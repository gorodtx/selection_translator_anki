import Foundation

/// Splits a byte stream into newline-terminated frames, keeping partial tails.
public struct LineFramer: Sendable {
    public static let maxLineBytes = 1 << 20

    private var buffer = Data()

    public init() {}

    /// Feed a chunk; returns every complete line (without the trailing newline).
    public mutating func append(_ chunk: Data) -> [Data] {
        buffer.append(chunk)
        var lines: [Data] = []
        while let newline = buffer.firstIndex(of: 0x0A) {
            var line = buffer.subdata(in: buffer.startIndex..<newline)
            if line.last == 0x0D { line.removeLast() }
            lines.append(line)
            buffer.removeSubrange(buffer.startIndex...newline)
        }
        if buffer.count > Self.maxLineBytes {
            // A malicious or broken peer; drop the unbounded partial line.
            buffer.removeAll(keepingCapacity: false)
        }
        return lines
    }

    public var pendingBytes: Int { buffer.count }
}

public struct IPCError: Error, Equatable, Sendable, LocalizedError {
    public var code: String
    public var message: String

    public init(code: String, message: String) {
        self.code = code
        self.message = message
    }

    public var errorDescription: String? { message.isEmpty ? code : message }
}

public struct IPCResponse: Equatable, Sendable {
    public var id: String
    public var ok: Bool
    /// Serialised `result` object (re-encoded JSON) when `ok`.
    public var result: Data?
    public var error: IPCError?

    public init(id: String, ok: Bool, result: Data?, error: IPCError?) {
        self.id = id
        self.ok = ok
        self.result = result
        self.error = error
    }
}

public struct IPCEvent: Equatable, Sendable {
    public var name: String
    /// Serialised `payload` object.
    public var payload: Data

    public init(name: String, payload: Data) {
        self.name = name
        self.payload = payload
    }

    public func decode<T: Decodable>(_ type: T.Type) throws -> T {
        try IPCCoding.decoder.decode(type, from: payload)
    }
}

public enum IPCIncoming: Equatable, Sendable {
    case response(IPCResponse)
    case event(IPCEvent)
}

public enum IPCFramingError: Error, Equatable {
    case notJSON
    case notAnObject
    case missingId
}

public enum IPCFraming {
    /// Parse one NDJSON line into a response or an event.
    public static func parse(line: Data) throws -> IPCIncoming {
        let raw: Any
        do {
            raw = try JSONSerialization.jsonObject(with: line, options: [.fragmentsAllowed])
        } catch {
            throw IPCFramingError.notJSON
        }
        guard let object = raw as? [String: Any] else { throw IPCFramingError.notAnObject }
        if let event = object["event"] as? String {
            let payload = object["payload"] as? [String: Any] ?? [:]
            return .event(IPCEvent(name: event, payload: try serialise(payload)))
        }
        let id: String
        if let s = object["id"] as? String {
            id = s
        } else if let n = object["id"] as? NSNumber {
            id = n.stringValue
        } else {
            throw IPCFramingError.missingId
        }
        let ok = (object["ok"] as? Bool) ?? false
        var error: IPCError?
        if let e = object["error"] as? [String: Any] {
            error = IPCError(
                code: e["code"] as? String ?? "internal",
                message: e["message"] as? String ?? ""
            )
        }
        var result: Data?
        if let r = object["result"] as? [String: Any] {
            result = try serialise(r)
        }
        if !ok && error == nil {
            error = IPCError(code: "internal", message: "backend reported failure without details")
        }
        return .response(IPCResponse(id: id, ok: ok, result: result, error: error))
    }

    /// Encode a request frame, newline-terminated.
    public static func request(id: Int, method: String, params: [String: Any]) throws -> Data {
        let object: [String: Any] = ["id": id, "method": method, "params": params]
        var data = try JSONSerialization.data(withJSONObject: object, options: [.withoutEscapingSlashes])
        data.append(0x0A)
        return data
    }

    private static func serialise(_ object: [String: Any]) throws -> Data {
        try JSONSerialization.data(withJSONObject: object, options: [])
    }
}
