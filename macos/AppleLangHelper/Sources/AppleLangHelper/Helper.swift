// Headless bridge to macOS Dictionary Services and the system Translation
// framework. Speaks newline-delimited JSON on stdin/stdout so the Python
// pipeline can treat Apple's engines as ordinary providers.
//
// Request:  {"id": "1", "op": "ping|availability|dictionaries|define|text_definition|translate|shutdown",
//            "term": "...", "text": "...", "source": "en", "target": "ru"}
// Response: {"id": "1", "ok": true, "result": {...}}
//           {"id": "1", "ok": false, "error": {"code": "...", "message": "..."}}
//
// `define` answers with records (dictionary/headword/title/anchor/markup); this
// implementation reports the matching dictionaries with `markup: null`, and
// `text_definition` returns the flat DCSCopyTextDefinition text the Python side
// can parse. A structured-markup sidecar with the same protocol is a drop-in.

import CoreServices
import Foundation
import Translation

@_silgen_name("DCSGetActiveDictionaries")
private func DCSGetActiveDictionaries() -> Unmanaged<CFArray>?
@_silgen_name("DCSDictionaryGetName")
private func DCSDictionaryGetName(_ dictionary: AnyObject) -> Unmanaged<CFString>?

let helperVersion = "0.3.0"

struct HelperError: Error {
    let code: String
    let message: String
}

final class DictionaryBridge {
    struct ActiveDictionary {
        let name: String
        let ref: AnyObject
    }

    private(set) var active: [ActiveDictionary] = []

    init() {
        guard let array = DCSGetActiveDictionaries() else { return }
        let items = array.takeUnretainedValue() as [AnyObject]
        active = items.map { item in
            let name = DCSDictionaryGetName(item).map { $0.takeUnretainedValue() as String } ?? "?"
            return ActiveDictionary(name: name, ref: item)
        }
    }

    /// Dictionaries that have an entry for `term` (flat lookup per dictionary).
    func records(for term: String, filter: String?) -> [[String: Any]] {
        let range = CFRangeMake(0, (term as NSString).length)
        var out: [[String: Any]] = []
        for entry in active {
            if let filter, !filter.isEmpty, !entry.name.localizedCaseInsensitiveContains(filter) {
                continue
            }
            let dictionary = unsafeBitCast(entry.ref, to: DCSDictionary.self)
            guard let raw = lookup(dictionary: dictionary, term: term, range: range) else { continue }
            out.append([
                "dictionary": entry.name,
                "headword": headword(from: raw, fallback: term),
                "title": NSNull(),
                "anchor": NSNull(),
                "markup": NSNull(),
            ])
        }
        return out
    }

    func textDefinition(for term: String, filter: String?) -> String? {
        let range = CFRangeMake(0, (term as NSString).length)
        if let filter, !filter.isEmpty {
            for entry in active where entry.name.localizedCaseInsensitiveContains(filter) {
                let dictionary = unsafeBitCast(entry.ref, to: DCSDictionary.self)
                if let raw = lookup(dictionary: dictionary, term: term, range: range) { return raw }
            }
            return nil
        }
        return lookup(dictionary: nil, term: term, range: range)
    }

    private func lookup(dictionary: DCSDictionary?, term: String, range: CFRange) -> String? {
        guard let value = DCSCopyTextDefinition(dictionary, term as CFString, range) else { return nil }
        let raw = value.takeRetainedValue() as String
        return raw.isEmpty ? nil : raw
    }

    private func headword(from raw: String, fallback: String) -> String {
        guard let bar = raw.range(of: " | ") else { return fallback }
        var head = String(raw[raw.startIndex..<bar.lowerBound]).trimmingCharacters(in: .whitespaces)
        // "bank 1" -> "bank"
        while let last = head.last, last.isNumber {
            head.removeLast()
        }
        head = head.trimmingCharacters(in: .whitespaces)
        return head.isEmpty ? fallback : head
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
            return try await session.translate(text).targetText
        } catch {
            sessions[key] = nil
            throw Self.mapError(error)
        }
    }

    func status(source: String, target: String) async -> String {
        let availability = LanguageAvailability()
        let status = await availability.status(
            from: Locale.Language(identifier: source),
            to: Locale.Language(identifier: target)
        )
        switch status {
        case .installed: return "installed"
        case .supported: return "supported"
        case .unsupported: return "unsupported"
        @unknown default: return "unknown"
        }
    }

    private static func mapError(_ error: Error) -> HelperError {
        let description = String(describing: error)
        if description.contains("notInstalled") {
            return HelperError(code: "translation_not_installed", message: description)
        }
        if description.lowercased().contains("unsupported") {
            return HelperError(code: "translation_unsupported", message: description)
        }
        return HelperError(code: "translation_failed", message: description)
    }
}

