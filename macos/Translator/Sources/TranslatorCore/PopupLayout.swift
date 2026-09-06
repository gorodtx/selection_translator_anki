import CoreGraphics
import Foundation

/// Geometry for the translation popup: width heuristics ported from the GTK window and
/// placement next to the pointer that never leaves the screen.
public enum PopupLayout {
    public static let minWidth: CGFloat = 340
    public static let maxWidth: CGFloat = 520
    public static let pointerOffset = CGPoint(x: 14, y: -18)
    public static let screenMargin: CGFloat = 12
    /// Header, action bar and padding around the scrolling body.
    public static let chromeHeight: CGFloat = 133

    /// Cap on the scrolling part of the popup.
    ///
    /// A dictionary card with senses, definitions and examples runs past any fixed cap on
    /// every real lookup, so this decides how much is read without scrolling. Half the
    /// screen keeps the popup a popup while using a large display when there is one; the
    /// bounds keep it sane on a laptop and on a 5K panel alike.
    public static func bodyMaxHeight(forScreenHeight height: CGFloat) -> CGFloat {
        min(max(height * 0.5, 360), 640)
    }

    /// Width grows with the longest line the popup has to show, within bounds.
    public static func preferredWidth(for state: ViewState) -> CGFloat {
        var width: CGFloat = 380
        let longestExample = state.examples.map { $0.en.count }.max() ?? 0
        let longestDefinition = state.definitionsItems.map(\.count).max() ?? 0
        let longest = max(state.original.count, state.translationText.count, longestExample, longestDefinition)
        if longest > 70 { width = 430 }
        if longest > 110 { width = 480 }
        if longest > 160 { width = maxWidth }
        return min(max(width, minWidth), maxWidth)
    }

    /// Place `size` near `pointer` (AppKit coordinates, origin bottom-left) inside `visible`.
    ///
    /// Preferred position: top-left corner just below-right of the pointer. When that would
    /// overflow the bottom, the popup flips above the pointer; horizontally it is clamped.
    public static func frame(for size: CGSize, pointer: CGPoint, visible: CGRect) -> CGRect {
        var x = pointer.x + pointerOffset.x
        var top = pointer.y + pointerOffset.y
        let maxX = visible.maxX - screenMargin - size.width
        let minX = visible.minX + screenMargin
        x = min(max(x, minX), max(minX, maxX))

        var bottom = top - size.height
        if bottom < visible.minY + screenMargin {
            // Flip above the pointer.
            bottom = pointer.y - pointerOffset.y
            top = bottom + size.height
            if top > visible.maxY - screenMargin {
                top = visible.maxY - screenMargin
                bottom = top - size.height
            }
        }
        if bottom < visible.minY + screenMargin {
            bottom = visible.minY + screenMargin
        }
        return CGRect(x: x, y: bottom, width: size.width, height: size.height)
    }

    /// Keep the top-left corner fixed when the content height changes.
    public static func resizedKeepingTopLeft(_ frame: CGRect, to size: CGSize, visible: CGRect) -> CGRect {
        var bottom = frame.maxY - size.height
        if bottom < visible.minY + screenMargin {
            bottom = visible.minY + screenMargin
        }
        var x = frame.minX
        let maxX = visible.maxX - screenMargin - size.width
        if x > maxX { x = max(visible.minX + screenMargin, maxX) }
        return CGRect(x: x, y: bottom, width: size.width, height: size.height)
    }
}
