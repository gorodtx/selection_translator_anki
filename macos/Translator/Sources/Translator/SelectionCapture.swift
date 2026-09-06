import AppKit
import ApplicationServices
import TranslatorCore

/// Reads the text the user has selected in whatever app is frontmost.
///
/// Two paths, in order of politeness:
/// 1. Accessibility — ask the focused element for `AXSelectedText`. Needs the Accessibility
///    grant, reads nothing else, and never touches the pasteboard.
/// 2. Synthetic ⌘C — save the pasteboard, copy, wait for `changeCount` to move, read, then
///    put the user's own pasteboard back. Also needs the Accessibility grant to post events.
@MainActor
enum SelectionCapture {
    static let copySettleTimeout: TimeInterval = 0.3

    static var isTrusted: Bool { AXIsProcessTrusted() }

    /// Prompts for the Accessibility grant (system dialog, once per app build).
    @discardableResult
    static func requestTrust() -> Bool {
        let options = [kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true] as CFDictionary
        return AXIsProcessTrustedWithOptions(options)
    }

    static func openAccessibilitySettings() {
        let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")!
        NSWorkspace.shared.open(url)
    }

    /// Current selection, or nil when nothing is selected or permission is missing.
    static func currentSelection() -> String? {
        if let text = accessibilitySelection(), !text.isEmpty { return text }
        guard isTrusted else { return nil }
        return copyViaKeystroke()
    }

    // MARK: - Accessibility

    static func accessibilitySelection() -> String? {
        guard isTrusted else { return nil }
        let system = AXUIElementCreateSystemWide()
        var focused: CFTypeRef?
        guard AXUIElementCopyAttributeValue(system, kAXFocusedUIElementAttribute as CFString, &focused) == .success,
              let element = focused, CFGetTypeID(element) == AXUIElementGetTypeID()
        else { return nil }
        let focusedElement = unsafeDowncast(element as AnyObject, to: AXUIElement.self)
        var selected: CFTypeRef?
        guard AXUIElementCopyAttributeValue(focusedElement, kAXSelectedTextAttribute as CFString, &selected) == .success,
              let value = selected as? String
        else { return nil }
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    // MARK: - Pasteboard fallback

    /// Sends ⌘C, waits for the pasteboard to change, and restores the previous contents.
    static func copyViaKeystroke() -> String? {
        let pasteboard = NSPasteboard.general
        let saved = snapshot(pasteboard)
        let before = pasteboard.changeCount

        guard sendCommandC() else { return nil }

        var captured: String?
        let deadline = Date().addingTimeInterval(copySettleTimeout)
        while Date() < deadline {
            if pasteboard.changeCount != before {
                captured = pasteboard.string(forType: .string)?
                    .trimmingCharacters(in: .whitespacesAndNewlines)
                break
            }
            RunLoop.current.run(mode: .default, before: Date().addingTimeInterval(0.01))
        }
        restore(saved, to: pasteboard)
        guard let captured, !captured.isEmpty else { return nil }
        return captured
    }

    private static func sendCommandC() -> Bool {
        guard let source = CGEventSource(stateID: .combinedSessionState) else { return false }
        // 8 == kVK_ANSI_C
        guard let keyDown = CGEvent(keyboardEventSource: source, virtualKey: 8, keyDown: true),
              let keyUp = CGEvent(keyboardEventSource: source, virtualKey: 8, keyDown: false)
        else { return false }
        keyDown.flags = .maskCommand
        keyUp.flags = .maskCommand
        keyDown.post(tap: .cghidEventTap)
        keyUp.post(tap: .cghidEventTap)
        return true
    }

    private struct PasteboardSnapshot {
        var items: [[NSPasteboard.PasteboardType: Data]]
    }

    private static func snapshot(_ pasteboard: NSPasteboard) -> PasteboardSnapshot {
        var items: [[NSPasteboard.PasteboardType: Data]] = []
        for item in pasteboard.pasteboardItems ?? [] {
            var contents: [NSPasteboard.PasteboardType: Data] = [:]
            for type in item.types {
                if let data = item.data(forType: type) { contents[type] = data }
            }
            if !contents.isEmpty { items.append(contents) }
        }
        return PasteboardSnapshot(items: items)
    }

    private static func restore(_ snapshot: PasteboardSnapshot, to pasteboard: NSPasteboard) {
        pasteboard.clearContents()
        guard !snapshot.items.isEmpty else { return }
        let items: [NSPasteboardItem] = snapshot.items.map { contents in
            let item = NSPasteboardItem()
            for (type, data) in contents { item.setData(data, forType: type) }
            return item
        }
        pasteboard.writeObjects(items)
    }

    /// Puts text on the general pasteboard (used by Copy all).
    static func writeToPasteboard(_ text: String) {
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString(text, forType: .string)
    }
}
