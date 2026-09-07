import AppKit
import SwiftUI
import TranslatorCore

/// Add-to-Anki flow: pick the values to send, choose between creating a new note or
/// updating matches, then apply. Mirrors the GTK dialog's decision model exactly.
struct AnkiUpsertSheet: View {
    @Bindable var model: AppModel
    var onFinished: (Bool) -> Void

    @State private var selectedTranslations: Set<String> = []
    @State private var selectedDefinitions: Set<String> = []
    @State private var selectedExamples: Set<String> = []
    @State private var translationAction: FieldAction = .mergeUniqueSelected
    @State private var definitionsAction: FieldAction = .mergeUniqueSelected
    @State private var examplesAction: FieldAction = .mergeUniqueSelected
    @State private var imageAction: ImageAction = .keepExisting
    @State private var imagePath: String?
    @State private var createNew = true
    @State private var targetNoteIds: Set<Int> = []
    @State private var isApplying = false

    var body: some View {
        GlassEffectContainer(spacing: 12) {
            VStack(alignment: .leading, spacing: 12) {
                header
                if model.isPreparingUpsert {
                    ProgressView("Reading your Anki collection…")
                        .frame(maxWidth: .infinity, minHeight: 160)
                } else if let preview = model.upsertPreview {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 12) {
                            valuesCard(preview)
                            targetCard(preview)
                            if !preview.matches.isEmpty { actionsCard }
                            imageCard
                        }
                    }
                    .scrollContentBackground(.hidden)
                } else {
                    Text("Nothing to add yet.")
                        .font(.secondaryText)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, minHeight: 160)
                }
                footer
            }
            .padding(Layout.gutter)
        }
        .frame(width: 560, height: 620)
        .task { await prepare() }
    }

    private var header: some View {
        HStack(alignment: .firstTextBaseline) {
            VStack(alignment: .leading, spacing: 2) {
                Text("Add to Anki").font(.sheetTitle)
                Text(model.state.originalText).font(.secondaryText).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer()
            if !model.ankiStatus.deckName.isEmpty {
                Text(model.ankiStatus.deckName)
                    .font(.captionText.weight(.medium))
                    .padding(.horizontal, 9).padding(.vertical, 5)
                    .glassSurface(radius: 8)
            }
        }
    }

    private func valuesCard(_ preview: UpsertPreview) -> some View {
        Card("Values") {
            CheckboxList(title: "Translations", items: preview.values.translations, selection: $selectedTranslations)
            if !preview.values.definitionsEn.isEmpty {
                CheckboxList(title: "Definitions", items: preview.values.definitionsEn, selection: $selectedDefinitions)
            }
            if !preview.values.examplesEn.isEmpty {
                CheckboxList(title: "Examples", items: preview.values.examplesEn, selection: $selectedExamples)
            }
        }
    }

    private func targetCard(_ preview: UpsertPreview) -> some View {
        Card("Target") {
            Picker("", selection: $createNew) {
                Text("Create a new note").tag(true)
                Text("Update existing notes").tag(false)
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .disabled(preview.matches.isEmpty)

            if preview.matches.isEmpty {
                Text("No existing note matches this word.")
                    .font(.captionText).foregroundStyle(.tertiary)
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(preview.matches) { match in
                        MatchRow(
                            match: match,
                            isSelected: targetNoteIds.contains(match.noteId),
                            enabled: !createNew
                        ) { toggle(match.noteId) }
                    }
                }
                .opacity(createNew ? 0.45 : 1)
                .animation(Motion.stateChange, value: createNew)
            }
        }
    }

    private var actionsCard: some View {
        Card("How to merge") {
            ActionPicker(title: "Translation", selection: $translationAction)
            ActionPicker(title: "Definitions", selection: $definitionsAction)
            ActionPicker(title: "Examples", selection: $examplesAction)
        }
        .disabled(createNew)
        .opacity(createNew ? 0.45 : 1)
    }

    private var imageCard: some View {
        Card("Image") {
            HStack(spacing: 8) {
                Button("Choose…") { chooseImage() }
                Button("Clear") { imagePath = nil; imageAction = .keepExisting }
                    .disabled(imagePath == nil)
                Spacer()
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            if let imagePath {
                Text((imagePath as NSString).lastPathComponent)
                    .font(.monoDetail)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                if !createNew {
                    Picker("On existing notes", selection: $imageAction) {
                        ForEach(ImageAction.allCases, id: \.self) { Text($0.title).tag($0) }
                    }
                    .pickerStyle(.menu)
                    .font(.captionText)
                }
            }
        }
    }

    private var footer: some View {
        HStack(spacing: 10) {
            if isApplying { ProgressView().controlSize(.small) }
            Spacer()
            Button("Cancel") { onFinished(false) }
                .keyboardShortcut(.cancelAction)
            Button("Apply") { Task { await apply() } }
                .keyboardShortcut(.defaultAction)
                .buttonStyle(.borderedProminent)
                .disabled(!canApply)
        }
    }

    private var canApply: Bool {
        guard !isApplying, model.upsertPreview != nil else { return false }
        if createNew { return !selectedTranslations.isEmpty || !selectedDefinitions.isEmpty || !selectedExamples.isEmpty }
        return !targetNoteIds.isEmpty
    }

    // MARK: - Actions

    private func prepare() async {
        await model.prepareUpsert()
        guard let preview = model.upsertPreview else { return }
        selectedTranslations = Set(preview.values.translations)
        selectedDefinitions = Set(preview.values.definitionsEn)
        selectedExamples = Set(preview.values.examplesEn)
        imagePath = preview.values.imagePath
        createNew = preview.matches.isEmpty
        targetNoteIds = preview.matches.isEmpty ? [] : [preview.matches[0].noteId]
    }

    private func toggle(_ noteId: Int) {
        if targetNoteIds.contains(noteId) { targetNoteIds.remove(noteId) } else { targetNoteIds.insert(noteId) }
    }

    private func chooseImage() {
        let dialog = NSOpenPanel()
        dialog.allowsMultipleSelection = false
        dialog.canChooseDirectories = false
        dialog.allowedContentTypes = [.png, .jpeg, .gif, .webP, .heic]
        guard dialog.runModal() == .OK, let url = dialog.url else { return }
        imagePath = url.path
        imageAction = .replaceWithSelected
    }

    private func apply() async {
        guard let preview = model.upsertPreview else { return }
        isApplying = true
        defer { isApplying = false }
        let decision = UpsertDecision(
            createNew: createNew,
            targetNoteIds: createNew ? [] : Array(targetNoteIds).sorted(),
            translationAction: translationAction,
            definitionsAction: definitionsAction,
            examplesAction: examplesAction,
            imageAction: imageAction,
            selectedTranslations: preview.values.translations.filter(selectedTranslations.contains),
            selectedDefinitionsEn: preview.values.definitionsEn.filter(selectedDefinitions.contains),
            selectedExamplesEn: preview.values.examplesEn.filter(selectedExamples.contains),
            imagePath: imagePath
        )
        let success = await model.applyUpsert(decision)
        onFinished(success)
    }
}

// MARK: - Pieces

private struct CheckboxList: View {
    let title: String
    let items: [String]
    @Binding var selection: Set<String>

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Text(title).font(.captionEmphasis).foregroundStyle(.secondary)
                Spacer()
                Button(selection.count == items.count ? "None" : "All") {
                    selection = selection.count == items.count ? [] : Set(items)
                }
                .buttonStyle(.plain)
                .font(.badgePlain)
                .foregroundStyle(.tertiary)
            }
            ForEach(items, id: \.self) { item in
                Toggle(isOn: Binding(
                    get: { selection.contains(item) },
                    set: { on in if on { selection.insert(item) } else { selection.remove(item) } }
                )) {
                    Text(item).font(.secondaryText).lineLimit(2)
                }
                .toggleStyle(.checkbox)
            }
        }
    }
}

