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
                await model.refreshPing()
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
                Text(step.detail)
                    .font(.captionText)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 8)
            action(for: step)
        }
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
        }
    }

    @ViewBuilder
    private func action(for step: SetupStep) -> some View {
        if step.id == .translationPair, pairWorking {
            ProgressView().controlSize(.mini)
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
