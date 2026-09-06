import SwiftUI
import TranslatorCore

/// The card that appears next to the pointer. One glass container so the sections read as
/// one physical object; sections morph between phases instead of being replaced.
struct TranslationPopupView: View {
    @Bindable var model: AppModel
    var onClose: () -> Void
    var onOpenAnki: () -> Void

    @Namespace private var glassNamespace
    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    var body: some View {
        GlassEffectContainer(spacing: 12) {
            VStack(alignment: .leading, spacing: Layout.sectionGap) {
                header
                if model.state.loading && !model.state.hasTranslation {
                    loadingRow
                }
                if model.state.hasTranslation {
                    translationSection
                }
                if let apple = model.state.apple, apple.hasContent {
                    appleSection(apple)
                }
                if !model.state.definitionsItems.isEmpty {
                    definitionsSection
                }
                if !model.state.examples.isEmpty {
                    examplesSection
                }
                if let error = model.lastError, !model.state.hasTranslation {
                    Text(error)
                        .font(.secondaryText)
                        .foregroundStyle(.secondary)
                }
                actionBar
            }
            .padding(Layout.gutter)
            .frame(width: PopupLayout.preferredWidth(for: model.state), alignment: .leading)
            .glassSurface(radius: Layout.cardRadius)
            .overlay(alignment: .top) { bannerOverlay }
        }
        .animation(Motion.content, value: model.state)
        .animation(Motion.stateChange, value: model.banner)
    }

    // MARK: - Sections

