import AppKit
import Observation
import SwiftUI
import TranslatorCore

/// Single source of truth for the shell: backend connection, current translation, history,
/// Anki state, settings. Views observe it; nothing else talks to `IPCClient` directly.
@MainActor
@Observable
final class AppModel {
    // Connection
    var connection: IPCClient.ConnectionState = .idle
    var ping: PingInfo?

    // Current translation
    var state = ViewState()
    var activeRequestId: Int = 0
    var phase: TranslationPhase = .final
    var lastError: String?

    // Ambient
    var banner: BannerMessage?
    /// Whether the app opens itself at login. Read from the system, never remembered:
    /// the user can change it in System Settings without the app hearing about it.
    var loginItem: LoginItemState = .notRegistered
    /// The note type's real field names, and why they could not be read. Empty with no
    /// error means nothing can be concluded, which is not the same as a mismatch.
    var ankiModelFields: [String] = []
    var ankiModelFieldsError: String?
    /// Progress per database file while a download runs; empty when none is.
    var databaseDownloads: [String: DatabaseProgressEvent] = [:]
    var history: [HistoryItem] = []
    var ankiStatus = AnkiStatus()
    var ankiDecks: [String] = []
    var settings = BackendSettings()
    var hotKey: KeyCombo = KeyCombo.defaultCombo
    var accessibilityTrusted: Bool = SelectionCapture.isTrusted
    /// Whether the current combination actually registered; another app may own it.
    var shortcutRegistered = true
    var appleTranslationReady = false

    // Anki sheet
    var upsertPreview: UpsertPreview?
    var isPreparingUpsert = false

    private let client: IPCClient
    private var bannerDismissTask: Task<Void, Never>?
    /// The last warning the backend sent, so an error phase can say why instead of
    /// "Translation failed."
    private var pendingNotice: String?

    struct BannerMessage: Equatable, Identifiable {
        let id = UUID()
        var text: String
        var level: NotificationLevel
    }

    init(client: IPCClient) {
        self.client = client
        client.onEvent = { [weak self] event in self?.handle(event) }
        client.onStateChange = { [weak self] state in self?.handle(connection: state) }
    }

    var isConnected: Bool { connection == .connected }

    var connectionSummary: String {
        switch connection {
        case .idle: return "Not connected"
        case let .connecting(attempt): return "Connecting… (\(attempt))"
        case .connected: return "Connected"
        case let .failed(message): return message
        }
    }

    // MARK: - Lifecycle

    func start() {
        client.start()
    }

    func stop() {
        client.stop()
    }

    private func handle(connection state: IPCClient.ConnectionState) {
        connection = state
        guard state == .connected else { return }
        Task { await refreshAll() }
    }

    func refreshAll() async {
        async let ping: Void = refreshPing()
        async let settings: Void = refreshSettings()
        async let anki: Void = refreshAnkiStatus()
        _ = await (ping, settings, anki)
    }

    // MARK: - Events

    private func handle(_ event: IPCEvent) {
        switch event.name {
        case IPCEventName.translationState:
            guard let payload = try? event.decode(TranslationStateEvent.self) else { return }
            guard payload.requestId >= activeRequestId else { return }  // stale request
            activeRequestId = payload.requestId
            phase = payload.phase
            withAnimation(Motion.stateChange) { state = payload.state }
            // The backend names the reason in a notification just before it reports the
            // error — "Every translation source is switched off." is not a failure to
            // retry, and calling it one sends the user looking for a fault.
            if payload.phase == .error { lastError = pendingNotice ?? "Translation failed." }
            pendingNotice = nil
        case IPCEventName.notification:
            guard let payload = try? event.decode(NotificationEvent.self) else { return }
            if payload.level != .info { pendingNotice = payload.message }
            show(banner: payload.message, level: payload.level)
        case IPCEventName.dbProgress:
            guard let payload = try? event.decode(DatabaseProgressEvent.self) else { return }
            apply(databaseProgress: payload)
        case IPCEventName.ankiAvailability:
            guard let payload = try? event.decode(AnkiAvailabilityEvent.self) else { return }
            ankiStatus.available = payload.available
        case IPCEventName.disconnected:
            state.loading = false
        default:
            break
        }
    }

    /// Drop whatever the popup was showing, so a bare message is not read as a result
    /// belonging to the previous lookup.
    func clearForAnnouncement() {
        state = ViewState()
        lastError = nil
    }

    func show(banner text: String, level: NotificationLevel) {
        bannerDismissTask?.cancel()
        withAnimation(Motion.stateChange) { banner = BannerMessage(text: text, level: level) }
        bannerDismissTask = Task { [weak self] in
            try? await Task.sleep(for: .seconds(level == .error ? 6 : 3))
            guard !Task.isCancelled else { return }
            await MainActor.run { withAnimation(Motion.stateChange) { self?.banner = nil } }
        }
    }

    // MARK: - Requests

    func refreshPing() async {
        ping = try? await client.send(IPCMethod.ping, as: PingInfo.self)
        if let ping { appleTranslationReady = ping.engines.appleTranslation }
    }

