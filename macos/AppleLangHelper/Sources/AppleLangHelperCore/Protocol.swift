import Foundation

/// Wire protocol: one JSON object per line on stdin (request) and stdout (response).
///
/// Every request carries a client-chosen `id`; the matching response echoes it, so the
/// client may pipeline several requests. Unknown fields are ignored on both sides.
public enum Op: String, Codable, Sendable {
    case ping
    case dictionaries
    case availability
    case define
    case textDefinition = "text_definition"
    case translate
    case shutdown
}

public struct Request: Codable, Sendable {
    public var id: String
    public var op: Op
    /// `define` / `text_definition`: the term to look up.
    public var term: String?
    /// `define`: substring of the dictionary display name to search in (nil = every active one).
    public var dictionary: String?
    /// `define`: 0 exact (default), 1 prefix, 3 wildcard.
    public var method: Int?
    /// `define`: cap on records returned (default 8).
    public var maxRecords: Int?
    /// `define`: include entry markup (default true).
    public var includeMarkup: Bool?
    /// `translate`: text to translate; `availability`: ignored.
    public var text: String?
    /// BCP-47 language identifiers for `translate` / `availability` (default en -> ru).
    public var source: String?
    public var target: String?

    enum CodingKeys: String, CodingKey {
        case id, op, term, dictionary, method, text, source, target
        case maxRecords = "max_records"
        case includeMarkup = "include_markup"
    }

    public init(
        id: String,
        op: Op,
        term: String? = nil,
        dictionary: String? = nil,
        method: Int? = nil,
        maxRecords: Int? = nil,
        includeMarkup: Bool? = nil,
        text: String? = nil,
        source: String? = nil,
        target: String? = nil
    ) {
        self.id = id
        self.op = op
        self.term = term
        self.dictionary = dictionary
        self.method = method
        self.maxRecords = maxRecords
        self.includeMarkup = includeMarkup
        self.text = text
        self.source = source
        self.target = target
    }
}

public enum ErrorCode: String, Codable, Sendable {
    case badRequest = "bad_request"
    case unknownOp = "unknown_op"
    case dictionaryUnavailable = "dictionary_unavailable"
    case translationUnsupported = "translation_unsupported"
    case translationNotInstalled = "translation_not_installed"
    case translationFailed = "translation_failed"
    case unsupportedOS = "unsupported_os"
    case internalError = "internal"
}

public struct ErrorBody: Codable, Sendable, Equatable {
    public var code: ErrorCode
    public var message: String

    public init(code: ErrorCode, message: String) {
        self.code = code
        self.message = message
    }
}

public struct DictionaryInfo: Codable, Sendable, Equatable {
    public var name: String
    public var shortName: String?

    enum CodingKeys: String, CodingKey {
        case name
        case shortName = "short_name"
    }

    public init(name: String, shortName: String?) {
        self.name = name
        self.shortName = shortName
    }
}

public struct DefinitionRecord: Codable, Sendable, Equatable {
    public var dictionary: String
    public var headword: String
    public var title: String?
    public var anchor: String?
    public var markup: String?

    public init(dictionary: String, headword: String, title: String?, anchor: String?, markup: String?) {
        self.dictionary = dictionary
        self.headword = headword
        self.title = title
        self.anchor = anchor
        self.markup = markup
    }
}

public struct AvailabilityResult: Codable, Sendable, Equatable {
    public var source: String
    public var target: String
    /// "installed" | "supported" | "unsupported" | "unavailable" (framework missing on this OS)
    public var status: String
    public var dictionaries: [DictionaryInfo]

    public init(source: String, target: String, status: String, dictionaries: [DictionaryInfo]) {
        self.source = source
        self.target = target
        self.status = status
        self.dictionaries = dictionaries
    }
}

public enum ResultBody: Sendable, Equatable {
    case pong(version: String)
    case dictionaries([DictionaryInfo])
    case availability(AvailabilityResult)
    case records([DefinitionRecord], elapsedMs: Double)
    case text(String, elapsedMs: Double)
    case translation(text: String, source: String, target: String, elapsedMs: Double)
    case shuttingDown
}

