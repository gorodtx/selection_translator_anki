import Foundation
import Testing
@testable import AppleLangHelperCore

struct FakeTranslator: Translating {
    var status: TranslationAvailability = .installed
    var failure: TranslationFailure? = nil

    func availability(source: String, target: String) async -> TranslationAvailability { status }

    func translate(_ text: String, source: String, target: String) async throws -> String {
        if let failure { throw failure }
        return "[\(source)->\(target)] \(text)"
    }
}

@Suite struct DispatcherTests {
    @Test func pingAnswersWithVersion() async {
        let d = Dispatcher(translator: FakeTranslator())
        let r = await d.handle(line: #"{"id":"1","op":"ping"}"#)
        #expect(r.id == "1")
        #expect(r.result == .pong(version: helperVersion))
    }

    @Test func unknownOpKeepsId() async {
        let d = Dispatcher(translator: FakeTranslator())
        let r = await d.handle(line: #"{"id":"x1","op":"dance"}"#)
        #expect(r.id == "x1")
        #expect(r.error?.code == .unknownOp)
    }

    @Test func garbageIsBadRequest() async {
        let d = Dispatcher(translator: FakeTranslator())
        let r = await d.handle(line: "garbage")
        #expect(r.error?.code == .badRequest)
    }

    @Test func defineRequiresTerm() async {
        let d = Dispatcher(translator: FakeTranslator())
        let r = await d.handle(Request(id: "2", op: .define, term: "   "))
        #expect(r.error?.code == .badRequest)
    }

    @Test func translateUsesTranslator() async {
        let d = Dispatcher(translator: FakeTranslator())
        let r = await d.handle(Request(id: "3", op: .translate, text: "hello", source: "en", target: "ru"))
        guard case let .translation(text, source, target, _)? = r.result else {
            Issue.record("expected translation result, got \(String(describing: r.result))")
            return
        }
        #expect(text == "[en->ru] hello")
        #expect(source == "en")
        #expect(target == "ru")
    }

    @Test func translateMapsNotInstalled() async {
        let d = Dispatcher(translator: FakeTranslator(failure: .notInstalled("en", "ru")))
        let r = await d.handle(Request(id: "4", op: .translate, text: "hello"))
        #expect(r.error?.code == .translationNotInstalled)
    }

    @Test func availabilityReportsStatus() async {
        let d = Dispatcher(translator: FakeTranslator(status: .supported))
        let r = await d.handle(Request(id: "5", op: .availability))
        guard case let .availability(a)? = r.result else {
            Issue.record("expected availability result")
            return
        }
        #expect(a.status == "supported")
        #expect(a.source == "en")
        #expect(a.target == "ru")
    }
}
