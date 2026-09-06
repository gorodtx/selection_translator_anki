@preconcurrency import CoreServices
import Foundation

// Dictionary Services SPI. These symbols have been exported by
// CoreServices/DictionaryServices since 10.5 and are what Dictionary.app itself uses.
// "Get" functions return +0 references, hence `Unmanaged`; "Copy" functions return +1.
@_silgen_name("DCSGetActiveDictionaries")
private func _DCSGetActiveDictionaries() -> Unmanaged<CFArray>?

@_silgen_name("DCSDictionaryGetName")
private func _DCSDictionaryGetName(_ dictionary: DCSDictionary) -> Unmanaged<CFString>?

@_silgen_name("DCSDictionaryGetShortName")
private func _DCSDictionaryGetShortName(_ dictionary: DCSDictionary) -> Unmanaged<CFString>?

@_silgen_name("DCSCopyRecordsForSearchString")
private func _DCSCopyRecordsForSearchString(
    _ dictionary: DCSDictionary, _ string: CFString, _ method: UInt, _ maxResults: UInt
) -> CFArray?

@_silgen_name("DCSRecordGetHeadword")
private func _DCSRecordGetHeadword(_ record: CFTypeRef) -> Unmanaged<CFString>?

@_silgen_name("DCSRecordGetTitle")
private func _DCSRecordGetTitle(_ record: CFTypeRef) -> Unmanaged<CFString>?

@_silgen_name("DCSRecordGetAnchor")
private func _DCSRecordGetAnchor(_ record: CFTypeRef) -> Unmanaged<CFString>?

@_silgen_name("DCSRecordCopyData")
private func _DCSRecordCopyData(_ record: CFTypeRef, _ version: Int) -> CFString?

public enum DictionarySearchMethod: Int, Sendable {
    case exact = 0
    case prefix = 1
    case wildcard = 3
}

public struct ActiveDictionary: Sendable {
    public let name: String
    public let shortName: String?
    fileprivate let ref: DCSDictionary

    public var info: DictionaryInfo { DictionaryInfo(name: name, shortName: shortName) }
}

/// Thin, synchronous bridge over Dictionary Services. Cheap to create; safe to keep around.
public struct DictionaryLookup: Sendable {
    public init() {}

    /// Dictionaries the user has enabled in Dictionary.app, in their configured order.
    public func activeDictionaries() -> [ActiveDictionary] {
        guard let array = _DCSGetActiveDictionaries()?.takeUnretainedValue() else { return [] }
        var result: [ActiveDictionary] = []
        for index in 0..<CFArrayGetCount(array) {
            guard let pointer = CFArrayGetValueAtIndex(array, index) else { continue }
            let dictionary = Unmanaged<DCSDictionary>.fromOpaque(pointer).takeUnretainedValue()
            let name = _DCSDictionaryGetName(dictionary).map { $0.takeUnretainedValue() as String } ?? ""
            let short = _DCSDictionaryGetShortName(dictionary).map { $0.takeUnretainedValue() as String }
            result.append(ActiveDictionary(name: name, shortName: short, ref: dictionary))
        }
        return result
    }

    /// Records matching `term` in `dictionary`.
    public func records(
        for term: String,
        in dictionary: ActiveDictionary,
        method: DictionarySearchMethod = .exact,
        maxRecords: Int = 8,
        includeMarkup: Bool = true
    ) -> [DefinitionRecord] {
        let trimmed = term.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return [] }
        guard let array = _DCSCopyRecordsForSearchString(
            dictionary.ref, trimmed as CFString, UInt(method.rawValue), 0
        ) else { return [] }
        var result: [DefinitionRecord] = []
        let count = CFArrayGetCount(array)
        for index in 0..<min(count, max(0, maxRecords)) {
            guard let pointer = CFArrayGetValueAtIndex(array, index) else { continue }
            let record = Unmanaged<CFTypeRef>.fromOpaque(pointer).takeUnretainedValue()
            let headword = _DCSRecordGetHeadword(record).map { $0.takeUnretainedValue() as String } ?? trimmed
            let title = _DCSRecordGetTitle(record).map { $0.takeUnretainedValue() as String }
            let anchor = _DCSRecordGetAnchor(record).map { $0.takeUnretainedValue() as String }
            let markup = includeMarkup ? _DCSRecordCopyData(record, 0).map { $0 as String } : nil
            result.append(
                DefinitionRecord(
                    dictionary: dictionary.name,
                    headword: headword,
                    title: title,
                    anchor: anchor,
                    markup: markup
                )
            )
        }
        return result
    }

    /// Public-API fallback: flat text of the first matching entry across active dictionaries.
    public func textDefinition(for term: String) -> String? {
        let trimmed = term.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        let cf = trimmed as CFString
        let range = CFRangeMake(0, CFStringGetLength(cf))
        guard let definition = DCSCopyTextDefinition(nil, cf, range) else { return nil }
        return definition.takeRetainedValue() as String
    }
}

/// Select dictionaries by a case-insensitive substring of their display name.
public func selectDictionaries(_ all: [ActiveDictionary], matching needle: String?) -> [ActiveDictionary] {
    guard let needle, !needle.isEmpty else { return all }
    let lowered = needle.lowercased()
    return all.filter { $0.name.lowercased().contains(lowered) || ($0.shortName?.lowercased().contains(lowered) ?? false) }
}
