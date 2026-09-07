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
    case loginItem
    case dictionary
    case translationPair
    case anki
}

/// Whether the app opens itself at login. Kept as a value so the plan stays pure: the
/// framework that answers this lives in the app layer.
public enum LoginItemState: Equatable, Sendable {
    case enabled
    /// Registered, but macOS is waiting for the user to allow it in System Settings.
    case requiresApproval
    case notRegistered
    /// A state this build does not know. Nothing a button here can fix, and guessing
    /// would be worse than saying so.
    case unavailable

    /// How a switch should read.
    ///
    /// Waiting for approval counts as on: the app is registered and the user asked for
    /// it, and showing the switch as off would invite them to turn on something that is
    /// already turned on. What is missing is a click in System Settings, which the row
    /// says in words instead.
    public var isOn: Bool {
        switch self {
        case .enabled, .requiresApproval: return true
        case .notRegistered, .unavailable: return false
        }
    }
}

public enum SetupState: Equatable, Sendable {
    /// Nothing left to do.
    case done
    /// The user has to act, and the step says how.
    case actionNeeded
    /// Working on it, or not known yet; no action would help.
    case waiting
    /// The user switched this source off. Not a gap to close and not a fault to report —
    /// so it counts as neither finished nor outstanding, and offers no button.
    case switchedOff
}

/// What the one button on a step does. The view maps these to handlers; keeping them as
/// values means the plan stays testable and the view stays dumb.
public enum SetupAction: Equatable, Sendable {
    case startBackend
    case grantAccessibility
    case openAccessibilitySettings
    case recordShortcut
    case enableLoginItem
    case openLoginItemsSettings
    case downloadLanguagePair
    case downloadDatabases
    case cancelDatabaseDownload
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
        steps.filter { !$0.isOptional && $0.state != .done && $0.state != .switchedOff }
    }

    /// Optional steps still worth doing. A source the user switched off is a decision,
    /// not a suggestion, so it is not counted here.
    public var suggested: [SetupStep] {
        steps.filter { $0.isOptional && $0.state != .done && $0.state != .switchedOff }
    }

    public var isReady: Bool { blocking.isEmpty }

    /// One line for the top of the section, so the state is legible without reading rows.
    public var summary: String {
        // Everything the backend reports is unknown until it answers, not wrong. Listing
        // those stages alongside it tells the user they have several problems when they
        // have one, and the rest resolve themselves the moment it starts.
        if let backend = steps.first(where: { $0.id == .backend }), backend.state != .done {
            return "One step left: \(backend.title)"
        }
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
        loginItem: LoginItemState,
        anki: AnkiStatus
    ) -> SetupPlan {
        var steps: [SetupStep] = []

        steps.append(backendStep(connected: connected, ping: ping))
        steps.append(databaseStep(ping: ping, connected: connected))
        steps.append(accessibilityStep(trusted: accessibilityTrusted))
        steps.append(shortcutStep(registered: shortcutRegistered, shortcut: shortcut))
        steps.append(loginItemStep(state: loginItem))
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
                detail: "Runs at login, listed in Login Items as Translator; it holds the dictionaries open.",
                state: .done,
                isOptional: false
            )
        }
        // The login agent is set to restart only after a crash, so a clean stop — a
        // manual one, or a test — leaves it down until the next login. Offer to start it
        // rather than telling the user to wait for something that will not happen.
        return SetupStep(
            id: .backend,
            title: "Backend",
            detail: connected
                ? "Connected, waiting for its first answer."
                : "Not running. It starts at login; start it now if it stopped.",
            state: .waiting,
            isOptional: false,
            action: connected ? .recheck : .startBackend,
            actionLabel: connected ? "Re-check" : "Start"
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
        // The backend fetches them, verifies each against the lock file and only then
        // moves it into place, so this is a button rather than an instruction to go and
        // run a shell script.
        return SetupStep(
            id: .databases,
            title: "Offline databases",
            // The size comes from the backend, which sums only the missing files: the
            // full set is about 1.8 GB but one absent file can be forty megabytes, and
            // overstating the cost by forty times is worse than saying nothing. A nil
            // means the backend cannot read its lock, so no number is claimed — never a
            // zero, which would read as "nothing to fetch" beside a list of what is
            // missing.
            detail: pendingSize(db.pendingBytes).map {
                "Missing: \(missing.joined(separator: ", ")). \($0) to download."
            } ?? "Missing: \(missing.joined(separator: ", ")).",
            state: .actionNeeded,
            isOptional: false,
            action: .downloadDatabases,
            actionLabel: "Download…"
        )
    }

    /// A size worth showing, or nothing. Both an unreadable lock and a zero leave the
    /// stage silent about cost rather than guessing at it.
    private static func pendingSize(_ bytes: Int?) -> String? {
        guard let bytes, bytes > 0 else { return nil }
        return ByteCountFormatter.string(fromByteCount: Int64(bytes), countStyle: .file)
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

    /// The backend's own agent covers only the backend. Without this the app is gone
    /// after a restart while the daemon still answers — which is why the gap read as a
    /// working install.
    private static func loginItemStep(state: LoginItemState) -> SetupStep {
        switch state {
        case .enabled:
            return SetupStep(
                id: .loginItem,
                title: "Open at login",
                detail: "The app is there after a restart, so the shortcut works straight away.",
                state: .done,
                isOptional: true
            )
        case .requiresApproval:
            // Registered already; the remaining click is one only the user can make.
            return SetupStep(
                id: .loginItem,
                title: "Open at login",
                detail: "Waiting for your approval in System Settings > General > Login Items.",
                state: .actionNeeded,
                isOptional: true,
                action: .openLoginItemsSettings,
                actionLabel: "Open…"
            )
        case .notRegistered:
            return SetupStep(
                id: .loginItem,
                title: "Open at login",
                detail: "Off. The shortcut only works once the app is open, so it has to be started by hand after a restart.",
                state: .actionNeeded,
                isOptional: true,
                action: .enableLoginItem,
                actionLabel: "Turn on"
            )
        case .unavailable:
            return SetupStep(
                id: .loginItem,
                title: "Open at login",
                detail: "The system reported a state this version does not understand.",
                state: .waiting,
                isOptional: true
            )
        }
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
        // Availability says the Mac has dictionaries; consent says the user wants them
        // consulted. Claiming five dictionaries while the source is off promises an answer
        // that will not arrive.
        if !engines.enabled.appleDictionary {
            return SetupStep(
                id: .dictionary,
                title: "Apple Dictionary",
                detail: "Switched off in Sources below.",
                state: .switchedOff,
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
        if !engines.enabled.appleTranslation {
            return SetupStep(
                id: .translationPair,
                title: "Offline translation",
                detail: "Switched off in Sources below. Phrases go over the network.",
                state: .switchedOff,
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
        // Only "supported" means Apple will hand over the pair if asked. Every other
        // answer — not offered here, the engine not reachable, no probe yet — is not
        // something a Download button can fix, and offering one would waste the press.
        switch engines.translationStatus {
        case "supported":
            return SetupStep(
                id: .translationPair,
                title: "Offline translation",
                detail: "Language pair not downloaded. Phrases go over the network until it is.",
                state: .actionNeeded,
                isOptional: true,
                action: .downloadLanguagePair,
                actionLabel: "Download…"
            )
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
                detail: "The translation engine is not answering. Phrases go over the network.",
                state: .waiting,
                isOptional: true
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
