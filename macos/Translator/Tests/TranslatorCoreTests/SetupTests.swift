import Foundation
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
    dictionaries: [String] = ["Oxford Russian Dictionary", "Apple Dictionary"],
    enabled: SourceSettings = SourceSettings()
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
            dictionaries: dictionaries,
            enabled: enabled
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
        // Its KeepAlive only covers a crash, so a clean stop needs a push, not patience.
        #expect(step(result, .backend).action == .startBackend)
        #expect(step(result, .databases).state == .waiting)
        #expect(step(result, .dictionary).state == .waiting)
        #expect(step(result, .translationPair).state == .waiting)
        // The permission and the shortcut do not depend on the backend.
        #expect(step(result, .accessibility).state == .done)
        #expect(step(result, .shortcut).state == .done)
    }

    /// The backend can fetch the databases now, so the stage is a button rather than an
    /// instruction to go and run a shell script.
    @Test func missingDatabasesOfferTheDownload() {
        let result = plan(ping: readyPing(primary: false))
        let databases = step(result, .databases)
        #expect(databases.state == .actionNeeded)
        #expect(databases.action == .downloadDatabases)
        #expect(databases.detail.contains("primary"))
        #expect(!databases.detail.contains("install_macos"), "no shell commands in the UI")
        // One missing file can be forty megabytes; naming the full set's size here would
        // overstate the cost by forty times.
        #expect(!databases.detail.contains("1.8 GB"))
    }

    /// Only "supported" means Apple will hand the pair over if asked. Offering a download
    /// for any other answer wastes the press and teaches the user the button does nothing.
    @Test func onlyASupportedPairOffersADownload() {
        for status in ["unknown", "unavailable", "something new"] {
            let result = plan(ping: readyPing(translation: false, translationStatus: status))
            let pair = step(result, .translationPair)
            #expect(pair.action == nil, "\(status) must not offer a download")
            #expect(pair.state == .waiting, "\(status)")
        }
        let supported = plan(ping: readyPing(translation: false, translationStatus: "supported"))
        #expect(step(supported, .translationPair).action == .downloadLanguagePair)
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
        #expect(databases.action == .downloadDatabases)
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

    /// With the backend down, the database stage is unknown rather than broken. Naming
    /// both would report two problems where fixing one resolves the other.
    @Test func aSilentBackendIsTheOnlyStepNamed() {
        let result = plan(connected: false, ping: nil)
        #expect(result.blocking.map(\.id) == [.backend, .databases])
        #expect(result.summary == "One step left: Backend")
        #expect(!result.isReady)
    }

    /// A source the user switched off is a decision. Reporting five installed
    /// dictionaries as working would promise an answer that will not arrive; reporting it
    /// as broken would send the user to fix something they chose.
    @Test func aDictionarySwitchedOffIsNeitherDoneNorOutstanding() {
        let result = plan(ping: readyPing(enabled: SourceSettings(appleDictionary: false)))
        let dictionary = step(result, .dictionary)
        #expect(dictionary.state == .switchedOff)
        #expect(dictionary.action == nil)
        #expect(dictionary.detail.contains("Sources"))
        #expect(!result.suggested.contains(where: { $0.id == .dictionary }))
        #expect(result.isReady)
        #expect(result.summary == "Everything is set up.")
    }

    /// Offering a download for a source the user turned off is worse than saying nothing.
    @Test func translationSwitchedOffOffersNoDownload() {
        let result = plan(
            ping: readyPing(
                translation: false,
                translationStatus: "supported",
                enabled: SourceSettings(appleTranslation: false)
            )
        )
        let pair = step(result, .translationPair)
        #expect(pair.state == .switchedOff)
        #expect(pair.action == nil)
        #expect(result.suggested.isEmpty)
    }

    /// Consent is checked before availability, so a switched-off source is not also told
    /// that no dictionary is enabled in system settings.
    @Test func consentIsReportedBeforeAvailability() {
        let result = plan(
            ping: readyPing(
                dictionary: false,
                dictionaries: [],
                enabled: SourceSettings(appleDictionary: false)
            )
        )
        #expect(step(result, .dictionary).state == .switchedOff)
    }
}

@Suite struct SourceSettingsCodingTests {
    /// Settings travel with keys kept verbatim; the ping travels through
    /// `convertFromSnakeCase`. Both must land, or a switched-off source silently reads as
    /// on and setup lies about it.
    @Test func bothKeySpellingsDecode() throws {
        let verbatim = #"{"apple_dictionary": false, "offline_examples": false}"#
        let a = try IPCCoding.plainDecoder.decode(SourceSettings.self, from: Data(verbatim.utf8))
        #expect(a.appleDictionary == false)
        #expect(a.offlineExamples == false)
        #expect(a.google, "a key that is absent stays on")

        let converted = #"{"appleDictionary": false, "offlineExamples": false}"#
        let b = try IPCCoding.decoder.decode(SourceSettings.self, from: Data(converted.utf8))
        #expect(b.appleDictionary == false)
        #expect(b.offlineExamples == false)
    }

    /// The ping is decoded by the snake_case coder, which is where the spellings meet.
    @Test func pingCarriesConsentThroughItsOwnCoder() throws {
        let json = #"""
        {"version": "0.3.0", "protocol": 1, "pid": 1, "platform": "darwin",
         "db": {"primary": true, "fallback": true, "definitions": true, "dir": "/db"},
         "engines": {"apple_dictionary": true, "apple_translation": true,
                     "translation_status": "installed", "dictionaries": ["A"],
                     "enabled": {"apple_dictionary": false, "google": false}}}
        """#
        let ping = try IPCCoding.decoder.decode(PingInfo.self, from: Data(json.utf8))
        #expect(ping.engines.appleDictionary, "the dictionary is installed")
        #expect(!ping.engines.enabled.appleDictionary, "and switched off")
        #expect(!ping.engines.enabled.google)
        #expect(ping.engines.enabled.cambridge, "absent keys stay on")
    }

    /// An older backend sends no consent at all; nothing must read as switched off.
    @Test func aPingWithoutConsentLeavesEverythingOn() throws {
        let json = #"""
        {"version": "0.3.0", "protocol": 1, "pid": 1, "platform": "darwin",
         "db": {"primary": true, "fallback": true, "definitions": true, "dir": "/db"},
         "engines": {"apple_dictionary": true, "apple_translation": true,
                     "translation_status": "installed", "dictionaries": []}}
        """#
        let ping = try IPCCoding.decoder.decode(PingInfo.self, from: Data(json.utf8))
        #expect(ping.engines.enabled == SourceSettings())
    }

    /// Saving must write the keys the backend reads, whatever the decoder did.
    @Test func savingKeepsTheBackendSpelling() throws {
        var settings = BackendSettings()
        settings.sources.cambridge = false
        let data = try IPCCoding.plainEncoder.encode(settings)
        let text = String(decoding: data, as: UTF8.self)
        #expect(text.contains(#""cambridge":false"#))
        #expect(text.contains(#""apple_dictionary":true"#))
    }
}