    private var header: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            VStack(alignment: .leading, spacing: 2) {
                Text(model.state.original.isEmpty ? "—" : model.state.original)
                    .font(.popupHeadword)
                    .tracking(-0.4)
                    .lineLimit(3)
                    .textSelection(.enabled)
                if let apple = model.state.apple, !apple.ipaUk.isEmpty || !apple.ipaUs.isEmpty {
                    HStack(spacing: 10) {
                        if !apple.ipaUk.isEmpty { ipaBadge("BrE", apple.ipaUk) }
                        if !apple.ipaUs.isEmpty { ipaBadge("AmE", apple.ipaUs) }
                    }
                }
            }
            Spacer(minLength: 8)
            Button(action: onClose) {
                Image(systemName: "xmark")
                    .font(.system(size: 11, weight: .semibold))
                    .frame(width: 22, height: 22)
            }
            .buttonStyle(.plain)
            .glassSurface(radius: 11, interactive: true)
            .help("Close (Esc)")
            .accessibilityLabel("Close")
        }
    }

    private func ipaBadge(_ dialect: String, _ value: String) -> some View {
        HStack(spacing: 4) {
            Text(dialect).font(.system(size: 9, weight: .bold)).foregroundStyle(.tertiary)
            Text(value).font(.monoIPA).foregroundStyle(.secondary)
        }
    }

    private var loadingRow: some View {
        HStack(spacing: 8) {
            ProgressView().controlSize(.small)
            Text("Translating…").font(.secondaryText).foregroundStyle(.secondary)
        }
        .transition(.opacity)
    }

    private var translationSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            SectionLabel("Translation") {
                if model.state.loading {
                    ProgressView().controlSize(.mini)
                }
            }
            Text(model.state.translation)
                .font(.popupTranslation)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.vertical, 8)
                .padding(.horizontal, 10)
                .innerSurface()
                .glassEffectID("translation", in: glassNamespace)
        }
    }

    private func appleSection(_ apple: AppleLexical) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionLabel("Dictionary")
            ForEach(Array(apple.groupedEntries.enumerated()), id: \.offset) { _, entry in
                VStack(alignment: .leading, spacing: 5) {
                    if !entry.pos.isEmpty {
                        Text(entry.pos)
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(.secondary)
                    }
                    ForEach(Array(entry.senses.enumerated()), id: \.offset) { _, sense in
                        senseRow(sense)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.vertical, 8)
                .padding(.horizontal, 10)
                .innerSurface()
            }
        }
    }

    private func senseRow(_ sense: AppleSense) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Text("\(sense.index)")
                .font(.system(size: 10, weight: .bold, design: .rounded))
                .foregroundStyle(.tertiary)
                .frame(minWidth: 12, alignment: .trailing)
            VStack(alignment: .leading, spacing: 2) {
                HStack(alignment: .firstTextBaseline, spacing: 5) {
                    if !sense.label.isEmpty {
                        Text("(\(sense.label))")
                            .font(.system(size: 11))
                            .foregroundStyle(.tertiary)
                    }
                    Text(sense.translation).font(.bodyText).textSelection(.enabled)
                }
                ForEach(Array(sense.examples.prefix(2).enumerated()), id: \.offset) { _, pair in
                    VStack(alignment: .leading, spacing: 1) {
                        Text(pair.en).font(.system(size: 11)).foregroundStyle(.secondary)
                        if !pair.ru.isEmpty {
                            Text(pair.ru).font(.system(size: 11)).foregroundStyle(.tertiary)
                        }
                    }
                }
            }
        }
        .fixedSize(horizontal: false, vertical: true)
    }

    private var definitionsSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            SectionLabel("Definitions")
            VStack(alignment: .leading, spacing: 6) {
                ForEach(Array(model.state.definitionsItems.enumerated()), id: \.offset) { index, item in
                    HStack(alignment: .firstTextBaseline, spacing: 7) {
                        Text("\(index + 1)")
                            .font(.system(size: 10, weight: .bold, design: .rounded))
                            .foregroundStyle(.tertiary)
                            .frame(minWidth: 12, alignment: .trailing)
                        Text(item)
                            .font(.bodyText)
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, 8)
            .padding(.horizontal, 10)
            .innerSurface()
        }
    }

    private var examplesSection: some View {
        VStack(alignment: .leading, spacing: 6) {
            SectionLabel("Examples") {
                if model.state.refreshingExamples {
                    ProgressView().controlSize(.mini)
                }
            }
            VStack(alignment: .leading, spacing: 6) {
                ForEach(Array(model.state.examples.enumerated()), id: \.offset) { _, example in
                    HStack(alignment: .firstTextBaseline, spacing: 7) {
                        Text("▸").font(.system(size: 10)).foregroundStyle(.tertiary)
                        Text(example.en)
                            .font(.bodyText)
                            .textSelection(.enabled)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .transition(.opacity)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.vertical, 8)
            .padding(.horizontal, 10)
            .innerSurface()
        }
    }

    private var actionBar: some View {
        HStack(spacing: 8) {
            PopupAction(title: "Copy all", symbol: "doc.on.doc", enabled: model.state.hasTranslation) {
                Task { await model.copyAll() }
            }
            PopupAction(
                title: "Examples",
                symbol: "arrow.triangle.2.circlepath",
                enabled: model.state.canRefreshExamples && !model.state.refreshingExamples
            ) {
                Task { await model.refreshExamples() }
            }
            Spacer(minLength: 0)
            PopupAction(
                title: "Add to Anki",
                symbol: "plus.rectangle.on.rectangle",
                prominent: true,
                enabled: model.state.canAddAnki && model.ankiStatus.available,
                action: onOpenAnki
            )
        }
    }

    @ViewBuilder
    private var bannerOverlay: some View {
        if let banner = model.banner {
            HStack(spacing: 7) {
                Image(systemName: banner.level.symbol).foregroundStyle(banner.level.tint)
                Text(banner.text).font(.secondaryText).lineLimit(2)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .glassSurface(radius: 13, tint: banner.level.tint.opacity(0.22))
            .padding(.top, -10)
            .transition(.move(edge: .top).combined(with: .opacity))
            .accessibilityAddTraits(.isStaticText)
        }
    }
}

/// Small glass button used in the popup's action bar.
struct PopupAction: View {
    var title: String
    var symbol: String
    var prominent = false
    var enabled: Bool
    var action: () -> Void

    @State private var isPressed = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 5) {
                Image(systemName: symbol).font(.system(size: 11, weight: .semibold))
                Text(title).font(.system(size: 12, weight: .medium))
            }
            .padding(.horizontal, 11)
            .padding(.vertical, 7)
            .contentShape(.rect(cornerRadius: Layout.chipRadius))
        }
        .buttonStyle(.plain)
        .glassSurface(radius: Layout.chipRadius, interactive: true, tint: prominent ? .accentColor.opacity(0.35) : nil)
        // Feedback on press-down, not on release.
        .scaleEffect(isPressed ? 0.97 : 1)
        .animation(Motion.stateChange, value: isPressed)
        .opacity(enabled ? 1 : 0.4)
        .disabled(!enabled)
        .onLongPressGesture(minimumDuration: 0, pressing: { isPressed = $0 && enabled }, perform: {})
        .accessibilityLabel(title)
    }
}
