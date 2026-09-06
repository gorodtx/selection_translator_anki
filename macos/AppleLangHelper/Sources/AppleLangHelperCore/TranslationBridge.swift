import Foundation
import Translation

public enum TranslationAvailability: String, Sendable {
    /// Language pair downloaded; offline translation works right now.
    case installed
    /// Pair exists but the model is not downloaded (needs the system download sheet).
    case supported
    case unsupported
    /// Translation framework is not usable on this OS version.
    case unavailable
}

/// Typed failure so the dispatcher can map it to a wire error code.
public struct TranslationFailure: Error, Sendable, Equatable {
    public let body: ErrorBody

    public init(code: ErrorCode, message: String) {
        body = ErrorBody(code: code, message: message)
    }

    public static func notInstalled(_ source: String, _ target: String) -> TranslationFailure {
        TranslationFailure(
            code: .translationNotInstalled,
            message: "language pair \(source)->\(target) is not downloaded"
        )
    }
}

public protocol Translating: Sendable {
    func availability(source: String, target: String) async -> TranslationAvailability
    func translate(_ text: String, source: String, target: String) async throws -> String
}

/// Apple Translation framework, headless. Works only for language pairs the user has already
/// downloaded (System Settings > General > Language & Region > Translation Languages, or the
/// SwiftUI `.translationTask` sheet); a headless process cannot trigger the download itself.
public struct SystemTranslator: Translating {
    public init() {}

    public func availability(source: String, target: String) async -> TranslationAvailability {
        guard #available(macOS 15.0, *) else { return .unavailable }
        let status = await LanguageAvailability().status(
            from: Locale.Language(identifier: source),
            to: Locale.Language(identifier: target)
        )
        switch status {
        case .installed: return .installed
        case .supported: return .supported
        case .unsupported: return .unsupported
        @unknown default: return .unsupported
        }
    }

    public func translate(_ text: String, source: String, target: String) async throws -> String {
        guard #available(macOS 26.0, *) else {
            throw TranslationFailure(code: .unsupportedOS, message: "headless TranslationSession needs macOS 26")
        }
        let session = TranslationSession(
            installedSource: Locale.Language(identifier: source),
            target: Locale.Language(identifier: target)
        )
        do {
            let response = try await session.translate(text)
            return response.targetText
        } catch {
            throw Self.classify(error, source: source, target: target)
        }
    }

    static func classify(_ error: any Error, source: String, target: String) -> TranslationFailure {
        if #available(macOS 26.4, *) {
            if TranslationError.notInstalled ~= error {
                return .notInstalled(source, target)
            }
            if TranslationError.unsupportedLanguagePairing ~= error
                || TranslationError.unsupportedSourceLanguage ~= error
                || TranslationError.unsupportedTargetLanguage ~= error {
                return TranslationFailure(code: .translationUnsupported, message: "\(error)")
            }
            if TranslationError.nothingToTranslate ~= error {
                return TranslationFailure(code: .badRequest, message: "nothing to translate")
            }
        }
        // Older systems: fall back to matching the description the framework prints.
        let description = "\(error)".lowercased()
        if description.contains("notinstalled") {
            return .notInstalled(source, target)
        }
        if description.contains("unsupported") {
            return TranslationFailure(code: .translationUnsupported, message: "\(error)")
        }
        return TranslationFailure(code: .translationFailed, message: "\(error)")
    }
}
