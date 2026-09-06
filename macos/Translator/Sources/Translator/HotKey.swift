import AppKit
import Carbon.HIToolbox
import TranslatorCore

/// Global hot key via Carbon `RegisterEventHotKey` — works with no TCC permission at all.
///
/// Carbon is the only API that still delivers a system-wide shortcut without Accessibility
/// or Input Monitoring, which is why AppKit-era code keeps using it.
@MainActor
final class HotKeyManager {
    private var handlerRef: EventHandlerRef?
    private var hotKeyRef: EventHotKeyRef?
    private var combo: KeyCombo?
    private var action: (() -> Void)?
    private let signature = OSType(0x54524E53) // 'TRNS'

    /// Registers `combo`; replaces any previous registration. Returns false when the
    /// shortcut is already taken by another app.
    @discardableResult
    func register(_ combo: KeyCombo, action: @escaping () -> Void) -> Bool {
        unregister()
        self.combo = combo
        self.action = action
        installHandlerIfNeeded()

        var reference: EventHotKeyRef?
        let hotKeyID = EventHotKeyID(signature: signature, id: 1)
        let status = RegisterEventHotKey(
            combo.keyCode,
            combo.modifiers,
            hotKeyID,
            GetEventDispatcherTarget(),
            0,
            &reference
        )
        guard status == noErr, let reference else {
            self.combo = nil
            return false
        }
        hotKeyRef = reference
        return true
    }

    func unregister() {
        if let hotKeyRef {
            UnregisterEventHotKey(hotKeyRef)
            self.hotKeyRef = nil
        }
        combo = nil
    }

    var current: KeyCombo? { combo }

    private func installHandlerIfNeeded() {
        guard handlerRef == nil else { return }
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        let context = Unmanaged.passUnretained(self).toOpaque()
        InstallEventHandler(
            GetEventDispatcherTarget(),
            { _, event, userData in
                guard let userData, let event else { return OSStatus(eventNotHandledErr) }
                var pressedID = EventHotKeyID()
                let status = GetEventParameter(
                    event,
                    EventParamName(kEventParamDirectObject),
                    EventParamType(typeEventHotKeyID),
                    nil,
                    MemoryLayout<EventHotKeyID>.size,
                    nil,
                    &pressedID
                )
                guard status == noErr else { return status }
                let manager = Unmanaged<HotKeyManager>.fromOpaque(userData).takeUnretainedValue()
                MainActor.assumeIsolated { manager.action?() }
                return noErr
            },
            1,
            &spec,
            context,
            &handlerRef
        )
    }

    deinit {
        if let hotKeyRef { UnregisterEventHotKey(hotKeyRef) }
        if let handlerRef { RemoveEventHandler(handlerRef) }
    }
}

/// Translates an `NSEvent` key-down into a `KeyCombo` for the shortcut recorder.
enum KeyComboRecorder {
    static func combo(from event: NSEvent) -> KeyCombo? {
        let flags = event.modifierFlags.intersection(.deviceIndependentFlagsMask)
        var modifiers: UInt32 = 0
        if flags.contains(.command) { modifiers |= KeyCombo.commandMask }
        if flags.contains(.option) { modifiers |= KeyCombo.optionMask }
        if flags.contains(.control) { modifiers |= KeyCombo.controlMask }
        if flags.contains(.shift) { modifiers |= KeyCombo.shiftMask }
        let combo = KeyCombo(keyCode: UInt32(event.keyCode), modifiers: modifiers)
        return combo.isUsable ? combo : nil
    }
}