private struct MatchRow: View {
    let match: UpsertMatch
    let isSelected: Bool
    let enabled: Bool
    var toggle: () -> Void

    var body: some View {
        Button(action: toggle) {
            HStack(alignment: .top, spacing: 9) {
                Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(isSelected ? Color.accentColor : Color.secondary)
                VStack(alignment: .leading, spacing: 2) {
                    Text(match.word).font(.controlLabel)
                    if !match.translation.isEmpty {
                        Text(match.translation).font(.captionText).foregroundStyle(.secondary).lineLimit(2)
                    }
                }
                Spacer(minLength: 0)
                if match.image?.isEmpty == false {
                    Image(systemName: "photo").font(.badgePlain).foregroundStyle(.tertiary)
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .contentShape(.rect(cornerRadius: Layout.innerRadius))
        }
        .buttonStyle(.plain)
        .background(
            RoundedRectangle(cornerRadius: Layout.innerRadius)
                .fill(Color.primary.opacity(isSelected ? 0.09 : 0.04))
        )
        .disabled(!enabled)
    }
}

private struct ActionPicker: View {
    let title: String
    @Binding var selection: FieldAction

    var body: some View {
        HStack {
            Text(title).font(.captionText).foregroundStyle(.secondary).frame(width: 92, alignment: .leading)
            Picker("", selection: $selection) {
                ForEach(FieldAction.allCases, id: \.self) { Text($0.title).tag($0) }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
        }
    }
}
