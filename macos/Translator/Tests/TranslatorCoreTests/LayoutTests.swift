import CoreGraphics
import Foundation
import Testing
@testable import TranslatorCore

@Suite struct KeyComboTests {
    @Test func defaultIsOptionCommandT() {
        let combo = KeyCombo.defaultCombo
        #expect(combo.displayString == "⌥⌘T")
        #expect(combo.isUsable)
    }

    @Test func modifiersRenderInCanonicalOrder() {
        let combo = KeyCombo(
            keyCode: 49,
            modifiers: KeyCombo.commandMask | KeyCombo.shiftMask | KeyCombo.optionMask | KeyCombo.controlMask
        )
        #expect(combo.displayString == "⌃⌥⇧⌘Space")
    }

    @Test func shiftAloneIsNotUsable() {
        #expect(!KeyCombo(keyCode: 17, modifiers: KeyCombo.shiftMask).isUsable)
        #expect(!KeyCombo(keyCode: 17, modifiers: 0).isUsable)
        #expect(KeyCombo(keyCode: 17, modifiers: KeyCombo.controlMask).isUsable)
    }

    @Test func unknownModifierBitsAreDropped() {
        let combo = KeyCombo(keyCode: 17, modifiers: KeyCombo.commandMask | 0x4000)
        #expect(combo.modifiers == KeyCombo.commandMask)
    }

    @Test func roundTripsThroughStorage() throws {
        let combo = KeyCombo(keyCode: 46, modifiers: KeyCombo.controlMask | KeyCombo.optionMask)
        let restored = try #require(KeyCombo(storageString: combo.storageString))
        #expect(restored == combo)
        #expect(KeyCombo(storageString: "garbage") == nil)
        #expect(KeyCombo(storageString: "17:") == nil)
    }
}

@Suite struct PopupLayoutTests {
    private let screen = CGRect(x: 0, y: 0, width: 1440, height: 900)

    @Test func widthGrowsWithContent() {
        let short = ViewState(original: "bank", translation: "берег")
        let long = ViewState(
            original: String(repeating: "word ", count: 40),
            translation: String(repeating: "слово ", count: 40)
        )
        #expect(PopupLayout.preferredWidth(for: short) < PopupLayout.preferredWidth(for: long))
        #expect(PopupLayout.preferredWidth(for: long) == PopupLayout.maxWidth)
        #expect(PopupLayout.preferredWidth(for: short) >= PopupLayout.minWidth)
    }

    @Test func widthAlsoConsidersExamplesAndDefinitions() {
        let base = ViewState(original: "run", translation: "бежать")
        var wide = base
        wide.examples = [ExampleItem(en: String(repeating: "x", count: 200))]
        #expect(PopupLayout.preferredWidth(for: wide) > PopupLayout.preferredWidth(for: base))
        var withDefs = base
        withDefs.definitionsItems = [String(repeating: "y", count: 130)]
        #expect(PopupLayout.preferredWidth(for: withDefs) > PopupLayout.preferredWidth(for: base))
    }

    @Test func popupSitsBelowRightOfPointer() {
        let frame = PopupLayout.frame(
            for: CGSize(width: 380, height: 300),
            pointer: CGPoint(x: 600, y: 700),
            visible: screen
        )
        #expect(frame.minX == 614)
        #expect(frame.maxY == 682)
        #expect(screen.contains(frame))
    }

    @Test func popupStaysOnScreenNearRightEdge() {
        let frame = PopupLayout.frame(
            for: CGSize(width: 500, height: 300),
            pointer: CGPoint(x: 1430, y: 700),
            visible: screen
        )
        #expect(frame.maxX <= screen.maxX - PopupLayout.screenMargin)
        #expect(frame.minX >= screen.minX)
    }

    @Test func popupFlipsAboveWhenItWouldOverflowBottom() {
        let frame = PopupLayout.frame(
            for: CGSize(width: 380, height: 400),
            pointer: CGPoint(x: 400, y: 120),
            visible: screen
        )
        #expect(frame.minY >= screen.minY + PopupLayout.screenMargin)
        #expect(frame.maxY <= screen.maxY - PopupLayout.screenMargin)
    }

    @Test func tallerContentKeepsTopLeftAnchored() {
        let original = CGRect(x: 300, y: 500, width: 380, height: 200)
        let grown = PopupLayout.resizedKeepingTopLeft(original, to: CGSize(width: 380, height: 320), visible: screen)
        #expect(grown.maxY == original.maxY)
        #expect(grown.minX == original.minX)
        #expect(grown.height == 320)
    }

    @Test func growthClampsAtScreenBottom() {
        let original = CGRect(x: 300, y: 40, width: 380, height: 120)
        let grown = PopupLayout.resizedKeepingTopLeft(original, to: CGSize(width: 380, height: 400), visible: screen)
        #expect(grown.minY >= screen.minY + PopupLayout.screenMargin)
    }

    @Test func widthGrowthPullsPanelBackOnScreen() {
        let original = CGRect(x: 1200, y: 400, width: 340, height: 200)
        let grown = PopupLayout.resizedKeepingTopLeft(original, to: CGSize(width: 520, height: 200), visible: screen)
        #expect(grown.maxX <= screen.maxX - PopupLayout.screenMargin)
    }
}
