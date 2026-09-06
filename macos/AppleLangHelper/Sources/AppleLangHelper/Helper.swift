// Headless bridge to macOS Dictionary Services and the system Translation
// framework. Speaks newline-delimited JSON on stdin/stdout so the Python
// pipeline can treat Apple's engines as ordinary providers.
//
// Request:  {"id": 1, "op": "define" | "translate" | "status", "text": "...",
//            "source": "en", "target": "ru"}
// Response: {"id": 1, "ok": true, "result": {...}}
//           {"id": 1, "ok": false, "error": {"code": "...", "message": "..."}}

import CoreServices
import Foundation
import Translation

// Dictionary Services SPI: present in the framework's export list but not in
// the public header. Only used to enumerate dictionaries; lookups themselves go
// through the public DCSCopyTextDefinition.
@_silgen_name("DCSGetActiveDictionaries")
private func DCSGetActiveDictionaries() -> Unmanaged<CFArray>?
@_silgen_name("DCSDictionaryGetName")
private func DCSDictionaryGetName(_ dictionary: AnyObject) -> Unmanaged<CFString>?

struct Request: Decodable {
    let id: Int
    let op: String
    let text: String?
    let source: String?
    let target: String?
}

struct HelperError: Error {
    let code: String
    let message: String
}

struct DictionaryHit: Encodable {
    let dictionary: String
    let raw: String
}

struct DefineResult: Encodable {
    let results: [DictionaryHit]
}

struct TranslateResult: Encodable {
    let text: String
    let source: String
    let target: String
}

struct TranslationStatus: Encodable {
    let status: String
    let supportedCount: Int
}

struct StatusResult: Encodable {
    let dictionaries: [String]
    let translation: TranslationStatus
}

struct ErrorBody: Encodable {
    let code: String
    let message: String
}

struct Response<T: Encodable>: Encodable {
    let id: Int
    let ok: Bool
    let result: T?
    let error: ErrorBody?
}

final class DictionaryBridge {
    struct ActiveDictionary {
        let name: String
        let ref: AnyObject
    }

    private(set) var active: [ActiveDictionary] = []

    init() {
        active = Self.loadActive()
    }

    private static func loadActive() -> [ActiveDictionary] {
        guard let array = DCSGetActiveDictionaries() else { return [] }
        let items = array.takeUnretainedValue() as [AnyObject]
        return items.map { item in
            let name = DCSDictionaryGetName(item).map { $0.takeUnretainedValue() as String } ?? "?"
            return ActiveDictionary(name: name, ref: item)
        }
    }

    func define(_ text: String) -> [DictionaryHit] {
        let range = CFRangeMake(0, (text as NSString).length)
        var hits: [DictionaryHit] = []
        if active.isEmpty {
            if let raw = lookup(dictionary: nil, text: text, range: range) {
                hits.append(DictionaryHit(dictionary: "default", raw: raw))
            }
            return hits
        }
        for entry in active {
            let dictionary = unsafeBitCast(entry.ref, to: DCSDictionary.self)
            if let raw = lookup(dictionary: dictionary, text: text, range: range) {
                hits.append(DictionaryHit(dictionary: entry.name, raw: raw))
            }
        }
        return hits
    }

    private func lookup(dictionary: DCSDictionary?, text: String, range: CFRange) -> String? {
        guard let value = DCSCopyTextDefinition(dictionary, text as CFString, range) else {
            return nil
        }
        let raw = value.takeRetainedValue() as String
        return raw.isEmpty ? nil : raw
    }
}

actor TranslationBridge {
    private var sessions: [String: TranslationSession] = [:]

    func translate(_ text: String, source: String, target: String) async throws -> String {
        let key = "\(source)->\(target)"
        let session: TranslationSession
        if let existing = sessions[key] {
            session = existing
        } else {
            session = TranslationSession(
                installedSource: Locale.Language(identifier: source),
                target: Locale.Language(identifier: target)
            )
            sessions[key] = session
        }
        do {
            let response = try await session.translate(text)
            return response.targetText
        } catch {
            sessions[key] = nil
            throw Self.mapError(error)
        }
    }

    func status(source: String, target: String) async -> TranslationStatus {
        let availability = LanguageAvailability()
        let status = await availability.status(
            from: Locale.Language(identifier: source),
            to: Locale.Language(identifier: target)
        )
        let count = await availability.supportedLanguages.count
        let label: String
        switch status {
        case .installed: label = "installed"
        case .supported: label = "supported"
        case .unsupported: label = "unsupported"
        @unknown default: label = "unknown"
        }
        return TranslationStatus(status: label, supportedCount: count)
    }

    private static func mapError(_ error: Error) -> HelperError {
        let description = String(describing: error)
        if description.contains("notInstalled") {
            return HelperError(code: "not_installed", message: description)
        }
        if description.lowercased().contains("unsupported") {
            return HelperError(code: "unsupported", message: description)
        }
        return HelperError(code: "translation_failed", message: description)
    }
}

final class Output {
    private let handle = FileHandle.standardOutput
    private let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.withoutEscapingSlashes]
        return encoder
    }()

    func send<T: Encodable>(id: Int, result: T) {
        write(Response(id: id, ok: true, result: result, error: nil))
    }

    func send(id: Int, error: HelperError) {
        write(Response<StatusResult>(
            id: id, ok: false, result: nil,
            error: ErrorBody(code: error.code, message: error.message)
        ))
    }

    private func write<T: Encodable>(_ response: Response<T>) {
        guard var data = try? encoder.encode(response) else { return }
        data.append(0x0A)
        handle.write(data)
    }
}

@main
struct Helper {
    static func main() async {
        let output = Output()
        let dictionary = DictionaryBridge()
        let translation = TranslationBridge()
        let decoder = JSONDecoder()

        let lines = AsyncStream<String> { continuation in
            let thread = Thread {
                while let line = readLine(strippingNewline: true) {
                    continuation.yield(line)
                }
                continuation.finish()
            }
            thread.start()
        }

        for await line in lines {
            let trimmed = line.trimmingCharacters(in: .whitespaces)
            if trimmed.isEmpty { continue }
            guard let request = try? decoder.decode(Request.self, from: Data(trimmed.utf8)) else {
                output.send(id: 0, error: HelperError(code: "bad_request", message: "malformed request"))
                continue
            }
            switch request.op {
            case "status":
                let status = await translation.status(
                    source: request.source ?? "en", target: request.target ?? "ru")
                output.send(id: request.id, result: StatusResult(
                    dictionaries: dictionary.active.map(\.name), translation: status))
            case "define":
                guard let text = request.text, !text.isEmpty else {
                    output.send(id: request.id, error: HelperError(code: "invalid_params", message: "text is required"))
                    continue
                }
                output.send(id: request.id, result: DefineResult(results: dictionary.define(text)))
            case "translate":
                guard let text = request.text, !text.isEmpty else {
                    output.send(id: request.id, error: HelperError(code: "invalid_params", message: "text is required"))
                    continue
                }
                let source = request.source ?? "en"
                let target = request.target ?? "ru"
                do {
                    let translated = try await translation.translate(text, source: source, target: target)
                    output.send(id: request.id, result: TranslateResult(text: translated, source: source, target: target))
                } catch let error as HelperError {
                    output.send(id: request.id, error: error)
                } catch {
                    output.send(id: request.id, error: HelperError(code: "translation_failed", message: String(describing: error)))
                }
            default:
                output.send(id: request.id, error: HelperError(code: "unknown_op", message: "unknown op \(request.op)"))
            }
        }
    }
}