final class Output {
    private let handle = FileHandle.standardOutput

    func send(id: String, result: [String: Any]) {
        write(["id": id, "ok": true, "result": result])
    }

    func send(id: String, error: HelperError) {
        write(["id": id, "ok": false, "error": ["code": error.code, "message": error.message]])
    }

    private func write(_ object: [String: Any]) {
        guard var data = try? JSONSerialization.data(
            withJSONObject: object, options: [.withoutEscapingSlashes, .sortedKeys]
        ) else { return }
        data.append(0x0A)
        handle.write(data)
    }
}

func string(_ object: [String: Any], _ key: String) -> String? {
    if let value = object[key] as? String { return value }
    if let number = object[key] as? NSNumber { return number.stringValue }
    return nil
}

@main
struct Helper {
    static func main() async {
        let output = Output()
        let dictionary = DictionaryBridge()
        let translation = TranslationBridge()

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
            guard let raw = try? JSONSerialization.jsonObject(with: Data(trimmed.utf8)),
                  let request = raw as? [String: Any],
                  let id = string(request, "id"),
                  let op = request["op"] as? String
            else {
                output.send(id: "0", error: HelperError(code: "bad_request", message: "malformed request"))
                continue
            }
            let source = string(request, "source") ?? "en"
            let target = string(request, "target") ?? "ru"
            switch op {
            case "ping":
                output.send(id: id, result: ["pong": true, "version": helperVersion])
            case "dictionaries":
                output.send(id: id, result: [
                    "dictionaries": dictionary.active.map { ["name": $0.name, "short_name": NSNull()] },
                ])
            case "availability":
                let status = await translation.status(source: source, target: target)
                output.send(id: id, result: [
                    "source": source,
                    "target": target,
                    "status": status,
                    "dictionaries": dictionary.active.map { ["name": $0.name, "short_name": NSNull()] },
                ])
            case "define", "text_definition":
                guard let term = string(request, "term") ?? string(request, "text"), !term.isEmpty else {
                    output.send(id: id, error: HelperError(code: "bad_request", message: "term is required"))
                    continue
                }
                let filter = string(request, "dictionary")
                let started = DispatchTime.now()
                if op == "define" {
                    let records = dictionary.records(for: term, filter: filter)
                    output.send(id: id, result: ["records": records, "elapsed_ms": elapsedMs(since: started)])
                } else {
                    let text = dictionary.textDefinition(for: term, filter: filter) ?? ""
                    output.send(id: id, result: ["text": text, "elapsed_ms": elapsedMs(since: started)])
                }
            case "translate":
                guard let text = string(request, "text"), !text.isEmpty else {
                    output.send(id: id, error: HelperError(code: "bad_request", message: "text is required"))
                    continue
                }
                let started = DispatchTime.now()
                do {
                    let translated = try await translation.translate(text, source: source, target: target)
                    output.send(id: id, result: [
                        "text": translated, "source": source, "target": target,
                        "elapsed_ms": elapsedMs(since: started),
                    ])
                } catch let error as HelperError {
                    output.send(id: id, error: error)
                } catch {
                    output.send(id: id, error: HelperError(code: "translation_failed", message: String(describing: error)))
                }
            case "shutdown":
                output.send(id: id, result: ["shutting_down": true])
                return
            default:
                output.send(id: id, error: HelperError(code: "unknown_op", message: "unknown op \(op)"))
            }
        }
    }
}

func elapsedMs(since started: DispatchTime) -> Double {
    Double(DispatchTime.now().uptimeNanoseconds - started.uptimeNanoseconds) / 1_000_000
}
