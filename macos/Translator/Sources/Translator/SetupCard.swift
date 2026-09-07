import SwiftUI
import Translation
import TranslatorCore

/// The stages a fresh install has to pass, at the top of Settings.
///
/// Each row says what the stage is for, whether it is done, and carries the one button
/// that advances it. What is blocking, what is merely suggested and whether the app is
/// usable yet is decided by `SetupPlanner`, which is under test; this only draws it.
struct SetupCard: View {
    @Bindable var model: AppModel
    var onRecordShortcut: () -> Void

    /// Set while the language pair downloads, so the row can show progress.
    @State private var pairConfiguration: TranslationSession.Configuration?
    @State private var pairMessage: String?
    @State private var pairWorking = false

    private var plan: SetupPlan {
        SetupPlanner.plan(
            connected: model.isConnected,
            ping: model.ping,
            accessibilityTrusted: model.accessibilityTrusted,
            shortcutRegistered: model.shortcutRegistered,
            shortcut: model.hotKey.displayString,
            loginItem: LoginItem.state,
            anki: model.ankiStatus
        )
    }

    var body: some View {
        let plan = plan
        Card("Setup") {
            VStack(alignment: .leading, spacing: 10) {
                summary(for: plan)
                ForEach(plan.steps) { step in
                    row(step)
                    if step.id != plan.steps.last?.id { Divider().opacity(0.12) }
                }
                if let pairMessage {
                    Text(pairMessage).font(.captionText).foregroundStyle(.secondary)
                }
            }
        }
        // The system download sheet only appears from a translationTask, so the row's
        // button sets a configuration and the work happens here.
        .translationTask(pairConfiguration) { session in
            do {
                try await session.prepareTranslation()
                await MainActor.run {
                    pairMessage = "Language pair ready."
                    pairWorking = false
                    pairConfiguration = nil
                }
                // The snapshot is cached for five minutes, so without this the stage
                // would keep offering a download for the pair just installed.
                await model.refreshEngines()
            } catch {
                await MainActor.run {
                    pairMessage = "Download failed: \(error.localizedDescription)"
                    pairWorking = false
                    pairConfiguration = nil
                }
            }
        }
    }

    // MARK: - Pieces

