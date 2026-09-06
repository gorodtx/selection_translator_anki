import Foundation
import Testing
@testable import TranslatorCore

@Suite struct FramingTests {
    @Test func splitsLinesAndKeepsPartialTail() {
        var framer = LineFramer()
        #expect(framer.append(Data("{\"a\":1}\n{\"b\"".utf8)).count == 1)
        #expect(framer.pendingBytes == 4)
        let rest = framer.append(Data(":2}\n".utf8))
        #expect(rest.count == 1)
        #expect(String(decoding: rest[0], as: UTF8.self) == "{\"b\":2}")
        #expect(framer.pendingBytes == 0)
    }

    @Test func stripsCarriageReturns() {
        var framer = LineFramer()
        let lines = framer.append(Data("one\r\ntwo\n".utf8))
        #expect(lines.map { String(decoding: $0, as: UTF8.self) } == ["one", "two"])
    }

    @Test func dropsUnboundedPartialLine() {
        var framer = LineFramer()
        let huge = Data(repeating: 0x41, count: LineFramer.maxLineBytes + 16)
        #expect(framer.append(huge).isEmpty)
        #expect(framer.pendingBytes == 0)
    }

    @Test func parsesSuccessResponse() throws {
        let line = Data(#"{"id":"7","ok":true,"result":{"text":"hi"}}"#.utf8)
        guard case let .response(response) = try IPCFraming.parse(line: line) else {
            Issue.record("expected a response")
            return
        }
        #expect(response.id == "7")
        #expect(response.ok)
        let payload = try IPCCoding.decoder.decode(CopyAllResponse.self, from: #require(response.result))
        #expect(payload.text == "hi")
    }

    @Test func parsesNumericIdAndError() throws {
        let line = Data(#"{"id":9,"ok":false,"error":{"code":"anki_error","message":"nope"}}"#.utf8)
        guard case let .response(response) = try IPCFraming.parse(line: line) else {
            Issue.record("expected a response")
            return
        }
        #expect(response.id == "9")
        #expect(!response.ok)
        #expect(response.error == IPCError(code: "anki_error", message: "nope"))
    }

    @Test func failedResponseWithoutErrorStillCarriesOne() throws {
        let line = Data(#"{"id":1,"ok":false}"#.utf8)
        guard case let .response(response) = try IPCFraming.parse(line: line) else {
            Issue.record("expected a response")
            return
        }
        #expect(response.error?.code == "internal")
    }

    @Test func parsesEvent() throws {
        let line = Data(#"{"event":"notification","payload":{"message":"Saved","level":"success"}}"#.utf8)
        guard case let .event(event) = try IPCFraming.parse(line: line) else {
            Issue.record("expected an event")
            return
        }
        #expect(event.name == IPCEventName.notification)
        let payload = try event.decode(NotificationEvent.self)
        #expect(payload.message == "Saved")
        #expect(payload.level == .success)
    }

    @Test func rejectsGarbage() {
        #expect(throws: IPCFramingError.notJSON) { try IPCFraming.parse(line: Data("nonsense".utf8)) }
        #expect(throws: IPCFramingError.notAnObject) { try IPCFraming.parse(line: Data("[1,2]".utf8)) }
        #expect(throws: IPCFramingError.missingId) { try IPCFraming.parse(line: Data("{\"ok\":true}".utf8)) }
    }

    @Test func encodesRequestWithTrailingNewline() throws {
        let frame = try IPCFraming.request(id: 3, method: IPCMethod.translate, params: ["text": "hello"])
        #expect(frame.last == 0x0A)
        let object = try #require(
            try JSONSerialization.jsonObject(with: frame.dropLast()) as? [String: Any]
        )
        #expect(object["id"] as? Int == 3)
        #expect(object["method"] as? String == "translate")
        #expect((object["params"] as? [String: Any])?["text"] as? String == "hello")
    }
}

@Suite struct ViewStateDecodingTests {
    @Test func decodesFullPayload() throws {
        let json = """
        {"original":"bank","original_raw":" bank ","translation":"берег; банк",
         "definitions_items":["a financial institution"],"examples":[{"en":"river bank"}],
         "can_refresh_examples":true,"refreshing_examples":false,"loading":false,
         "can_add_anki":true,"entry_id":12}
        """
        let state = try IPCCoding.decoder.decode(ViewState.self, from: Data(json.utf8))
        #expect(state.original == "bank")
        #expect(state.originalRaw == " bank ")
        #expect(state.translation == "берег; банк")
        #expect(state.definitionsItems == ["a financial institution"])
        #expect(state.examples == [ExampleItem(en: "river bank")])
        #expect(state.canRefreshExamples)
        #expect(state.canAddAnki)
        #expect(state.entryId == 12)
        #expect(state.apple == nil)
        #expect(state.hasTranslation)
    }

    @Test func toleratesMissingFields() throws {
        let state = try IPCCoding.decoder.decode(ViewState.self, from: Data("{}".utf8))
        #expect(state.isEmpty)
        #expect(state.examples.isEmpty)
        #expect(state.entryId == nil)
        #expect(!state.loading)
    }

    @Test func decodesOptionalAppleBlockGrouped() throws {
        let json = """
        {"original":"look up","translation":"навестить",
         "apple":{"headword":"look up","ipa_uk":"lʊk","ipa_us":"lʊk",
           "entries":[{"pos":"transitive verb","senses":[
             {"index":1,"label":"visit","translation":"навещать","examples":[{"en":"look up a friend","ru":"навестить друга"}]}]}]}}
        """
        let state = try IPCCoding.decoder.decode(ViewState.self, from: Data(json.utf8))
        let apple = try #require(state.apple)
        #expect(apple.hasContent)
        #expect(apple.groupedEntries.count == 1)
        #expect(apple.groupedEntries[0].pos == "transitive verb")
        let sense = apple.groupedEntries[0].senses[0]
        #expect(sense.index == 1)
        #expect(sense.label == "visit")
        #expect(sense.examples[0].ru == "навестить друга")
    }

    @Test func decodesOptionalAppleBlockFlat() throws {
        let json = """
        {"apple":{"headword":"bank","pos":"noun","senses":[{"index":1,"translation":"берег"}]}}
        """
        let state = try IPCCoding.decoder.decode(ViewState.self, from: Data(json.utf8))
        let apple = try #require(state.apple)
        #expect(apple.groupedEntries.count == 1)
        #expect(apple.groupedEntries[0].pos == "noun")
        #expect(apple.groupedEntries[0].senses[0].translation == "берег")
    }
}

@Suite struct AnkiPayloadTests {
    @Test func decodesPreviewWithStringAndListFields() throws {
        let json = """
        {"preview":{"values":{"translations":["берег"],"definitions_en":["riverside"],
          "examples_en":["river bank"],"image_path":null},
          "matches":[{"note_id":5,"word":"bank","translation":"берег","definitions_en":"riverside",
                      "examples_en":["a","b"],"image":null}],
          "available_fields":["Word","Translation"]}}
        """
        let response = try IPCCoding.decoder.decode(UpsertPreviewResponse.self, from: Data(json.utf8))
        #expect(response.preview.values.translations == ["берег"])
        #expect(response.preview.values.imagePath == nil)
        #expect(response.preview.matches[0].noteId == 5)
        #expect(response.preview.matches[0].definitionsEn == "riverside")
        #expect(response.preview.matches[0].examplesEn == "a; b")
        #expect(response.preview.availableFields.count == 2)
    }

    @Test func decisionEncodesSnakeCaseWithExplicitNullImage() throws {
        let decision = UpsertDecision(
            createNew: false,
            targetNoteIds: [1, 2],
            translationAction: .replaceWithSelected,
            definitionsAction: .keepExisting,
            examplesAction: .mergeUniqueSelected,
            imageAction: .keepExisting,
            selectedTranslations: ["берег"],
            selectedDefinitionsEn: [],
            selectedExamplesEn: ["river bank"],
            imagePath: nil
        )
        let object = try decision.jsonObject()
        #expect(object["create_new"] as? Bool == false)
        #expect(object["target_note_ids"] as? [Int] == [1, 2])
        #expect(object["translation_action"] as? String == "replace_with_selected")
        #expect(object["definitions_action"] as? String == "keep_existing")
        #expect(object["examples_action"] as? String == "merge_unique_selected")
        #expect(object["image_action"] as? String == "keep_existing")
        #expect(object["selected_examples_en"] as? [String] == ["river bank"])
        #expect(object["image_path"] is NSNull)
    }

    @Test func outcomeClassifiesSuccess() throws {
        let updated = try IPCCoding.decoder.decode(
            UpsertOutcome.self, from: Data(#"{"outcome":"updated","message":"1 note updated"}"#.utf8)
        )
        #expect(updated.isSuccess)
        let duplicate = try IPCCoding.decoder.decode(
            UpsertOutcome.self, from: Data(#"{"outcome":"duplicate","message":"already there"}"#.utf8)
        )
        #expect(!duplicate.isSuccess)
    }
}

@Suite struct SettingsTests {
    @Test func roundTripsAndPreservesUnknownKeys() throws {
        let json = """
        {"languages":{"source":"en","target":"ru"},
         "anki":{"deck":"Default","model":"Basic",
           "fields":{"word":"Word","translation":"Translation","example_en":"Example",
                     "definitions_en":"definitions_en","image":"image"}},
         "future_flag":true,"nested":{"a":[1,2,3]}}
        """
        var settings = try BackendSettings.decode(from: Data(json.utf8))
        #expect(settings.languages.target == "ru")
        #expect(settings.anki.fields.exampleEn == "Example")
        #expect(settings.extra["future_flag"] == .bool(true))

        settings.anki.deck = "Vocabulary"
        let object = try settings.jsonObject()
        #expect((object["anki"] as? [String: Any])?["deck"] as? String == "Vocabulary")
        #expect(object["future_flag"] as? Bool == true)
        #expect(object["nested"] != nil)
        let fields = try #require((object["anki"] as? [String: Any])?["fields"] as? [String: Any])
        #expect(fields["example_en"] as? String == "Example")
    }

    @Test func fallsBackToDefaultsWhenEmpty() throws {
        let settings = try BackendSettings.decode(from: Data("{}".utf8))
        #expect(settings.languages.source == "en")
        #expect(settings.languages.target == "ru")
        #expect(settings.anki.deck.isEmpty)
    }
}

@Suite struct PingTests {
    @Test func decodesPingWithProtocolKey() throws {
        let json = """
        {"version":"0.3.0","protocol":1,"pid":42,"platform":"darwin",
         "db":{"primary":true,"fallback":false,"definitions":true,"dir":"/tmp/db"},
         "engines":{"apple_dictionary":true,"apple_translation":false}}
        """
        let ping = try IPCCoding.decoder.decode(PingInfo.self, from: Data(json.utf8))
        #expect(ping.version == "0.3.0")
        #expect(ping.protocolVersion == 1)
        #expect(ping.pid == 42)
        #expect(ping.db.primary)
        #expect(!ping.db.fallback)
        #expect(ping.db.dir == "/tmp/db")
        #expect(ping.engines.appleDictionary)
        #expect(!ping.engines.appleTranslation)
    }
}
