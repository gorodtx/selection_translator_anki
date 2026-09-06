import SwiftUI
import TranslatorCore

/// Past lookups. Selecting a row re-opens it in the popup without hitting the network.
struct HistoryView: View {
    @Bindable var model: AppModel
    var onSelect: (Int) -> Void

    @State private var query = ""
    @Namespace private var glassNamespace

    private var filtered: [HistoryItem] {
        let needle = query.trimmingCharacters(in: .whitespaces).lowercased()
        guard !needle.isEmpty else { return model.history }
        return model.history.filter {
            $0.text.lowercased().contains(needle) || $0.translation.lowercased().contains(needle)
        }
    }

    var body: some View {
        GlassEffectContainer(spacing: 10) {
            VStack(alignment: .leading, spacing: 12) {
                HStack(spacing: 8) {
                    Image(systemName: "magnifyingglass").foregroundStyle(.tertiary)
                    TextField("Search history", text: $query)
                        .textFieldStyle(.plain)
                        .font(.bodyText)
                    if !query.isEmpty {
                        Button { query = "" } label: { Image(systemName: "xmark.circle.fill") }
                            .buttonStyle(.plain)
                            .foregroundStyle(.tertiary)
                    }
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 9)
                .glassSurface(radius: 12)

                if filtered.isEmpty {
                    emptyState
                } else {
                    ScrollView {
                        LazyVStack(alignment: .leading, spacing: 6) {
                            ForEach(filtered) { item in
                                HistoryRow(item: item) { onSelect(item.entryId) }
                                    .glassEffectUnion(id: "history", namespace: glassNamespace)
                            }
                        }
                        .padding(.vertical, 2)
                    }
                    .scrollContentBackground(.hidden)
                }
            }
            .padding(Layout.gutter)
        }
        .frame(minWidth: 420, minHeight: 380)
        .animation(Motion.content, value: filtered)
        .task { await model.loadHistory() }
    }

    private var emptyState: some View {
        VStack(spacing: 8) {
            Image(systemName: "clock.arrow.circlepath")
                .font(.system(size: 26, weight: .light))
                .foregroundStyle(.tertiary)
            Text(model.history.isEmpty ? "Nothing translated yet." : "No matches.")
                .font(.secondaryText)
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private struct HistoryRow: View {
    let item: HistoryItem
    var action: () -> Void

    @State private var isHovering = false

    var body: some View {
        Button(action: action) {
            VStack(alignment: .leading, spacing: 3) {
                Text(item.text)
                    .font(.system(size: 13, weight: .medium))
                    .lineLimit(1)
                Text(item.translation.isEmpty ? "—" : item.translation)
                    .font(.secondaryText)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 12)
            .padding(.vertical, 9)
            .contentShape(.rect(cornerRadius: Layout.innerRadius))
        }
        .buttonStyle(.plain)
        .background(
            RoundedRectangle(cornerRadius: Layout.innerRadius)
                .fill(Color.primary.opacity(isHovering ? 0.09 : 0.045))
        )
        .onHover { isHovering = $0 }
        .animation(Motion.stateChange, value: isHovering)
    }
}
