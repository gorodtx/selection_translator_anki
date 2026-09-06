import SwiftUI
import Translation
import TranslatorCore

/// Settings: shortcut, permissions, engines, Anki, database status.
struct SettingsView: View {
    @Bindable var model: AppModel
    var onHotKeyChange: (KeyCombo) -> Void

    var body: some View {
        GlassEffectContainer(spacing: 12) {
            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    shortcutCard
                    permissionsCard
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
        .frame(minWidth: 480, minHeight: 520)
        .task {
            model.refreshAccessibilityTrust()
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
                .font(.system(size: 11))
                .foregroundStyle(.tertiary)
        }
    }

    private var permissionsCard: some View {
        Card("Permissions") {
            StatusRow(
                title: "Accessibility",
                detail: model.accessibilityTrusted
                    ? "Granted — the shortcut can read the selection anywhere."
                    : "Not granted — the shortcut falls back to the Services menu.",
                ok: model.accessibilityTrusted
            )
            if !model.accessibilityTrusted {
                HStack(spacing: 8) {
                    Button("Request access") { SelectionCapture.requestTrust() }
                    Button("Open Accessibility Settings") { SelectionCapture.openAccessibilitySettings() }
                    Button("Re-check") { model.refreshAccessibilityTrust() }
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
            }
        }
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

            DisclosureGroup("Field mapping") {
                VStack(spacing: 6) {
                    FieldRow("Word", text: $model.settings.anki.fields.word)
                    FieldRow("Translation", text: $model.settings.anki.fields.translation)
                    FieldRow("Example", text: $model.settings.anki.fields.exampleEn)
                    FieldRow("Definitions", text: $model.settings.anki.fields.definitionsEn)
                    FieldRow("Image", text: $model.settings.anki.fields.image)
                }
                .padding(.top, 6)
            }
            .font(.secondaryText)
        }
    }

    private var databaseCard: some View {
        Card("Offline database") {
            if let db = model.ping?.db {
                StatusRow(title: "primary.sqlite3", detail: db.primary ? "Present" : "Missing", ok: db.primary)
                StatusRow(title: "fallback.sqlite3", detail: db.fallback ? "Present" : "Missing", ok: db.fallback)
                StatusRow(title: "definitions_pack.sqlite3", detail: db.definitions ? "Present" : "Missing", ok: db.definitions)
                Text(db.dir).font(.system(size: 10, design: .monospaced)).foregroundStyle(.tertiary).textSelection(.enabled)
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
                .font(.system(size: 12))
            VStack(alignment: .leading, spacing: 1) {
                Text(title).font(.system(size: 12, weight: .medium))
                Text(detail).font(.system(size: 11)).foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
    }
}

private struct FieldRow: View {
    let label: String
    @Binding var text: String

    init(_ label: String, text: Binding<String>) {
        self.label = label
        self._text = text
    }

    var body: some View {
        HStack {
            Text(label).font(.system(size: 11)).foregroundStyle(.secondary).frame(width: 90, alignment: .leading)
            TextField(label, text: $text).textFieldStyle(.roundedBorder).font(.system(size: 11))
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
                .font(.system(size: 13, weight: .medium, design: .rounded))
                .frame(minWidth: 92)
                .padding(.horizontal, 12)
                .padding(.vertical, 7)
                .contentShape(.rect(cornerRadius: Layout.chipRadius))
        }
        .buttonStyle(.plain)
        .glassSurface(radius: Layout.chipRadius, interactive: true, tint: isRecording ? .accentColor.opacity(0.35) : nil)
        .animation(Motion.stateChange, value: isRecording)
        .onDisappear { stop() }
        .accessibilityLabel("Shortcut \(combo.displayString)")
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
                Text(message).font(.system(size: 11)).foregroundStyle(.secondary)
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
