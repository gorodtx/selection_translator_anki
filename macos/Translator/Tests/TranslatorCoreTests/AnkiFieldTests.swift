import Foundation
import Testing
@testable import TranslatorCore

/// A field name Anki does not have is invisible in Settings and fails when a card is
/// added — far from the setting that caused it. These cover what may and may not be
/// concluded from the note type's answer.
@Suite struct AnkiFieldCheckTests {
    private let model = ["Word", "Translation", "Example", "Definition", "Image"]

    @Test func namesTheNoteTypeHasAreNotFlagged() {
        #expect(AnkiFieldCheck.issues(configured: ["Word", "Image"], modelFields: model).isEmpty)
    }

    /// The whole point: an empty answer means the question was not settled. A closed Anki
    /// and a note type that does not exist both answer this way, and flagging every name
    /// would paint a correct configuration red.
    @Test func anEmptyModelFlagsNothing() {
        #expect(AnkiFieldCheck.issues(configured: ["word", "nonsense"], modelFields: []).isEmpty)
    }

    /// The common mistake, and the one worth naming outright.
    @Test func aCaseMismatchSuggestsTheRealName() {
        let issues = AnkiFieldCheck.issues(configured: ["word"], modelFields: model)
        #expect(issues.count == 1)
        #expect(issues[0].configured == "word")
        #expect(issues[0].suggestion == "Word")
    }

    @Test func anUnrelatedNameIsFlaggedWithoutASuggestion() {
        let issues = AnkiFieldCheck.issues(configured: ["Meaning"], modelFields: model)
        #expect(issues.map(\.configured) == ["Meaning"])
        #expect(issues[0].suggestion == nil)
    }

    /// The backend drops an empty mapping, which is how a field is left alone. Reporting
    /// it would invent a mistake the user did not make.
    @Test func anEmptyMappingIsNotAMistake() {
        #expect(AnkiFieldCheck.issues(configured: ["", "   "], modelFields: model).isEmpty)
    }

    /// Anki matches exactly and the backend strips, so surrounding space is harmless.
    @Test func surroundingSpaceIsIgnored() {
        #expect(AnkiFieldCheck.issues(configured: ["  Word  "], modelFields: model).isEmpty)
    }

    @Test func theSameWrongNameIsReportedOnce() {
        let issues = AnkiFieldCheck.issues(configured: ["Nope", "Nope"], modelFields: model)
        #expect(issues.count == 1)
    }
}

/// Decoded from what the backend actually sent, copied from a live run: a decoder that
/// has drifted answers with an empty list, which this UI is required to read as "nothing
/// to compare against" — so a silent drift would look exactly like a healthy unknown.
@Suite struct AnkiModelFieldsWireTests {
    @Test func aReachableAnkiDecodesItsFields() throws {
        let json = #"{"fields": ["word", "translation", "example_en", "definitions_en", "image"], "error": null}"#
        let answer = try IPCCoding.decoder.decode(AnkiModelFields.self, from: Data(json.utf8))
        #expect(answer.fields.count == 5)
        #expect(answer.fields.first == "word")
        #expect(answer.error == nil)
        #expect(AnkiFieldCheck.issues(
            configured: ["word", "translation", "example_en", "definitions_en", "image"],
            modelFields: answer.fields
        ).isEmpty, "the shipped defaults match the note type this backend creates")
    }

    @Test func aClosedAnkiDecodesItsReason() throws {
        let json = #"""
        {"fields": [], "error": "AnkiConnect error: Cannot connect to host 127.0.0.1:8765 ssl:default [Connect call failed ('127.0.0.1', 8765)]"}
        """#
        let answer = try IPCCoding.decoder.decode(AnkiModelFields.self, from: Data(json.utf8))
        #expect(answer.fields.isEmpty)
        #expect(answer.error?.contains("Cannot connect") == true)
        // Nothing may be flagged from this, however the names are configured.
        #expect(AnkiFieldCheck.issues(configured: ["Nope"], modelFields: answer.fields).isEmpty)
    }

    /// An unknown note type answers exactly like one with no fields — empty, no error —
    /// so neither may produce a warning.
    @Test func anUnknownNoteTypeIsIndistinguishableAndSilent() throws {
        let json = #"{"fields": [], "error": null}"#
        let answer = try IPCCoding.decoder.decode(AnkiModelFields.self, from: Data(json.utf8))
        #expect(answer.fields.isEmpty)
        #expect(answer.error == nil)
        #expect(AnkiFieldCheck.issues(configured: ["word"], modelFields: answer.fields).isEmpty)
    }
}
