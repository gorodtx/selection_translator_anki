import Foundation
import Testing
@testable import AppleLangHelperCore

/// Live tests against the user's enabled dictionaries. They run only when an Oxford
/// English-Russian dictionary is active in Dictionary.app, so CI without it stays green.
private let oxford: ActiveDictionary? = selectDictionaries(
    DictionaryLookup().activeDictionaries(), matching: "Oxford Russian"
).first

@Suite struct DictionaryLiveTests {
    @Test(.enabled(if: oxford != nil)) func homographsComeAsSeparateRecords() throws {
        let dictionary = try #require(oxford)
        let records = DictionaryLookup().records(for: "bank", in: dictionary)
        #expect(records.count >= 2)
        #expect(records.allSatisfy { $0.headword == "bank" })
        #expect(records.first?.markup?.contains("d:entry") == true)
    }

    @Test(.enabled(if: oxford != nil)) func phrasalVerbCarriesAnchorIntoParentEntry() throws {
        let dictionary = try #require(oxford)
        let records = DictionaryLookup().records(for: "look up", in: dictionary)
        let first = try #require(records.first)
        #expect(first.headword == "look up")
        #expect(first.title == "look")
        #expect(first.anchor?.contains("xpointer") == true)
    }

    @Test(.enabled(if: oxford != nil)) func inflectedFormResolvesToLemma() throws {
        let dictionary = try #require(oxford)
        let records = DictionaryLookup().records(for: "children", in: dictionary, includeMarkup: false)
        #expect(records.contains { $0.headword == "child" })
        #expect(records.allSatisfy { $0.markup == nil })
    }

    @Test(.enabled(if: oxford != nil)) func missingHeadwordYieldsNoRecords() throws {
        let dictionary = try #require(oxford)
        #expect(DictionaryLookup().records(for: "in spite of", in: dictionary).isEmpty)
        #expect(DictionaryLookup().records(for: "   ", in: dictionary).isEmpty)
    }

    @Test func textDefinitionFallbackDoesNotCrash() {
        // Result depends on the machine's dictionaries; only the call contract is asserted.
        _ = DictionaryLookup().textDefinition(for: "look")
        #expect(DictionaryLookup().textDefinition(for: "") == nil)
    }

    @Test(.enabled(if: oxford != nil)) func dispatcherDefineEndToEnd() async throws {
        let d = Dispatcher(translator: FakeTranslator())
        let r = await d.handle(line: #"{"id":"d1","op":"define","term":"bank","dictionary":"Oxford Russian","max_records":2}"#)
        guard case let .records(records, elapsed)? = r.result else {
            Issue.record("expected records, got \(String(describing: r.error))")
            return
        }
        #expect(records.count == 2)
        #expect(elapsed >= 0)
        let line = try r.jsonLine()
        #expect(line.contains("\"headword\":\"bank\""))
    }
}
