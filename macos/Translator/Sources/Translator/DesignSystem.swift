import SwiftUI
import TranslatorCore

/// Motion tokens. Springs everywhere, because every one of these can be interrupted by the
/// next event (a partial arriving mid-animation, the panel closing mid-open).
/// Reduce Motion collapses them to a short cross-fade instead of removing feedback.
enum Motion {
    /// Critically damped, quick: the default for anything that just changes value.
    static var stateChange: Animation {
        reduceMotion ? .easeOut(duration: 0.15) : .spring(response: 0.34, dampingFraction: 1.0)
    }

    /// Popup arrival — a hair of overshoot, because it follows a physical gesture (hot key
    /// pressed on a selection) and should read as thrown onto the screen.
    static var popupAppear: Animation {
        reduceMotion ? .easeOut(duration: 0.14) : .spring(response: 0.32, dampingFraction: 0.82)
    }

    static var popupDismiss: Animation {
        reduceMotion ? .easeIn(duration: 0.12) : .spring(response: 0.24, dampingFraction: 1.0)
    }

    /// Rows and list content: no bounce, they are not thrown.
    static var content: Animation {
        reduceMotion ? .easeOut(duration: 0.15) : .spring(response: 0.4, dampingFraction: 1.0)
    }

    static var reduceMotion: Bool {
        NSWorkspace.shared.accessibilityDisplayShouldReduceMotion
    }
}

/// Layout and type tokens. Spacing is a 4-pt scale; type sizes follow the system stack so
/// Dynamic Type keeps working.
enum Layout {
    static let gutter: CGFloat = 16
    static let sectionGap: CGFloat = 14
    static let rowGap: CGFloat = 8
    static let cardRadius: CGFloat = 22

    static let innerRadius: CGFloat = 14
    static let chipRadius: CGFloat = 9
}

extension Font {
    /// Tokens name their role through a text style instead of a point size. At the
    /// default setting the styles measure exactly what the fixed sizes used to be here —
    /// title 22, title2 17, title3 15, body 13, callout 12, subheadline 11, footnote 10 —
    /// so this changed nothing on screen.
    ///
    /// It does not buy Dynamic Type: measured on macOS 26, `dynamicTypeSize` and
    /// `ScaledMetric` are inert and `NSFont.preferredFont(forTextStyle:)` returns fixed
    /// sizes, because macOS has no system text-size control. What it buys is that the
    /// hierarchy is stated rather than encoded in numbers, and that the sizes come from
    /// the platform instead of from us.
    ///
    /// Tracking stays size-specific: tighter as text grows, near zero for body.
    static let popupHeadword = Font.system(.title, design: .rounded).weight(.semibold)
    static let popupTranslation = Font.system(.title2).weight(.medium)
    static let sectionLabel = Font.system(.subheadline).weight(.semibold).width(.expanded)
    static let bodyText = Font.system(.body)
    static let secondaryText = Font.system(.callout)
    static let monoIPA = Font.system(.callout, design: .monospaced)

    /// Sheet and window titles, one step below the popup headword.
    static let sheetTitle = Font.system(.title2).weight(.semibold)
    /// Buttons and segmented labels.
    static let controlLabel = Font.system(.callout).weight(.medium)
    /// Field labels, captions and secondary rows.
    static let captionText = Font.system(.subheadline)
    static let captionEmphasis = Font.system(.subheadline).weight(.semibold)
    /// Counters and badges that sit inside a chip.
    static let badgeText = Font.system(.footnote, design: .rounded).weight(.bold)
    static let badgePlain = Font.system(.footnote)
    /// Paths and other monospaced detail.
    static let monoDetail = Font.system(.footnote, design: .monospaced)
    /// The smallest tag we use, the BrE/AmE marker beside a transcription. There is no
    /// 9 pt text style, so it takes the smallest one: one point larger than before.
    static let dialectTag = Font.system(.caption2).weight(.bold)
    /// Prominent action label, e.g. the primary button in Settings.
    static let actionLabel = Font.system(.body, design: .rounded).weight(.medium)
}

/// A translucent surface. Liquid Glass when the system offers it and the user allows
/// both transparency and normal contrast; an opaque material with a defined border
/// otherwise, so Reduce Transparency and Increase Contrast both stay legible.
struct GlassSurface: ViewModifier {
    var radius: CGFloat = Layout.cardRadius
    var interactive = false
    var tint: Color?

    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
    @Environment(\.colorSchemeContrast) private var contrast

    func body(content: Content) -> some View {
        // Which look applies is decided by SurfaceStyleResolver, where it is under test:
        // the two environment keys are read-only, so the branch cannot be checked here.
        let style = SurfaceStyleResolver.panel(
            reduceTransparency: reduceTransparency,
            increasedContrast: contrast == .increased
        )
        if case let .opaque(border) = style {
            content
                .background(.background, in: .rect(cornerRadius: radius))
                .overlay(
                    RoundedRectangle(cornerRadius: radius)
                        .strokeBorder(Color.primary.opacity(border), lineWidth: 1)
                )
        } else {
            content.glassEffect(glass, in: .rect(cornerRadius: radius))
        }
    }

    private var glass: Glass {
        var value = Glass.regular
        if let tint { value = value.tint(tint) }
        if interactive { value = value.interactive() }
        return value
    }
}

/// Inner surface for a section inside a glass panel. Never a second translucent layer:
/// on glass it is a low-opacity fill, which keeps text legible.
///
/// A 5.5% fill is deliberately near-invisible, which is right until the user asks for
/// more contrast — then the section has to be told apart from the panel it sits on, so
/// the fill deepens and gains a defined border.
struct InnerSurface: ViewModifier {
    @Environment(\.colorSchemeContrast) private var contrast
    var radius: CGFloat = Layout.innerRadius

    func body(content: Content) -> some View {
        let style = SurfaceStyleResolver.inner(increasedContrast: contrast == .increased)
        content
            .background(Color.primary.opacity(style.fill), in: .rect(cornerRadius: radius))
            .overlay {
                if let border = style.border {
                    RoundedRectangle(cornerRadius: radius)
                        .strokeBorder(Color.primary.opacity(border), lineWidth: 1)
                }
            }
    }
}

extension View {
    /// Primary glass surface (panels, cards).
    func glassSurface(radius: CGFloat = Layout.cardRadius, interactive: Bool = false, tint: Color? = nil) -> some View {
        modifier(GlassSurface(radius: radius, interactive: interactive, tint: tint))
    }

    func innerSurface(radius: CGFloat = Layout.innerRadius) -> some View {
        modifier(InnerSurface(radius: radius))
    }
}

/// Small uppercase caption that titles a section without competing with content.
struct SectionLabel: View {
    let text: String
    var accessory: AnyView?

    init(_ text: String) {
        self.text = text
        self.accessory = nil
    }

    init<Accessory: View>(_ text: String, @ViewBuilder accessory: () -> Accessory) {
        self.text = text
        self.accessory = AnyView(accessory())
    }

    var body: some View {
        HStack(spacing: 6) {
            Text(text.uppercased())
                .font(.sectionLabel)
                .tracking(0.6)
                .foregroundStyle(.secondary)
            Spacer(minLength: 4)
            accessory
        }
    }
}

extension NotificationLevel {
    var tint: Color {
        switch self {
        case .success: return .green
        case .info: return .accentColor
        case .warning: return .orange
        case .error: return .red
        }
    }

    var symbol: String {
        switch self {
        case .success: return "checkmark.circle.fill"
        case .info: return "info.circle.fill"
        case .warning: return "exclamationmark.triangle.fill"
        case .error: return "xmark.octagon.fill"
        }
    }
}
