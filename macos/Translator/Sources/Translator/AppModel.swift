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
    var history: [HistoryItem] = []
    var ankiStatus = AnkiStatus()
    var ankiDecks: [String] = []
    var settings = BackendSettings()
    var hotKey: KeyCombo = KeyCombo.defaultCombo
    var accessibilityTrusted: Bool = SelectionCapture.isTrusted
    var appleTranslationReady = false

    // Anki sheet
    var upsertPreview: UpsertPreview?
    var isPreparingUpsert = false

    private let client: IPCClient
    private var bannerDismissTask: Task<Void, Never>?

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
            if payload.phase == .error { lastError = "Translation failed." }
        case IPCEventName.notification:
            guard let payload = try? event.decode(NotificationEvent.self) else { return }
            show(banner: payload.message, level: payload.level)
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
            show(banner: outcome.message, level: outcome.isSuccess ? .success : .warning)
            await refreshAnkiStatus()
            return outcome.isSuccess
        } catch {
            show(banner: message(for: error), level: .error)
            return false
        }
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
    }

    private func message(for error: Error) -> String {
        if let ipc = error as? IPCError { return ipc.message.isEmpty ? ipc.code : ipc.message }
        return error.localizedDescription
    }
}
