import Foundation

/// A global keyboard shortcut in Carbon terms (virtual key code + Carbon modifier mask).
public struct KeyCombo: Codable, Equatable, Hashable, Sendable {
    public static let commandMask: UInt32 = 0x0100
    public static let shiftMask: UInt32 = 0x0200
    public static let optionMask: UInt32 = 0x0800
    public static let controlMask: UInt32 = 0x1000

    /// ⌥⌘T
    public static let defaultCombo = KeyCombo(keyCode: 17, modifiers: commandMask | optionMask)

    public var keyCode: UInt32
    public var modifiers: UInt32

    public init(keyCode: UInt32, modifiers: UInt32) {
        self.keyCode = keyCode
        self.modifiers = modifiers & (Self.commandMask | Self.shiftMask | Self.optionMask | Self.controlMask)
    }

    /// Something a global hot key can sensibly be: at least one non-shift modifier.
    public var isUsable: Bool {
        modifiers & (Self.commandMask | Self.optionMask | Self.controlMask) != 0
    }

    /// "⌃⌥⇧⌘T" — macOS canonical modifier order.
    public var displayString: String {
        var text = ""
        if modifiers & Self.controlMask != 0 { text += "⌃" }
        if modifiers & Self.optionMask != 0 { text += "⌥" }
        if modifiers & Self.shiftMask != 0 { text += "⇧" }
        if modifiers & Self.commandMask != 0 { text += "⌘" }
        return text + Self.keyName(for: keyCode)
    }

    // MARK: Persistence ("keyCode:modifiers")

    public var storageString: String { "\(keyCode):\(modifiers)" }

    public init?(storageString: String) {
        let parts = storageString.split(separator: ":")
        guard parts.count == 2, let key = UInt32(parts[0]), let mods = UInt32(parts[1]) else { return nil }
        self.init(keyCode: key, modifiers: mods)
    }

    // MARK: Key names (US ANSI virtual key codes)

    private static let names: [UInt32: String] = [
        0: "A", 1: "S", 2: "D", 3: "F", 4: "H", 5: "G", 6: "Z", 7: "X", 8: "C", 9: "V",
        11: "B", 12: "Q", 13: "W", 14: "E", 15: "R", 16: "Y", 17: "T", 18: "1", 19: "2",
        20: "3", 21: "4", 22: "6", 23: "5", 24: "=", 25: "9", 26: "7", 27: "-", 28: "8",
        29: "0", 30: "]", 31: "O", 32: "U", 33: "[", 34: "I", 35: "P", 36: "↩", 37: "L",
        38: "J", 39: "'", 40: "K", 41: ";", 42: "\\", 43: ",", 44: "/", 45: "N", 46: "M",
        47: ".", 48: "⇥", 49: "Space", 50: "`", 51: "⌫", 53: "⎋", 96: "F5", 97: "F6",
        98: "F7", 99: "F3", 100: "F8", 101: "F9", 103: "F11", 105: "F13", 107: "F14",
        109: "F10", 111: "F12", 113: "F15", 115: "↖", 116: "⇞", 117: "⌦", 118: "F4",
        119: "↘", 120: "F2", 121: "⇟", 122: "F1", 123: "←", 124: "→", 125: "↓", 126: "↑",
    ]

    public static func keyName(for keyCode: UInt32) -> String {
        names[keyCode] ?? "Key \(keyCode)"
    }
}