    /// The engine snapshot is cached for five minutes, so straight after a language pair
    /// finishes downloading the ping still reports it as merely supported and the setup
    /// stage keeps offering a download for a pair already on disk. This asks the backend
    /// to look again and answer in the same call.
    func refreshEngines() async {
        guard let engines = try? await client.send(
            IPCMethod.enginesRefresh, as: PingInfo.Engines.self
        ) else { return }
        ping?.engines = engines
        appleTranslationReady = engines.appleTranslation
    }

    /// Read the note type's fields, so a name that Anki does not have can be shown as
    /// wrong while the user is still looking at it, rather than failing at the moment a
    /// card is added.
    func loadModelFields() async {
        guard let answer = try? await client.send(
            IPCMethod.ankiModelFields, as: AnkiModelFields.self
        ) else {
            ankiModelFields = []
            ankiModelFieldsError = "The backend did not answer."
            return
        }
        ankiModelFields = answer.fields
        ankiModelFieldsError = answer.error
    }

    /// Configured names the note type does not have. Empty while nothing is known.
    var ankiFieldIssues: [AnkiFieldIssue] {
        AnkiFieldCheck.issues(
            configured: [
                settings.anki.fields.word,
                settings.anki.fields.translation,
                settings.anki.fields.exampleEn,
                settings.anki.fields.definitionsEn,
                settings.anki.fields.image,
            ],
            modelFields: ankiModelFields
        )
    }

    // MARK: - Open at login

    func refreshLoginItem() {
        loginItem = LoginItem.state
    }

    /// Turning it on asks the system for the registration; macOS may then want the user
    /// to approve it, which is a different state and not a failure.
    func setLoginItem(_ on: Bool) {
        do {
            if on { try LoginItem.enable() } else { try LoginItem.disable() }
        } catch {
            show(
                banner: on
                    ? "Could not turn on opening at login: \(error.localizedDescription)"
                    : "Could not turn off opening at login: \(error.localizedDescription)",
                level: .error
            )
        }
        // Ask the system what it now thinks rather than assuming the call decided it.
        refreshLoginItem()
    }

    // MARK: - Offline databases

    /// Only the app can ask for the 1.8 GB the offline sources need; until now the answer
    /// was "run a shell script", which is not something a setup stage can offer.
    func downloadDatabases() async {
        guard let start = try? await client.send(
            IPCMethod.dbDownload, as: DatabaseDownloadStart.self
        ) else {
            show(banner: "Could not start the download.", level: .error)
            return
        }
        guard start.started else {
            // Nothing missing: the button is safe to press and says so rather than
            // pretending to work.
            await refreshPing()
            show(banner: "The offline databases are already complete.", level: .info)
            return
        }
        databaseDownloads = start.files.reduce(into: [:]) { out, file in
            out[file] = DatabaseProgressEvent(file: file, state: .downloading)
        }
    }

    func cancelDatabaseDownload() async {
        _ = try? await client.send(IPCMethod.dbCancel)
    }

    private func apply(databaseProgress payload: DatabaseProgressEvent) {
        guard !payload.file.isEmpty else {
            // An empty file name is the whole operation ending, not one download.
            databaseDownloads = [:]
            if let error = payload.error { show(banner: error, level: .error) }
            Task { await refreshPing() }
            return
        }
        databaseDownloads[payload.file] = payload
        switch payload.state {
        case .failed:
            show(banner: payload.error ?? "\(payload.file) failed to download.", level: .error)
        case .done, .present:
            // Ask what the backend now sees rather than assuming the store is complete:
            // the other two files may still be arriving.
            Task { await refreshPing() }
        default:
            break
        }
        if databaseDownloads.values.allSatisfy({ $0.state == .done || $0.state == .present }) {
            databaseDownloads = [:]
        }
    }

    func translate(_ text: String) async {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        lastError = nil
        phase = .begin
        withAnimation(Motion.stateChange) {
            state = ViewState(original: trimmed, originalRaw: text, loading: true)
        }
        do {
            let response = try await client.send(IPCMethod.translate, params: ["text": text], as: TranslateResponse.self)
            activeRequestId = response.requestId
            withAnimation(Motion.stateChange) { state = response.state }
        } catch {
            state.loading = false
            lastError = message(for: error)
            show(banner: message(for: error), level: .error)
        }
    }

    func cancel() async {
        _ = try? await client.send(IPCMethod.cancel)
    }

    func closeSession() async {
        _ = try? await client.send(IPCMethod.close)
    }

    func refreshExamples() async {
        guard state.canRefreshExamples, !state.refreshingExamples else { return }
        state.refreshingExamples = true
        do {
            let response = try await client.send(IPCMethod.examplesRefresh, as: ExamplesRefreshResponse.self)
            withAnimation(Motion.stateChange) { state = response.state }
            if !response.changed { show(banner: "No other examples found.", level: .info) }
        } catch {
            state.refreshingExamples = false
            show(banner: message(for: error), level: .error)
        }
    }

