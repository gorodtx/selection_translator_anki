import Foundation

/// Whether the configured field names match the note type Anki actually has.
///
/// Getting one wrong is invisible in Settings and fails much later, when a card is added,
/// far from the setting that caused it. The rule that matters here is a negative one: an
/// empty field list means there is nothing to compare against — the note type does not
/// exist, or Anki is closed, and both answer alike — so flagging every name at that point
/// would paint a correct configuration red. That is why the decision lives in a pure
/// function instead of in the view.
public struct AnkiFieldIssue: Equatable, Sendable, Identifiable {
    public let configured: String
    /// A field the note type does have that differs only in case or surrounding space,
    /// when there is one. Then the fix is obvious rather than a hunt.
    public let suggestion: String?

    public var id: String { configured }

    public init(configured: String, suggestion: String? = nil) {
        self.configured = configured
        self.suggestion = suggestion
    }
}

public enum AnkiFieldCheck {
    /// Anki's own refusal, plus what it means here.
    ///
    /// A mistyped field name makes Anki answer "cannot create note because it is empty",
    /// which sends the user to look at the card — the note is not empty, the name is
    /// wrong. Both halves are known on this side, so the message says both. With nothing
    /// known, Anki's words stand alone rather than being decorated with a guess.
    public static func explain(failure: String, issues: [AnkiFieldIssue]) -> String {
        guard !issues.isEmpty else { return failure }
        let names = issues.map { "“\($0.configured)”" }.joined(separator: ", ")
        let plural = issues.count == 1 ? "no" : "none of"
        let suggestion = issues.compactMap(\.suggestion).first
        let fix = suggestion.map { " Anki has “\($0)”." } ?? ""
        return "\(failure) The note type has \(plural) \(names).\(fix) Fix the field mapping in Settings."
    }

    /// Configured names the note type does not have. Empty when nothing can be concluded.
    public static func issues(configured: [String], modelFields: [String]) -> [AnkiFieldIssue] {
        // Nothing to compare against is not the same as everything being wrong.
        guard !modelFields.isEmpty else { return [] }

        let known = Set(modelFields.map { $0.trimmingCharacters(in: .whitespaces) })
        // A name differing only in case is the common mistake, and worth naming outright.
        var nearby: [String: String] = [:]
        for field in modelFields {
            let key = field.trimmingCharacters(in: .whitespaces).lowercased()
            if nearby[key] == nil { nearby[key] = field }
        }

        var reported = Set<String>()
        return configured.compactMap { name in
            let trimmed = name.trimmingCharacters(in: .whitespaces)
            // An empty mapping means "leave this field alone", which the backend honours
            // by dropping it. Not a mistake, so not a warning.
            guard !trimmed.isEmpty, !known.contains(trimmed) else { return nil }
            guard reported.insert(trimmed).inserted else { return nil }
            return AnkiFieldIssue(configured: name, suggestion: nearby[trimmed.lowercased()])
        }
    }
}
