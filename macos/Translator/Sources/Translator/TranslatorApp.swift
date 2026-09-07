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
    private var announceDismissal: Task<Void, Never>?
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
        // Know our own permission state from the start: the setup stages read it, and it
        // is recorded where the installer report can see it.
        model.refreshAccessibilityTrust()
        applyHotKey(model.hotKey)
        openSetupIfUnfinished()
        model.start()
        observePopupResize()
        openDebugTargets()
    }

    /// Development hooks, so the UI can be driven without a real selection:
    /// `TRANSLATOR_DEBUG_TEXT` opens the popup on that text, `TRANSLATOR_DEBUG_WINDOW`
    /// (`settings` | `history` | `anki`) opens one auxiliary window,
    /// `TRANSLATOR_DEBUG_CAPTURE` runs the real capture path.
    private func openDebugTargets() {
        let environment = ProcessInfo.processInfo.environment
        if let text = environment["TRANSLATOR_DEBUG_TEXT"], !text.isEmpty {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { [weak self] in
                self?.present(text: text)
            }
        }
        // The capture path is the only one that raises the Accessibility request, and it
        // normally needs a hot key press. Without this hook the grant cannot be asked for
        // from a launch, which is exactly what an unattended check has to do.
        if environment["TRANSLATOR_DEBUG_CAPTURE"] != nil {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) { [weak self] in
                self?.translateSelection()
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
        model.shortcutRegistered = registered
        if !registered {
            announce("\(combo.displayString) is already taken by another app.", level: .warning)
        }
    }

    func translateSelection() {
        model.refreshAccessibilityTrust()
        guard let text = SelectionCapture.currentSelection(), !text.isEmpty else {
            if model.accessibilityTrusted {
                announce("No text selected.", level: .info)
            } else {
                SelectionCapture.requestTrust()
                showSettings()
                model.show(banner: "Grant Accessibility to read the selection.", level: .warning)
            }
            return
        }
        present(text: text)
    }

    /// Show Settings on a launch where setup is not finished.
    ///
    /// A menu bar app with nothing on screen gives a new user nowhere to start, and the
    /// steps that make it work — a permission, a language pair, Anki — are all in
    /// Settings. Once the required steps are done it stops appearing, so it never
    /// becomes a nag; the flag remembers that across launches.
    private func openSetupIfUnfinished() {
        guard !UserDefaults.standard.bool(forKey: Self.setupSeenKey) else { return }
        Task { @MainActor in
            // Give the backend its retry burst, so the stages show real state and not
            // "unknown" for everything.
            try? await Task.sleep(for: .seconds(2))
            model.refreshAccessibilityTrust()
            await model.refreshAll()
            let plan = SetupPlanner.plan(
                connected: model.isConnected,
                ping: model.ping,
                accessibilityTrusted: model.accessibilityTrusted,
                shortcutRegistered: model.shortcutRegistered,
                shortcut: model.hotKey.displayString,
                anki: model.ankiStatus
            )
            if plan.isReady {
                UserDefaults.standard.set(true, forKey: Self.setupSeenKey)
            } else {
                showSettings()
            }
        }
    }

    static let setupSeenKey = "setupCompleted"

    /// Say something to the user when there is no popup on screen to say it in.
    ///
    /// Banners render inside the popup, so raising one from the hot key — nothing
    /// selected, or a combination another app already owns — used to set state that
    /// nobody displayed: the key did nothing and said nothing. The panel comes up with
    /// the message and closes itself, since there is no translation to keep it open for.
    private func announce(_ message: String, level: NotificationLevel) {
        model.clearForAnnouncement()
        showPopup()
        model.show(banner: message, level: level)
        announceDismissal?.cancel()
        announceDismissal = Task { [weak self] in
            try? await Task.sleep(for: .seconds(level == .info ? 2.5 : 4))
            guard !Task.isCancelled else { return }
            await MainActor.run { self?.popup.hide() }
        }
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