    func copyAll() async {
        do {
            let response = try await client.send(IPCMethod.copyAll, as: CopyAllResponse.self)
            SelectionCapture.writeToPasteboard(response.text)
            show(banner: "Copied.", level: .success)
        } catch {
            show(banner: message(for: error), level: .error)
        }
    }

    func loadHistory() async {
        do {
            history = try await client.send(IPCMethod.historyList, as: HistoryListResponse.self).items
        } catch {
            show(banner: message(for: error), level: .error)
        }
    }

    func selectHistory(_ entryId: Int) async {
        do {
            let response = try await client.send(
                IPCMethod.historySelect, params: ["entry_id": entryId], as: TranslateResponse.self
            )
            activeRequestId = response.requestId
            withAnimation(Motion.stateChange) { state = response.state }
        } catch {
            show(banner: message(for: error), level: .error)
        }
    }

    // MARK: - Anki

    func refreshAnkiStatus() async {
        guard let status = try? await client.send(IPCMethod.ankiStatus, as: AnkiStatus.self) else { return }
        ankiStatus = status
    }

    func loadDecks() async {
        do {
            let response = try await client.send(IPCMethod.ankiDecks, as: AnkiDecksResponse.self)
            ankiDecks = response.decks
            if let error = response.error, !error.isEmpty { show(banner: error, level: .warning) }
        } catch {
            show(banner: message(for: error), level: .error)
        }
    }

    func selectDeck(_ deck: String) async {
        await runAction(IPCMethod.ankiSelectDeck, params: ["deck": deck])
    }

    func createModel() async {
        await runAction(IPCMethod.ankiCreateModel)
    }

    private func runAction(_ method: String, params: [String: Any] = [:]) async {
        do {
            let result = try await client.send(method, params: params, as: ActionResult.self)
            apply(result)
            if !result.message.isEmpty { show(banner: result.message, level: .success) }
        } catch {
            show(banner: message(for: error), level: .error)
        }
    }

    private func apply(_ result: ActionResult) {
        if let model = result.modelStatus { ankiStatus.modelStatus = model }
        if let deck = result.deckStatus { ankiStatus.deckStatus = deck }
        if let name = result.deckName { ankiStatus.deckName = name }
    }

    func prepareUpsert() async {
        isPreparingUpsert = true
        defer { isPreparingUpsert = false }
        do {
            let response = try await client.send(IPCMethod.ankiPrepareUpsert, as: UpsertPreviewResponse.self)
            upsertPreview = response.preview
        } catch {
            upsertPreview = nil
            show(banner: message(for: error), level: .error)
        }
    }

    func applyUpsert(_ decision: UpsertDecision) async -> Bool {
        do {
            let payload = try decision.jsonObject()
            let outcome = try await client.send(
                IPCMethod.ankiApplyUpsert, params: ["decision": payload], as: UpsertOutcome.self
            )
            if outcome.isSuccess {
                show(banner: outcome.message, level: .success)
            } else {
                show(banner: await explain(ankiFailure: outcome.message), level: .warning)
            }
            await refreshAnkiStatus()
            return outcome.isSuccess
        } catch {
            show(banner: message(for: error), level: .error)
            return false
        }
    }

    /// Anki's own words plus what they mean here.
    ///
    /// A mistyped field name makes Anki answer "cannot create note because it is empty",
    /// which sends the user looking at the card — the note is not empty, the name is
    /// wrong. The app knows both halves and can say so, so it does.
    private func explain(ankiFailure message: String) async -> String {
        // The field list may never have been read: nobody has to open the mapping
        // section for this to be the cause.
        if ankiModelFields.isEmpty, ankiModelFieldsError == nil { await loadModelFields() }
        return AnkiFieldCheck.explain(failure: message, issues: ankiFieldIssues)
    }

    // MARK: - Settings

    func refreshSettings() async {
        guard let data = try? await client.send(IPCMethod.settingsGet),
              let loaded = try? BackendSettings.decode(from: data)
        else { return }
        settings = loaded
    }

    func saveSettings() async {
        do {
            let payload = try settings.jsonObject()
            let result = try await client.send(IPCMethod.settingsSave, params: ["config": payload], as: ActionResult.self)
            apply(result)
            show(banner: result.message.isEmpty ? "Settings saved." : result.message, level: .success)
        } catch {
            show(banner: message(for: error), level: .error)
        }
    }

    func updateHotKey(_ combo: KeyCombo) {
        hotKey = combo
        UserDefaults.standard.set(combo.storageString, forKey: "hotKey")
    }

    func loadStoredHotKey() {
        if let raw = UserDefaults.standard.string(forKey: "hotKey"), let combo = KeyCombo(storageString: raw) {
            hotKey = combo
        }
    }

    func refreshAccessibilityTrust() {
        accessibilityTrusted = SelectionCapture.isTrusted
        // Written so scripts can read it: asking from a script answers for the script's
        // own parent process, never for this app.
        UserDefaults.standard.set(accessibilityTrusted, forKey: "accessibilityTrusted")
    }

    private func message(for error: Error) -> String {
        if let ipc = error as? IPCError { return ipc.message.isEmpty ? ipc.code : ipc.message }
        return error.localizedDescription
    }
}
