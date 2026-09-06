import AppKit
import SwiftUI
import TranslatorCore

@main
struct TranslatorApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate

    var body: some Scene {
        MenuBarExtra("Translator", systemImage: "character.bubble") {
            MenuBarContent(model: delegate.model, delegate: delegate)
        }
        .menuBarExtraStyle(.menu)
    }
}

private struct MenuBarContent: View {
    @Bindable var model: AppModel
    let delegate: AppDelegate

    var body: some View {
        Text(model.connectionSummary)
        Divider()
        Button("Translate Selection  \(model.hotKey.displayString)") { delegate.translateSelection() }
        Button("History…") { delegate.showHistory() }
        Button("Settings…") { delegate.showSettings() }
        Divider()
        Button("Quit Translator") { NSApplication.shared.terminate(nil) }
            .keyboardShortcut("q")
    }
}

/// Owns everything AppKit: hot key, Services entry, the floating popup, auxiliary windows.
///
/// Windows are plain `NSWindow`s hosting SwiftUI rather than SwiftUI `Window` scenes,
/// because an accessory (menu-bar) app opens them from AppKit callbacks — a hot key, a
/// Services invocation — where SwiftUI's `openWindow` action is not reachable.
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    let model: AppModel
    private let client: IPCClient
    private let hotKeys = HotKeyManager()
    private lazy var popup = PopupPanelController(model: model)
    private var windows: [String: NSWindow] = [:]
    private var stateObserver: Task<Void, Never>?

    override init() {
        let client = IPCClient(socketPath: IPCClient.defaultSocketPath())
        self.client = client
        self.model = AppModel(client: client)
        super.init()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.accessory)   // menu-bar app: no Dock icon
        NSApp.servicesProvider = self
        NSUpdateDynamicServices()

        model.loadStoredHotKey()
        applyHotKey(model.hotKey)
        model.start()
        observePopupResize()
        openDebugTargets()
    }

    /// Development hooks, so the UI can be driven without a real selection:
    /// `TRANSLATOR_DEBUG_TEXT` opens the popup on that text, `TRANSLATOR_DEBUG_WINDOW`
    /// (`settings` | `history` | `anki`) opens one auxiliary window.
    private func openDebugTargets() {
        let environment = ProcessInfo.processInfo.environment
        if let text = environment["TRANSLATOR_DEBUG_TEXT"], !text.isEmpty {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { [weak self] in
                self?.present(text: text)
            }
        }
        switch environment["TRANSLATOR_DEBUG_WINDOW"] {
        case "settings": DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { [weak self] in self?.showSettings() }
        case "history": DispatchQueue.main.asyncAfter(deadline: .now() + 0.9) { [weak self] in self?.showHistory() }
        case "anki": DispatchQueue.main.asyncAfter(deadline: .now() + 1.4) { [weak self] in self?.showAnkiSheet() }
        default: break
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        stateObserver?.cancel()
        hotKeys.unregister()
        model.stop()
    }

    // MARK: - Hot key & selection

    func applyHotKey(_ combo: KeyCombo) {
        let registered = hotKeys.register(combo) { [weak self] in
            MainActor.assumeIsolated { self?.translateSelection() }
        }
        if !registered {
            model.show(banner: "\(combo.displayString) is already taken by another app.", level: .warning)
        }
    }

    func translateSelection() {
        model.refreshAccessibilityTrust()
        guard let text = SelectionCapture.currentSelection(), !text.isEmpty else {
            if model.accessibilityTrusted {
                model.show(banner: "No text selected.", level: .info)
            } else {
                SelectionCapture.requestTrust()
                showSettings()
                model.show(banner: "Grant Accessibility to read the selection.", level: .warning)
            }
            return
        }
        present(text: text)
    }

    /// Services entry point (declared as `NSServices` in Info.plist): zero permissions.
    @objc func translateSelection(
        _ pasteboard: NSPasteboard,
        userData: String?,
        error: AutoreleasingUnsafeMutablePointer<NSString>?
    ) {
        guard let text = pasteboard.string(forType: .string), !text.isEmpty else {
            error?.pointee = "No text to translate." as NSString
            return
        }
        present(text: text)
    }

    private func present(text: String) {
        showPopup()
        Task { await model.translate(text) }
    }

    private func showPopup() {
        popup.show(
            at: NSEvent.mouseLocation,
            openAnki: { [weak self] in self?.showAnkiSheet() },
            onClose: { [weak self] in Task { await self?.model.closeSession() } }
        )
    }

    /// Keep the panel fitted while partial → final content grows.
    private func observePopupResize() {
        stateObserver = Task { [weak self] in
            var lastState: ViewState?
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(120))
                guard let self else { return }
                if self.model.state != lastState {
                    lastState = self.model.state
                    self.popup.resizeToContent()
                }
            }
        }
    }

    // MARK: - Windows

    func showHistory() {
        present(
            id: "history",
            title: "History",
            size: CGSize(width: 460, height: 480),
            view: HistoryView(model: model) { [weak self] entryId in self?.showHistoryEntry(entryId) }
        )
    }

    func showSettings() {
        present(
            id: "settings",
            title: "Translator Settings",
            size: CGSize(width: 520, height: 580),
            view: SettingsView(model: model) { [weak self] combo in self?.applyHotKey(combo) }
        )
    }

    func showAnkiSheet() {
        present(
            id: "anki",
            title: "Add to Anki",
            size: CGSize(width: 560, height: 620),
            view: AnkiUpsertSheet(model: model) { [weak self] _ in self?.close(id: "anki") }
        )
    }

    func showHistoryEntry(_ entryId: Int) {
        showPopup()
        Task { await model.selectHistory(entryId) }
    }

    private func present(id: String, title: String, size: CGSize, view: some View) {
        NSApp.activate(ignoringOtherApps: true)
        if let existing = windows[id] {
            existing.contentViewController = NSHostingController(rootView: AnyView(view))
            existing.makeKeyAndOrderFront(nil)
            return
        }
        let controller = NSHostingController(rootView: AnyView(view))
        let window = NSWindow(contentViewController: controller)
        window.title = title
        window.setContentSize(size)
        window.styleMask = [.titled, .closable, .miniaturizable, .resizable, .fullSizeContentView]
        window.titlebarAppearsTransparent = true
        window.isReleasedWhenClosed = false
        window.center()
        windows[id] = window
        window.makeKeyAndOrderFront(nil)
    }

    private func close(id: String) {
        windows[id]?.close()
    }
}
