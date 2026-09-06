import Foundation

public let helperVersion = "0.1.0"

/// Pure request handler: no I/O besides the system frameworks it wraps, so it is unit-testable.
public struct Dispatcher: Sendable {
    public var dictionaries: DictionaryLookup
    public var translator: any Translating

    public init(dictionaries: DictionaryLookup = DictionaryLookup(), translator: any Translating = SystemTranslator()) {
        self.dictionaries = dictionaries
        self.translator = translator
    }

    public func handle(line: String) async -> Response {
        let request: Request
        do {
            request = try decodeRequest(line: line)
        } catch let error as RequestDecodingError {
            let id = Self.recoverId(from: line)
            switch error {
            case let .unknownOp(op):
                return Response(id: id, error: ErrorBody(code: .unknownOp, message: "unknown op: \(op)"))
            default:
                return Response(id: id, error: ErrorBody(code: .badRequest, message: "\(error)"))
            }
        } catch {
            return Response(id: "", error: ErrorBody(code: .badRequest, message: "\(error)"))
        }
        return await handle(request)
    }

    public func handle(_ request: Request) async -> Response {
        switch request.op {
        case .ping:
            return Response(id: request.id, result: .pong(version: helperVersion))
        case .shutdown:
            return Response(id: request.id, result: .shuttingDown)
        case .dictionaries:
            return Response(id: request.id, result: .dictionaries(dictionaries.activeDictionaries().map(\.info)))
        case .availability:
            let source = request.source ?? "en"
            let target = request.target ?? "ru"
            let status = await translator.availability(source: source, target: target)
            return Response(
                id: request.id,
                result: .availability(
                    AvailabilityResult(
                        source: source,
                        target: target,
                        status: status.rawValue,
                        dictionaries: dictionaries.activeDictionaries().map(\.info)
                    )
                )
            )
        case .define:
            guard let term = request.term, !term.trimmingCharacters(in: .whitespaces).isEmpty else {
                return Response(id: request.id, error: ErrorBody(code: .badRequest, message: "define requires non-empty term"))
            }
            let started = DispatchTime.now()
            let all = dictionaries.activeDictionaries()
            let selected = selectDictionaries(all, matching: request.dictionary)
            if selected.isEmpty {
                return Response(
                    id: request.id,
                    error: ErrorBody(
                        code: .dictionaryUnavailable,
                        message: "no active dictionary matches \(request.dictionary ?? "<any>")"
                    )
                )
            }
            let method = DictionarySearchMethod(rawValue: request.method ?? 0) ?? .exact
            var records: [DefinitionRecord] = []
            for dictionary in selected {
                records += dictionaries.records(
                    for: term,
                    in: dictionary,
                    method: method,
                    maxRecords: request.maxRecords ?? 8,
                    includeMarkup: request.includeMarkup ?? true
                )
            }
            return Response(id: request.id, result: .records(records, elapsedMs: Self.elapsedMs(since: started)))
        case .textDefinition:
            guard let term = request.term, !term.trimmingCharacters(in: .whitespaces).isEmpty else {
                return Response(id: request.id, error: ErrorBody(code: .badRequest, message: "text_definition requires non-empty term"))
            }
            let started = DispatchTime.now()
            let text = dictionaries.textDefinition(for: term) ?? ""
            return Response(id: request.id, result: .text(text, elapsedMs: Self.elapsedMs(since: started)))
        case .translate:
            guard let text = request.text, !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                return Response(id: request.id, error: ErrorBody(code: .badRequest, message: "translate requires non-empty text"))
            }
            let source = request.source ?? "en"
            let target = request.target ?? "ru"
            let started = DispatchTime.now()
            do {
                let translated = try await translator.translate(text, source: source, target: target)
                return Response(
                    id: request.id,
                    result: .translation(text: translated, source: source, target: target, elapsedMs: Self.elapsedMs(since: started))
                )
            } catch let error as TranslationFailure {
                return Response(id: request.id, error: error.body)
            } catch {
                return Response(id: request.id, error: ErrorBody(code: .translationFailed, message: "\(error)"))
            }
        }
    }

    static func elapsedMs(since started: DispatchTime) -> Double {
        Double(DispatchTime.now().uptimeNanoseconds - started.uptimeNanoseconds) / 1_000_000
    }

    /// Best-effort extraction of "id" from a malformed request so the client can correlate the error.
    static func recoverId(from line: String) -> String {
        guard let data = line.data(using: .utf8),
              let raw = try? JSONSerialization.jsonObject(with: data),
              let object = raw as? [String: Any] else { return "" }
        if let s = object["id"] as? String { return s }
        if let n = object["id"] as? NSNumber { return n.stringValue }
        return ""
    }
}
