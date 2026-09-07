import SwiftUI
import Translation
import TranslatorCore

/// Settings: setup stages first, then shortcut, engines, Anki and database detail.
///
/// The permissions card is gone: it said the same thing as the setup stage above it, and
/// two rows claiming the same state is how they drift apart.
struct SettingsView: View {
    @State private var fieldMappingOpen = false
    @Bindable var model: AppModel
    var onHotKeyChange: (KeyCombo) -> Void

    private static let shortcutAnchor = "shortcut-card"

    var body: some View {
        GlassEffectContainer(spacing: 12) {
            ScrollViewReader { scroller in
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    // What a fresh install still has to do, before the detail below.
                    SetupCard(model: model) {
                        // The recorder lives further down this window, so the stage hands
                        // the user to it instead of opening a second place to do it.
                        withAnimation(Motion.stateChange) { scroller.scrollTo(Self.shortcutAnchor, anchor: .top) }
                    }
                    shortcutCard.id(Self.shortcutAnchor)
                    sourcesCard
                    enginesCard
                    ankiCard
                    databaseCard
                    HStack {
                        Spacer()
                        Button("Save settings") { Task { await model.saveSettings() } }
                            .buttonStyle(.borderedProminent)
                            .disabled(!model.isConnected)
                    }
                }
                .padding(Layout.gutter)
            }
            .scrollContentBackground(.hidden)
            }
        }
        .frame(minWidth: 480, minHeight: 520)
        .task {
            model.refreshAccessibilityTrust()
            // Read from the system, not from memory: the user can turn this off in
            // System Settings and the app is never told.
            model.refreshLoginItem()
            await model.refreshAll()
        }
    }

    // MARK: - Cards

    private var shortcutCard: some View {
        Card("Shortcut") {
            HStack(spacing: 12) {
                Text("Translate selection")
                    .font(.bodyText)
                Spacer()
                HotKeyRecorder(combo: model.hotKey) { combo in
                    model.updateHotKey(combo)
                    onHotKeyChange(combo)
                }
            }
            Text("Also available from the Services menu on any selected text, with no permissions.")
                .font(.captionText)
                .foregroundStyle(.tertiary)

            Divider().opacity(0.4)
            loginItemRow
        }
    }

    /// The shortcut belongs to this process, so it is gone whenever the app is not
    /// running. The backend's own login agent covers only the backend, which is what made
    /// this easy to miss: after a restart the daemon answers and nothing else does. The
    /// switch lives next to the shortcut for that reason, and reads from the system every
    /// time — the user can change it in System Settings without the app hearing.
    @ViewBuilder
    private var loginItemRow: some View {
        Toggle(isOn: Binding(
            get: { model.loginItem.isOn },
            set: { model.setLoginItem($0) }
        )) {
            VStack(alignment: .leading, spacing: 1) {
                Text("Open at login").font(.controlLabel)
                Text("Without it the shortcut works only after the app is opened by hand.")
                    .font(.captionText)
                    .foregroundStyle(.secondary)
            }
        }
        .toggleStyle(.switch)
        .controlSize(.small)
        .accessibilityLabel("Open at login")
        .accessibilityHint("Registers the app to start itself when you log in.")

        if model.loginItem == .requiresApproval {
            // Registered already; the one remaining click is the user's to make.
            HStack(spacing: 8) {
                Text("Waiting for your approval in System Settings.")
                    .font(.captionText)
                    .foregroundStyle(Color.orange)
                Button("Open…") { LoginItem.openSettings() }
                    .buttonStyle(.bordered)
                    .controlSize(.small)
                Spacer()
            }
        } else if model.loginItem == .unavailable {
            Text("The system reported a state this version does not understand.")
                .font(.captionText)
                .foregroundStyle(.secondary)
        }
    }

    private var issues: [AnkiFieldIssue] { model.ankiFieldIssues }


    /// What is known about the note type, said plainly. The three states are different
    /// answers and must not read alike: names were read and compared, the question could
    /// not be asked, or the answer was empty and settles nothing.
    @ViewBuilder
    private var fieldMappingFooter: some View {
        if let error = model.ankiModelFieldsError {
            Text(error)
                .font(.captionText)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        } else if model.ankiModelFields.isEmpty {
            Text("Nothing to compare against yet — the note type may not exist. Create it above.")
                .font(.captionText)
                .foregroundStyle(.tertiary)
                .fixedSize(horizontal: false, vertical: true)
        } else if issues.isEmpty {
            Text("All five match the note type: \(model.ankiModelFields.joined(separator: ", ")).")
                .font(.captionText)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        } else {
            Text("The note type has: \(model.ankiModelFields.joined(separator: ", ")).")
                .font(.captionText)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    /// Which sources may answer a lookup.
    ///
    /// Switching one off is a real question — is the network worth the wait, is a
    /// dictionary card too much — so each row says what it contributes and what happens
    /// without it, rather than leaving the user to experiment.
    private var sourcesCard: some View {
        Card("Sources") {
            sourceToggle(
                "Apple Dictionary",
                "Senses, transcription and example pairs, offline in milliseconds.",
                isOn: $model.settings.sources.appleDictionary
            )
            sourceToggle(
                "Apple Translation",
                "Phrases and sentences offline. Off, they wait for the network.",
                isOn: $model.settings.sources.appleTranslation
            )
            sourceToggle(
                "Google",
                "Network fallback, and the only source for rarer phrasing.",
                isOn: $model.settings.sources.google
            )
            sourceToggle(
                "Cambridge",
                "Network dictionary; the slowest source and the most fragile.",
                isOn: $model.settings.sources.cambridge
            )
            sourceToggle(
                "Offline examples",
                "The 1.7 GB corpus behind most of the example sentences.",
                isOn: $model.settings.sources.offlineExamples
            )
            sourceToggle(
                "Definitions pack",
                "English definitions from the offline pack.",
                isOn: $model.settings.sources.definitionsPack
            )
            Text("Changes apply after Save settings.")
                .font(.captionText)
                .foregroundStyle(.tertiary)
        }
    }

    private func sourceToggle(_ title: String, _ detail: String, isOn: Binding<Bool>) -> some View {
        Toggle(isOn: isOn) {
            VStack(alignment: .leading, spacing: 1) {
                Text(title).font(.controlLabel)
                Text(detail).font(.captionText).foregroundStyle(.secondary)
            }
        }
        .toggleStyle(.switch)
        .controlSize(.small)
        // A two-line label built from a stack reaches assistive technology as an unnamed
        // switch, and six of them are indistinguishable. Name each one, and let the
        // explanation be the hint rather than part of the name.
        .accessibilityLabel(title)
        .accessibilityHint(detail)
    }

    private var enginesCard: some View {
        Card("On-device engines") {
            StatusRow(
                title: "Apple Dictionary",
                detail: (model.ping?.engines.appleDictionary ?? false)
                    ? dictionarySummary
                    : "Not detected by the backend.",
                ok: model.ping?.engines.appleDictionary ?? false
            )
            StatusRow(
                title: "Apple Translation",
                detail: (model.ping?.engines.appleTranslation ?? false)
                    ? "Language pair installed — offline translation."
                    : "Language pair not downloaded (\(model.ping?.engines.translationStatus ?? "unknown")).",
                ok: model.ping?.engines.appleTranslation ?? false
            )
            if !(model.ping?.engines.appleTranslation ?? false) {
                LanguagePairDownloadButton(
                    source: model.settings.languages.source,
                    target: model.settings.languages.target
                ) {
                    Task { await model.refreshPing() }
                }
            }
        }
    }

    private var ankiCard: some View {
        Card("Anki") {
            StatusRow(
                title: "AnkiConnect",
                detail: model.ankiStatus.available ? "Reachable." : "Not reachable — is Anki running?",
                ok: model.ankiStatus.available
            )
            LabeledContent("Model") { Text(statusText(model.ankiStatus.modelStatus)).foregroundStyle(.secondary) }
            LabeledContent("Deck") {
                Text(model.ankiStatus.deckName.isEmpty ? statusText(model.ankiStatus.deckStatus) : model.ankiStatus.deckName)
                    .foregroundStyle(.secondary)
            }
            .font(.secondaryText)

            HStack(spacing: 8) {
                Button("List decks") { Task { await model.loadDecks() } }
                Button("Create model") { Task { await model.createModel() } }
                Spacer()
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .disabled(!model.isConnected)

            if !model.ankiDecks.isEmpty {
                Picker("Deck", selection: Binding(
                    get: { model.settings.anki.deck },
                    set: { deck in
                        model.settings.anki.deck = deck
                        Task { await model.selectDeck(deck) }
                    }
                )) {
                    ForEach(model.ankiDecks, id: \.self) { Text($0).tag($0) }
                }
                .pickerStyle(.menu)
                .font(.secondaryText)
            }

            DisclosureGroup("Field mapping", isExpanded: $fieldMappingOpen) {
                VStack(spacing: 6) {
                    FieldRow("Word", text: $model.settings.anki.fields.word, issues: issues)
                    FieldRow("Translation", text: $model.settings.anki.fields.translation, issues: issues)
                    FieldRow("Example", text: $model.settings.anki.fields.exampleEn, issues: issues)
                    FieldRow("Definitions", text: $model.settings.anki.fields.definitionsEn, issues: issues)
                    FieldRow("Image", text: $model.settings.anki.fields.image, issues: issues)
                    fieldMappingFooter
                }
                .padding(.top, 6)
            }
            .font(.secondaryText)
            // Asked when the section opens rather than on every settings visit: it is a
            // question to another program, and nobody needs the answer while the section
            // is closed.
            .onChange(of: fieldMappingOpen) { _, open in
                if open { Task { await model.loadModelFields() } }
            }
        }
    }

    private var databaseCard: some View {
        Card("Offline database") {
            if let db = model.ping?.db {
                StatusRow(title: "primary.sqlite3", detail: db.primary ? "Present" : "Missing", ok: db.primary)
                StatusRow(title: "fallback.sqlite3", detail: db.fallback ? "Present" : "Missing", ok: db.fallback)
                StatusRow(title: "definitions_pack.sqlite3", detail: db.definitions ? "Present" : "Missing", ok: db.definitions)
                Text(db.dir).font(.monoDetail).foregroundStyle(.tertiary).textSelection(.enabled)
            } else {
                Text(model.connectionSummary).font(.secondaryText).foregroundStyle(.secondary)
            }
        }
    }

    private func statusText(_ raw: String) -> String {
        raw.isEmpty ? "—" : raw
    }

    private var dictionarySummary: String {
        let names = model.ping?.engines.dictionaries ?? []
        guard !names.isEmpty else { return "Available — offline definitions and examples." }
        return names.joined(separator: ", ")
    }
}

// MARK: - Building blocks

struct Card<Content: View>: View {
    let title: String
    @ViewBuilder var content: Content

    init(_ title: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionLabel(title)
            content
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .glassSurface(radius: 18)
    }
}

struct StatusRow: View {
    let title: String
    let detail: String
    let ok: Bool

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Image(systemName: ok ? "checkmark.circle.fill" : "exclamationmark.circle")
                .foregroundStyle(ok ? Color.green : Color.orange)
                .font(.secondaryText)
            VStack(alignment: .leading, spacing: 1) {
                Text(title).font(.controlLabel)
                Text(detail).font(.captionText).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
    }
}

private struct FieldRow: View {
    let label: String
    @Binding var text: String
    let issues: [AnkiFieldIssue]

    init(_ label: String, text: Binding<String>, issues: [AnkiFieldIssue] = []) {
        self.label = label
        self._text = text
        self.issues = issues
    }

    /// Set only when the note type was read and does not have this name — never while
    /// the answer is unknown.
    private var issue: AnkiFieldIssue? {
        issues.first { $0.configured == text }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack {
                Text(label).font(.captionText).foregroundStyle(.secondary).frame(width: 90, alignment: .leading)
                TextField(label, text: $text).textFieldStyle(.roundedBorder).font(.captionText)
                if issue != nil {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundStyle(Color.orange)
                        .font(.captionText)
                        .accessibilityLabel("Not a field of the note type")
                }
            }
            if let issue {
                // Naming the near miss turns a hunt into a correction, and a plain
                // "no such field" into something actionable.
                Text(issue.suggestion.map { "The note type has no \"\(issue.configured)\". Did you mean \"\($0)\"?" }
                    ?? "The note type has no \"\(issue.configured)\". A card would fail to add.")
                    .font(.captionText)
                    .foregroundStyle(Color.orange)
                    .padding(.leading, 98)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

/// Records a new global shortcut. Feedback is on key-down, and Esc cancels.
struct HotKeyRecorder: View {
    var combo: KeyCombo
    var onChange: (KeyCombo) -> Void

    @State private var isRecording = false
    @State private var monitor: Any?

    var body: some View {
        Button {
            isRecording ? stop() : start()
        } label: {
            Text(isRecording ? "Press keys…" : combo.displayString)
                .font(.actionLabel)
                .frame(minWidth: 92)
                .padding(.horizontal, 12)
                .padding(.vertical, 7)
                .contentShape(.rect(cornerRadius: Layout.chipRadius))
        }
        .buttonStyle(.plain)
        .glassSurface(radius: Layout.chipRadius, interactive: true, tint: isRecording ? .accentColor.opacity(0.35) : nil)
        .animation(Motion.stateChange, value: isRecording)
        .onDisappear { stop() }
        // The visible text changes to "Press keys…" while recording, so the label must not
        // pin the old combination: the name says what the control is, the value says what
        // it holds or that it is waiting.
        .accessibilityLabel("Shortcut")
        .accessibilityValue(isRecording ? "Waiting for a key combination" : combo.displayString)
        .accessibilityHint(
            isRecording
                ? "Press the keys to use, or Escape to cancel."
                : "Activate, then press the keys to use."
        )
    }

    private func start() {
        isRecording = true
        monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            MainActor.assumeIsolated {
                if event.keyCode == 53 { stop(); return }
                if let recorded = KeyComboRecorder.combo(from: event) {
                    onChange(recorded)
                    stop()
                }
            }
            return nil
        }
    }

    private func stop() {
        isRecording = false
        if let monitor { NSEvent.removeMonitor(monitor) }
        monitor = nil
    }
}

/// Downloads an Apple translation language pair. The system sheet only appears from a
/// SwiftUI `translationTask`; a headless process cannot request the download itself.
struct LanguagePairDownloadButton: View {
    var source: String
    var target: String
    var onFinished: () -> Void

    @State private var configuration: TranslationSession.Configuration?
    @State private var isWorking = false
    @State private var message: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Button {
                message = nil
                isWorking = true
                configuration = TranslationSession.Configuration(
                    source: Locale.Language(identifier: source),
                    target: Locale.Language(identifier: target)
                )
            } label: {
                HStack(spacing: 6) {
                    if isWorking { ProgressView().controlSize(.mini) }
                    Text("Download \(source.uppercased()) → \(target.uppercased()) offline model")
                }
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .disabled(isWorking)

            if let message {
                Text(message).font(.captionText).foregroundStyle(.secondary)
            }
        }
        .translationTask(configuration) { session in
            do {
                try await session.prepareTranslation()
                await MainActor.run {
                    message = "Language pair ready."
                    isWorking = false
                    onFinished()
                }
            } catch {
                await MainActor.run {
                    message = "Download failed: \(error.localizedDescription)"
                    isWorking = false
                }
            }
        }
    }
}