public struct Response: Sendable, Equatable {
    public var id: String
    public var result: ResultBody?
    public var error: ErrorBody?

    public init(id: String, result: ResultBody) {
        self.id = id
        self.result = result
        self.error = nil
    }

    public init(id: String, error: ErrorBody) {
        self.id = id
        self.result = nil
        self.error = error
    }

    public var ok: Bool { error == nil }
}

// MARK: - JSON encoding of responses (hand-rolled so the shape stays flat and stable)

extension Response {
    public func jsonObject() -> [String: Any] {
        var object: [String: Any] = ["id": id, "ok": ok]
        if let error {
            object["error"] = ["code": error.code.rawValue, "message": error.message]
        }
        if let result {
            object["result"] = result.jsonObject()
        }
        return object
    }

    /// One line of JSON without embedded newlines.
    public func jsonLine() throws -> String {
        let data = try JSONSerialization.data(
            withJSONObject: jsonObject(),
            options: [.withoutEscapingSlashes, .sortedKeys]
        )
        guard var line = String(data: data, encoding: .utf8) else {
            throw CocoaError(.coderInvalidValue)
        }
        // JSONSerialization never emits raw newlines inside strings, but be defensive.
        line = line.replacingOccurrences(of: "\n", with: "\\n")
        return line
    }
}

extension ResultBody {
    func jsonObject() -> [String: Any] {
        switch self {
        case let .pong(version):
            return ["pong": true, "version": version]
        case let .dictionaries(list):
            return ["dictionaries": list.map(Self.dictionaryObject)]
        case let .availability(a):
            return [
                "source": a.source,
                "target": a.target,
                "status": a.status,
                "dictionaries": a.dictionaries.map(Self.dictionaryObject),
            ]
        case let .records(records, elapsedMs):
            return [
                "elapsed_ms": elapsedMs,
                "records": records.map { r in
                    var o: [String: Any] = ["dictionary": r.dictionary, "headword": r.headword]
                    o["title"] = r.title ?? NSNull()
                    o["anchor"] = r.anchor ?? NSNull()
                    o["markup"] = r.markup ?? NSNull()
                    return o
                },
            ]
        case let .text(text, elapsedMs):
            return ["text": text, "elapsed_ms": elapsedMs]
        case let .translation(text, source, target, elapsedMs):
            return ["text": text, "source": source, "target": target, "elapsed_ms": elapsedMs]
        case .shuttingDown:
            return ["shutting_down": true]
        }
    }

    private static func dictionaryObject(_ d: DictionaryInfo) -> [String: Any] {
        var o: [String: Any] = ["name": d.name]
        o["short_name"] = d.shortName ?? NSNull()
        return o
    }
}

// MARK: - Request decoding

public enum RequestDecodingError: Error, Equatable {
    case notJSON
    case missingId
    case missingOp
    case unknownOp(String)
}

public func decodeRequest(line: String) throws -> Request {
    guard let data = line.data(using: .utf8) else { throw RequestDecodingError.notJSON }
    let raw: Any
    do {
        raw = try JSONSerialization.jsonObject(with: data)
    } catch {
        throw RequestDecodingError.notJSON
    }
    guard let object = raw as? [String: Any] else { throw RequestDecodingError.notJSON }
    // id may be a number or a string; normalise to string.
    let id: String
    if let s = object["id"] as? String {
        id = s
    } else if let n = object["id"] as? NSNumber {
        id = n.stringValue
    } else {
        throw RequestDecodingError.missingId
    }
    guard let opRaw = object["op"] as? String else { throw RequestDecodingError.missingOp }
    guard let op = Op(rawValue: opRaw) else { throw RequestDecodingError.unknownOp(opRaw) }
    return Request(
        id: id,
        op: op,
        term: object["term"] as? String,
        dictionary: object["dictionary"] as? String,
        method: (object["method"] as? NSNumber)?.intValue,
        maxRecords: (object["max_records"] as? NSNumber)?.intValue,
        includeMarkup: (object["include_markup"] as? NSNumber).map { $0.boolValue },
        text: object["text"] as? String,
        source: object["source"] as? String,
        target: object["target"] as? String
    )
}