    private func summary(for plan: SetupPlan) -> some View {
        HStack(spacing: 8) {
            Image(systemName: plan.isReady ? "checkmark.seal.fill" : "arrow.right.circle.fill")
                .foregroundStyle(plan.isReady ? Color.green : Color.accentColor)
                .font(.popupTranslation)
            Text(plan.summary)
                .font(.controlLabel)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
            Button("Re-check") {
                model.refreshAccessibilityTrust()
                Task { await model.refreshAll() }
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
        }
    }

    private func row(_ step: SetupStep) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 9) {
            icon(for: step)
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(step.title).font(.controlLabel)
                    if step.isOptional, step.state != .done {
                        Text("optional")
                            .font(.badgePlain)
                            .foregroundStyle(.tertiary)
                            .padding(.horizontal, 5)
                            .padding(.vertical, 1)
                            .innerSurface(radius: 5)
                    }
                }
                Text(detail(for: step))
                    .font(.captionText)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                if step.id == .databases, !model.databaseDownloads.isEmpty {
                    ProgressView(value: databaseFraction)
                        .progressViewStyle(.linear)
                        .controlSize(.small)
                }
            }
            Spacer(minLength: 8)
            action(for: step)
        }
    }

    /// While files are arriving the row says which one and how far, because 1.8 GB with no
    /// sign of movement is indistinguishable from a stall.
    private func detail(for step: SetupStep) -> String {
        guard step.id == .databases, !model.databaseDownloads.isEmpty else { return step.detail }
        let active = model.databaseDownloads.values
            .filter { $0.state == .downloading || $0.state == .verifying }
            .sorted { $0.file < $1.file }
        guard let current = active.first else { return "Checking what arrived…" }
        let done = model.databaseDownloads.values.filter { $0.state == .done || $0.state == .present }
        let queue = model.databaseDownloads.count > 1
            ? " (\(done.count + 1) of \(model.databaseDownloads.count))"
            : ""
        if current.state == .verifying { return "Verifying \(current.file)\(queue)" }
        guard current.total > 0 else { return "Downloading \(current.file)\(queue)" }
        let received = ByteCountFormatter.string(fromByteCount: Int64(current.received), countStyle: .file)
        let total = ByteCountFormatter.string(fromByteCount: Int64(current.total), countStyle: .file)
        return "\(current.file) — \(received) of \(total)\(queue)"
    }

    /// One bar for the whole operation: per-file bars jumping back to zero read as failure.
    private var databaseFraction: Double {
        let files = model.databaseDownloads.values
        guard !files.isEmpty else { return 0 }
        let share = files.reduce(0.0) { total, file in
            switch file.state {
            case .done, .present: return total + 1
            case .downloading where file.total > 0:
                return total + Double(file.received) / Double(file.total)
            default: return total
            }
        }
        return share / Double(files.count)
    }

    /// Shape carries the state, not colour alone: a check, a chevron or a spinner.
    @ViewBuilder
    private func icon(for step: SetupStep) -> some View {
        switch step.state {
        case .done:
            Image(systemName: "checkmark.circle.fill")
                .foregroundStyle(Color.green)
                .font(.secondaryText)
        case .actionNeeded:
            Image(systemName: step.isOptional ? "circle.dotted" : "exclamationmark.circle.fill")
                .foregroundStyle(step.isOptional ? Color.secondary : Color.orange)
                .font(.secondaryText)
        case .waiting:
            ProgressView().controlSize(.mini)
        case .switchedOff:
            // A deliberate choice, so neither a tick that claims it works nor a warning
            // that asks to be fixed.
            Image(systemName: "minus.circle")
                .foregroundStyle(.tertiary)
                .font(.secondaryText)
        }
    }

    @ViewBuilder
    private func action(for step: SetupStep) -> some View {
        if step.id == .translationPair, pairWorking {
            ProgressView().controlSize(.mini)
        } else if step.id == .databases, !model.databaseDownloads.isEmpty {
            Button("Stop") { perform(.cancelDatabaseDownload) }
                .buttonStyle(.bordered)
                .controlSize(.small)
        } else if let action = step.action, let label = step.actionLabel {
            Button(label) { perform(action) }
                .buttonStyle(.bordered)
                .controlSize(.small)
        }
    }

    /// Ask launchd to run the login agent now.
    ///
    /// Its KeepAlive only covers a crash, so a backend stopped cleanly stays down until
    /// the next login. `kickstart` restarts a service that is still loaded; one that was
    /// booted out is not there to kick, so that case bootstraps the agent first.
    private func startBackendAgent() {
        let label = "com.translator.desktop"
        let domain = "gui/\(getuid())"
        if launchctl(["kickstart", "-k", "\(domain)/\(label)"]) != 0 {
            let plist = FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Library/LaunchAgents/\(label).plist")
            _ = launchctl(["bootstrap", domain, plist.path])
        }
        Task {
            // It opens three SQLite bases and warms the sidecar before it answers.
            try? await Task.sleep(for: .seconds(8))
            await model.refreshAll()
        }
    }

    @discardableResult
    private func launchctl(_ arguments: [String]) -> Int32 {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        process.arguments = arguments
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
            process.waitUntilExit()
            return process.terminationStatus
        } catch {
            return -1
        }
    }

    private func perform(_ action: SetupAction) {
        switch action {
        case .startBackend:
            startBackendAgent()
        case .grantAccessibility:
            // Raises Apple's own dialog; the click in it is the user's.
            SelectionCapture.requestTrust()
            SelectionCapture.openAccessibilitySettings()
            model.refreshAccessibilityTrust()
        case .openAccessibilitySettings:
            SelectionCapture.openAccessibilitySettings()
        case .recordShortcut:
            onRecordShortcut()
        case .downloadLanguagePair:
            pairMessage = nil
            pairWorking = true
            pairConfiguration = TranslationSession.Configuration(
                source: Locale.Language(identifier: model.settings.languages.source),
                target: Locale.Language(identifier: model.settings.languages.target)
            )
        case .enableLoginItem:
            do {
                try LoginItem.enable()
                // Registering can leave macOS waiting for approval, so the row is
                // re-read rather than assumed to be done.
                Task { await model.refreshAll() }
            } catch {
                model.show(
                    banner: "Could not turn that on: \(error.localizedDescription)",
                    level: .error
                )
            }
        case .openLoginItemsSettings:
            LoginItem.openSettings()
        case .downloadDatabases:
            Task { await model.downloadDatabases() }
        case .cancelDatabaseDownload:
            Task { await model.cancelDatabaseDownload() }
        case .openDictionarySettings:
            NSWorkspace.shared.open(URL(fileURLWithPath: "/System/Applications/Dictionary.app"))
        case .connectAnki:
            Task {
                await model.refreshAnkiStatus()
                await model.loadDecks()
            }
        case .recheck:
            model.refreshAccessibilityTrust()
            Task { await model.refreshAll() }
        }
    }
}
