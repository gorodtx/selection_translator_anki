import Foundation
import Testing
@testable import AppleLangHelperCore

@Suite struct ProtocolTests {
    @Test func decodesStringAndNumericIds() throws {
        let a = try decodeRequest(line: #"{"id":"abc","op":"ping"}"#)
        #expect(a.id == "abc")
        #expect(a.op == .ping)
        let b = try decodeRequest(line: #"{"id":42,"op":"define","term":"bank","max_records":3,"include_markup":false}"#)
        #expect(b.id == "42")
        #expect(b.op == .define)
        #expect(b.term == "bank")
        #expect(b.maxRecords == 3)
        #expect(b.includeMarkup == false)
    }

    @Test func rejectsMalformedRequests() {
        #expect(throws: RequestDecodingError.notJSON) { try decodeRequest(line: "not json") }
        #expect(throws: RequestDecodingError.missingId) { try decodeRequest(line: #"{"op":"ping"}"#) }
        #expect(throws: RequestDecodingError.missingOp) { try decodeRequest(line: #"{"id":"1"}"#) }
        #expect(throws: RequestDecodingError.unknownOp("dance")) { try decodeRequest(line: #"{"id":"1","op":"dance"}"#) }
    }

    @Test func encodesRecordsWithNulls() throws {
        let response = Response(
            id: "7",
            result: .records(
                [DefinitionRecord(dictionary: "Oxford", headword: "bank", title: nil, anchor: nil, markup: "<x/>")],
                elapsedMs: 1.5
            )
        )
        let line = try response.jsonLine()
        #expect(!line.contains("\n"))
        let object = try #require(try JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any])
        #expect(object["id"] as? String == "7")
        #expect(object["ok"] as? Bool == true)
        let result = try #require(object["result"] as? [String: Any])
        let records = try #require(result["records"] as? [[String: Any]])
        #expect(records.count == 1)
        #expect(records[0]["headword"] as? String == "bank")
        #expect(records[0]["title"] is NSNull)
        #expect(records[0]["markup"] as? String == "<x/>")
    }

    @Test func encodesErrors() throws {
        let response = Response(id: "9", error: ErrorBody(code: .translationNotInstalled, message: "nope"))
        let object = try #require(try JSONSerialization.jsonObject(with: Data(response.jsonLine().utf8)) as? [String: Any])
        #expect(object["ok"] as? Bool == false)
        let error = try #require(object["error"] as? [String: Any])
        #expect(error["code"] as? String == "translation_not_installed")
        #expect(error["message"] as? String == "nope")
        #expect(object["result"] == nil)
    }
}
