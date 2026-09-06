import AppKit
import SwiftUI
import TranslatorCore

/// Borderless floating panel that hosts the translation card.
///
/// `.nonactivatingPanel` keeps the user's app frontmost, so the selection they just made
/// stays selected; `hidesOnDeactivate = false` keeps the card up while they read it.
@MainActor
final class PopupPanelController: NSObject, NSWindowDelegate {
    private var panel: NSPanel?
    private let model: AppModel
    private var onClose: (() -> Void)?
    private var openAnki: (() -> Void)?
    private var localMonitor: Any?
    private var bodyMaxHeight = PopupLayout.bodyMaxHeight(forScreenHeight: 900)

    init(model: AppModel) {
        self.model = model
        super.init()
    }

    var isVisible: Bool { panel?.isVisible ?? false }

    func show(at pointer: CGPoint? = nil, openAnki: @escaping () -> Void, onClose: @escaping () -> Void) {
        self.onClose = onClose
        self.openAnki = openAnki
        let panel = ensurePanel()
        let screen = screenContaining(pointer ?? NSEvent.mouseLocation)
        applyBodyMaxHeight(for: screen)
        let size = fittingSize(width: PopupLayout.preferredWidth(for: model.state))
        let frame = PopupLayout.frame(
            for: size,
            pointer: pointer ?? NSEvent.mouseLocation,
            visible: screen.visibleFrame
        )
        panel.setFrame(frame, display: false)
        panel.alphaValue = 0
        panel.orderFrontRegardless()

        // Materialise: scale + fade together, so the glass reads as arriving, not blinking in.
        let content = panel.contentView
        content?.wantsLayer = true
        content?.layer?.anchorPoint = CGPoint(x: 0, y: 1)
        if !Motion.reduceMotion {
            content?.layer?.setAffineTransform(CGAffineTransform(scaleX: 0.96, y: 0.96))
        }
        NSAnimationContext.runAnimationGroup { context in
            context.duration = Motion.reduceMotion ? 0.12 : 0.22
            context.timingFunction = CAMediaTimingFunction(name: .easeOut)
            panel.animator().alphaValue = 1
            content?.layer?.setAffineTransform(.identity)
        }
        installEscapeMonitor()
    }

    func hide() {
        guard let panel, panel.isVisible else { return }
        removeEscapeMonitor()
        NSAnimationContext.runAnimationGroup { context in
            context.duration = Motion.reduceMotion ? 0.1 : 0.16
            panel.animator().alphaValue = 0
        } completionHandler: { [weak panel] in
            panel?.orderOut(nil)
        }
    }

    /// Re-fit the panel to new content, keeping the top-left corner anchored.
    func resizeToContent() {
        guard let panel, panel.isVisible else { return }
        let screen = screenContaining(panel.frame.origin)
        let size = fittingSize(width: PopupLayout.preferredWidth(for: model.state))
        let frame = PopupLayout.resizedKeepingTopLeft(panel.frame, to: size, visible: screen.visibleFrame)
        guard frame != panel.frame else { return }
        NSAnimationContext.runAnimationGroup { context in
            context.duration = Motion.reduceMotion ? 0 : 0.18
            context.timingFunction = CAMediaTimingFunction(name: .easeOut)
            panel.animator().setFrame(frame, display: true)
        }
    }

    // MARK: - Panel

    /// The cap follows the screen the popup opens on, so moving to another display
    /// changes how much is read without scrolling.
    private func applyBodyMaxHeight(for screen: NSScreen) {
        let cap = PopupLayout.bodyMaxHeight(forScreenHeight: screen.visibleFrame.height)
        guard cap != bodyMaxHeight else { return }
        bodyMaxHeight = cap
        if let hosting = panel?.contentView as? NSHostingView<AnyView> {
            hosting.rootView = AnyView(makeRootView())
        }
    }

    private func makeRootView() -> TranslationPopupView {
        TranslationPopupView(
            model: model,
            bodyMaxHeight: bodyMaxHeight,
            onClose: { [weak self] in self?.closeRequested() },
            onOpenAnki: { [weak self] in self?.openAnki?() }
        )
    }

    private func ensurePanel() -> NSPanel {
        if let panel { return panel }
        let hosting = NSHostingView(rootView: AnyView(makeRootView()))
        hosting.translatesAutoresizingMaskIntoConstraints = true

        let panel = NSPanel(
            contentRect: NSRect(x: 0, y: 0, width: PopupLayout.minWidth, height: 200),
            styleMask: [.nonactivatingPanel, .fullSizeContentView, .borderless],
            backing: .buffered,
            defer: false
        )
        panel.contentView = hosting
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.level = .floating
        panel.hidesOnDeactivate = false
        panel.isMovableByWindowBackground = true
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .ignoresCycle]
        panel.delegate = self
        self.panel = panel
        return panel
    }

    private func fittingSize(width: CGFloat) -> CGSize {
        guard let hosting = panel?.contentView else { return CGSize(width: width, height: 220) }
        hosting.setFrameSize(NSSize(width: width, height: hosting.frame.height))
        hosting.layoutSubtreeIfNeeded()
        let height = max(120, min(hosting.fittingSize.height, 720))
        return CGSize(width: width, height: height)
    }

    private func screenContaining(_ point: CGPoint) -> NSScreen {
        NSScreen.screens.first { $0.frame.contains(point) } ?? NSScreen.main ?? NSScreen.screens[0]
    }

    private func closeRequested() {
        hide()
        onClose?()
    }

    // MARK: - Esc

    private func installEscapeMonitor() {
        guard localMonitor == nil else { return }
        localMonitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
            guard event.keyCode == 53 else { return event }   // Esc
            MainActor.assumeIsolated { self?.closeRequested() }
            return nil
        }
    }

    private func removeEscapeMonitor() {
        if let localMonitor { NSEvent.removeMonitor(localMonitor) }
        localMonitor = nil
    }
}
