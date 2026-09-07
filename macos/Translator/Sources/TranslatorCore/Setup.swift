import Foundation

/// The stages a fresh install has to pass before the app does what it promises.
///
/// Getting this app working means granting a permission, downloading a language model and
/// pointing it at Anki — none of which the app can do for the user, and all of which used
/// to be invisible until something silently failed. So the stages are stated in Settings
/// with what each one is for, whether it is done, and the one button that advances it.
///
/// The decision lives here rather than in the view because it is the part worth testing:
/// which stage is blocking, what counts as optional, and whether the app is usable yet.
public enum SetupStepID: String, Sendable, CaseIterable {
    case backend
    case databases
    case accessibility
    case shortcut
    case dictionary
    case translationPair
    case anki
}

public enum SetupState: Equatable, Sendable {
    /// Nothing left to do.
    case done
    /// The user has to act, and the step says how.
    case actionNeeded
    /// Working on it, or not known yet; no action would help.
    case waiting
}

/// What the one button on a step does. The view maps these to handlers; keeping them as
/// values means the plan stays testable and the view stays dumb.
public enum SetupAction: Equatable, Sendable {
    case grantAccessibility
    case openAccessibilitySettings
    case recordShortcut
    case downloadLanguagePair
    case openDictionarySettings
    case connectAnki
    case recheck
}

public struct SetupStep: Equatable, Sendable, Identifiable {
    public let id: SetupStepID
    public let title: String
    /// One line: what this is for, or what is wrong.
    public let detail: String
    public let state: SetupState
    /// Optional steps make the app better; they do not block using it.
    public let isOptional: Bool
    public let action: SetupAction?
    public let actionLabel: String?

    public init(
        id: SetupStepID,
        title: String,
        detail: String,
        state: SetupState,
        isOptional: Bool,
        action: SetupAction? = nil,
        actionLabel: String? = nil
    ) {
        self.id = id
        self.title = title
        self.detail = detail
        self.state = state
        self.isOptional = isOptional
        self.action = action
        self.actionLabel = actionLabel
    }
}

public struct SetupPlan: Equatable, Sendable {
    public let steps: [SetupStep]

    public init(steps: [SetupStep]) {
        self.steps = steps
    }

    /// Steps that block the app from doing its job.
    public var blocking: [SetupStep] {
        steps.filter { !$0.isOptional && $0.state != .done }
    }

    /// Optional steps still worth doing.
    public var suggested: [SetupStep] {
        steps.filter { $0.isOptional && $0.state != .done }
    }

    public var isReady: Bool { blocking.isEmpty }

    /// One line for the top of the section, so the state is legible without reading rows.
    public var summary: String {
        if !blocking.isEmpty {
            let names = blocking.map(\.title).joined(separator: ", ")
            return blocking.count == 1
                ? "One step left: \(names)"
                : "\(blocking.count) steps left: \(names)"
        }
        if suggested.isEmpty { return "Everything is set up." }
        return suggested.count == 1
            ? "Ready. One optional step left: \(suggested[0].title)"
            : "Ready. \(suggested.count) optional steps left."
    }
}

public enum SetupPlanner {
    /// Build the plan from what the shell already knows. Pure, so the tests can drive
    /// every combination without a backend, a permission or a network.
    public static func plan(
        connected: Bool,
        ping: PingInfo?,
        accessibilityTrusted: Bool,
        shortcutRegistered: Bool,
        shortcut: String,
        anki: AnkiStatus
    ) -> SetupPlan {
        var steps: [SetupStep] = []

        steps.append(backendStep(connected: connected, ping: ping))
        steps.append(databaseStep(ping: ping, connected: connected))
        steps.append(accessibilityStep(trusted: accessibilityTrusted))
        steps.append(shortcutStep(registered: shortcutRegistered, shortcut: shortcut))
        steps.append(dictionaryStep(ping: ping, connected: connected))
        steps.append(translationStep(ping: ping, connected: connected))
        steps.append(ankiStep(anki: anki))

        return SetupPlan(steps: steps)
    }

    // MARK: - Steps

    private static func backendStep(connected: Bool, ping: PingInfo?) -> SetupStep {
        if connected, ping != nil {
            return SetupStep(
                id: .backend,
                title: "Backend",
                detail: "Running as a login agent; it holds the dictionaries open.",
                state: .done,
                isOptional: false
            )
        }
        return SetupStep(
            id: .backend,
            title: "Backend",
            detail: connected
                ? "Connected, waiting for its first answer."
                : "Not reachable yet. It starts at login and takes a few seconds.",
            state: .waiting,
            isOptional: false,
            action: .recheck,
            actionLabel: "Re-check"
        )
    }

