import Testing
@testable import TranslatorCore

/// The setup plan decides what a fresh install still has to do, so these cover the states
/// a user actually lands in: nothing running, permission missing, a shortcut another app
/// owns, no language pair, no Anki.
private func plan(
    connected: Bool = true,
    ping: PingInfo? = readyPing(),
    trusted: Bool = true,
    shortcutRegistered: Bool = true,
    shortcut: String = "⌥⌘T",
    anki: AnkiStatus = readyAnki()
) -> SetupPlan {
    SetupPlanner.plan(
        connected: connected,
        ping: ping,
        accessibilityTrusted: trusted,
        shortcutRegistered: shortcutRegistered,
        shortcut: shortcut,
        anki: anki
    )
}

private func readyPing(
    primary: Bool = true,
    fallback: Bool = true,
    definitions: Bool = true,
    dictionary: Bool = true,
    translation: Bool = true,
    translationStatus: String = "installed",
    dictionaries: [String] = ["Oxford Russian Dictionary", "Apple Dictionary"]
) -> PingInfo {
    PingInfo(
        version: "0.3.0",
        pid: 1,
        platform: "darwin",
        db: PingInfo.Database(
            primary: primary, fallback: fallback, definitions: definitions,
            dir: "/db"
        ),
        engines: PingInfo.Engines(
            appleDictionary: dictionary,
            appleTranslation: translation,
            translationStatus: translationStatus,
            dictionaries: dictionaries
        )
    )
}

private func readyAnki() -> AnkiStatus {
    AnkiStatus(modelStatus: "Model ready", deckStatus: "Selected", deckName: "Vocabulary", available: true)
}

private func step(_ plan: SetupPlan, _ id: SetupStepID) -> SetupStep {
    guard let found = plan.steps.first(where: { $0.id == id }) else {
        Issue.record("no step \(id)")
        return SetupStep(id: id, title: "", detail: "", state: .waiting, isOptional: true)
    }
    return found
}

@Suite struct SetupPlanTests {
    @Test func everyStepIsPresentAndOrdered() {
        #expect(plan().steps.map(\.id) == SetupStepID.allCases)
    }

    @Test func aFullySetUpMacHasNothingLeft() {
        let result = plan()
        #expect(result.isReady)
        #expect(result.blocking.isEmpty)
        #expect(result.suggested.isEmpty)
        #expect(result.summary == "Everything is set up.")
    }

    /// The first thing a fresh install sees: no backend yet, so nothing else is known.
    @Test func withoutABackendNothingIsClaimedAsWorking() {
        let result = plan(connected: false, ping: nil)
        #expect(!result.isReady)
        #expect(step(result, .backend).state == .waiting)
        #expect(step(result, .databases).state == .waiting)
        #expect(step(result, .dictionary).state == .waiting)
        #expect(step(result, .translationPair).state == .waiting)
        // The permission and the shortcut do not depend on the backend.
        #expect(step(result, .accessibility).state == .done)
        #expect(step(result, .shortcut).state == .done)
    }

    @Test func missingDatabasesBlockAndNameThemselves() {
        let result = plan(ping: readyPing(primary: false, definitions: false))
        let databases = step(result, .databases)
        #expect(databases.state == .actionNeeded)
        #expect(!databases.isOptional)
        #expect(databases.detail.contains("primary"))
        #expect(databases.detail.contains("definitions"))
        #expect(!databases.detail.contains("fallback"))
        #expect(!result.isReady)
    }

    @Test func missingPermissionBlocksAndOffersTheGrant() {
        let result = plan(trusted: false)
        let accessibility = step(result, .accessibility)
        #expect(accessibility.state == .actionNeeded)
        #expect(accessibility.action == .grantAccessibility)
        // Without it the shortcut is dead but Services is not, and the row says so.
        #expect(accessibility.detail.contains("Services"))
        #expect(result.blocking.map(\.id) == [.accessibility])
    }

    @Test func aTakenShortcutBlocksAndOffersToChangeIt() {
        let result = plan(shortcutRegistered: false, shortcut: "⌥⌘T")
        let shortcut = step(result, .shortcut)
        #expect(shortcut.state == .actionNeeded)
        #expect(shortcut.action == .recordShortcut)
        #expect(shortcut.detail.contains("⌥⌘T"))
        #expect(!result.isReady)
    }

    /// A missing language pair is a real gap, but the network covers it, so it must not
    /// read as "the app is broken".
    @Test func aMissingLanguagePairIsOptionalAndDownloadable() {
        let result = plan(ping: readyPing(translation: false, translationStatus: "supported"))
        let pair = step(result, .translationPair)
        #expect(pair.state == .actionNeeded)
        #expect(pair.isOptional)
        #expect(pair.action == .downloadLanguagePair)
        #expect(result.isReady)
        #expect(result.summary.hasPrefix("Ready. One optional step left"))
    }

    /// A pair the Mac does not offer is not something a button can fix.
    @Test func anUnsupportedPairOffersNoAction() {
        let result = plan(ping: readyPing(translation: false, translationStatus: "unsupported"))
        let pair = step(result, .translationPair)
        #expect(pair.state == .waiting)
        #expect(pair.action == nil)
        #expect(result.isReady)
    }

    @Test func noDictionaryPointsAtDictionarySettings() {
        let result = plan(ping: readyPing(dictionary: false, dictionaries: []))
        let dictionary = step(result, .dictionary)
        #expect(dictionary.state == .actionNeeded)
        #expect(dictionary.isOptional)
        #expect(dictionary.action == .openDictionarySettings)
    }

    @Test func manyDictionariesAreSummarisedNotListed() {
        let result = plan(ping: readyPing(dictionaries: ["A", "B", "C", "D"]))
        #expect(step(result, .dictionary).detail == "A, B and 2 more.")
    }

    @Test func ankiIsOptionalAndSaysWhatIsLeft() {
        let unreachable = plan(anki: AnkiStatus())
        #expect(step(unreachable, .anki).state == .actionNeeded)
        #expect(step(unreachable, .anki).isOptional)
        #expect(unreachable.isReady)

        let halfSetUp = plan(
            anki: AnkiStatus(modelStatus: "Model not found", deckStatus: "Not selected", deckName: "", available: true)
        )
        let step = step(halfSetUp, .anki)
        #expect(step.detail.contains("model"))
        #expect(step.detail.contains("deck"))
    }

    @Test func blockingStepsAreNamedInTheSummary() {
        let result = plan(trusted: false, shortcutRegistered: false)
        #expect(result.blocking.count == 2)
        #expect(result.summary.hasPrefix("2 steps left:"))
        #expect(result.summary.contains("Accessibility"))
        #expect(result.summary.contains("Shortcut"))
    }

    @Test func oneBlockingStepReadsAsSingular() {
        #expect(plan(trusted: false).summary == "One step left: Accessibility")
    }
}