    private static func databaseStep(ping: PingInfo?, connected: Bool) -> SetupStep {
        guard let db = ping?.db, connected else {
            return SetupStep(
                id: .databases,
                title: "Offline databases",
                detail: "Unknown until the backend answers.",
                state: .waiting,
                isOptional: false
            )
        }
        let missing = [
            ("primary", db.primary), ("fallback", db.fallback), ("definitions", db.definitions),
        ].filter { !$0.1 }.map(\.0)
        if missing.isEmpty {
            return SetupStep(
                id: .databases,
                title: "Offline databases",
                detail: "All three present in \(db.dir).",
                state: .done,
                isOptional: false
            )
        }
        // The app cannot fetch 1.8 GB itself; the installer verifies checksums and does.
        return SetupStep(
            id: .databases,
            title: "Offline databases",
            detail: "Missing: \(missing.joined(separator: ", ")). Run scripts/install_macos.sh to fetch them.",
            state: .actionNeeded,
            isOptional: false,
            action: .recheck,
            actionLabel: "Re-check"
        )
    }

    private static func accessibilityStep(trusted: Bool) -> SetupStep {
        if trusted {
            return SetupStep(
                id: .accessibility,
                title: "Accessibility",
                detail: "Granted — the shortcut can read the selection in any app.",
                state: .done,
                isOptional: false
            )
        }
        // Without it neither reading the selection nor the synthesized copy works, so the
        // shortcut is dead; the Services menu still is not, and the detail says so.
        return SetupStep(
            id: .accessibility,
            title: "Accessibility",
            detail: "Needed for the shortcut. Until then, use Services on any selected text.",
            state: .actionNeeded,
            isOptional: false,
            action: .grantAccessibility,
            actionLabel: "Grant…"
        )
    }

    private static func shortcutStep(registered: Bool, shortcut: String) -> SetupStep {
        if registered {
            return SetupStep(
                id: .shortcut,
                title: "Shortcut",
                detail: "\(shortcut) translates the current selection.",
                state: .done,
                isOptional: false
            )
        }
        return SetupStep(
            id: .shortcut,
            title: "Shortcut",
            detail: "\(shortcut) is taken by another app. Pick a different one.",
            state: .actionNeeded,
            isOptional: false,
            action: .recordShortcut,
            actionLabel: "Change…"
        )
    }

    private static func dictionaryStep(ping: PingInfo?, connected: Bool) -> SetupStep {
        guard let engines = ping?.engines, connected else {
            return SetupStep(
                id: .dictionary,
                title: "Apple Dictionary",
                detail: "Unknown until the backend answers.",
                state: .waiting,
                isOptional: true
            )
        }
        if engines.appleDictionary {
            let names = engines.dictionaries.prefix(2).joined(separator: ", ")
            return SetupStep(
                id: .dictionary,
                title: "Apple Dictionary",
                detail: engines.dictionaries.count > 2
                    ? "\(names) and \(engines.dictionaries.count - 2) more."
                    : (names.isEmpty ? "Active." : "\(names)."),
                state: .done,
                isOptional: true
            )
        }
        return SetupStep(
            id: .dictionary,
            title: "Apple Dictionary",
            detail: "No dictionary is enabled. Turn on a Russian one in Dictionary settings.",
            state: .actionNeeded,
            isOptional: true,
            action: .openDictionarySettings,
            actionLabel: "Open Dictionary…"
        )
    }

    private static func translationStep(ping: PingInfo?, connected: Bool) -> SetupStep {
        guard let engines = ping?.engines, connected else {
            return SetupStep(
                id: .translationPair,
                title: "Offline translation",
                detail: "Unknown until the backend answers.",
                state: .waiting,
                isOptional: true
            )
        }
        if engines.appleTranslation {
            return SetupStep(
                id: .translationPair,
                title: "Offline translation",
                detail: "Language pair installed — phrases answer without the network.",
                state: .done,
                isOptional: true
            )
        }
        switch engines.translationStatus {
        case "unsupported":
            return SetupStep(
                id: .translationPair,
                title: "Offline translation",
                detail: "This language pair is not offered on this Mac. Phrases go over the network.",
                state: .waiting,
                isOptional: true
            )
        default:
            return SetupStep(
                id: .translationPair,
                title: "Offline translation",
                detail: "Language pair not downloaded. Phrases go over the network until it is.",
                state: .actionNeeded,
                isOptional: true,
                action: .downloadLanguagePair,
                actionLabel: "Download…"
            )
        }
    }

    private static func ankiStep(anki: AnkiStatus) -> SetupStep {
        guard anki.available else {
            return SetupStep(
                id: .anki,
                title: "Anki",
                detail: "Not reachable. Start Anki with the AnkiConnect add-on to add cards.",
                state: .actionNeeded,
                isOptional: true,
                action: .connectAnki,
                actionLabel: "Re-check"
            )
        }
        let hasModel = anki.modelStatus.localizedCaseInsensitiveContains("ready")
        let hasDeck = !anki.deckName.isEmpty
        if hasModel, hasDeck {
            return SetupStep(
                id: .anki,
                title: "Anki",
                detail: "Cards go to \(anki.deckName).",
                state: .done,
                isOptional: true
            )
        }
        var missing: [String] = []
        if !hasModel { missing.append("model") }
        if !hasDeck { missing.append("deck") }
        return SetupStep(
            id: .anki,
            title: "Anki",
            detail: "Connected. Still to choose: \(missing.joined(separator: " and ")).",
            state: .actionNeeded,
            isOptional: true,
            action: .connectAnki,
            actionLabel: "Set up…"
        )
    }
}
