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
    /// Tracking is size-specific: tighter as text grows, near zero for body.
    static let popupHeadword = Font.system(size: 22, weight: .semibold, design: .rounded)
    static let popupTranslation = Font.system(size: 17, weight: .medium)
    static let sectionLabel = Font.system(size: 11, weight: .semibold).width(.expanded)
    static let bodyText = Font.system(size: 13)
    static let secondaryText = Font.system(size: 12)
    static let monoIPA = Font.system(size: 12, weight: .regular, design: .monospaced)
}

/// A translucent surface. Liquid Glass when the system offers it and the user allows
/// transparency; an opaque material otherwise, so Reduce Transparency stays legible.
struct GlassSurface: ViewModifier {
    var radius: CGFloat = Layout.cardRadius
    var interactive = false
    var tint: Color?

    @Environment(\.accessibilityReduceTransparency) private var reduceTransparency

    func body(content: Content) -> some View {
        if reduceTransparency {
            content
                .background(.background, in: .rect(cornerRadius: radius))
                .overlay(
                    RoundedRectangle(cornerRadius: radius)
                        .strokeBorder(Color.primary.opacity(0.18), lineWidth: 1)
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

extension View {
    /// Primary glass surface (panels, cards).
    func glassSurface(radius: CGFloat = Layout.cardRadius, interactive: Bool = false, tint: Color? = nil) -> some View {
        modifier(GlassSurface(radius: radius, interactive: interactive, tint: tint))
    }

    /// Inner surface for a section inside a glass panel. Never a second translucent layer:
    /// on glass it is a low-opacity fill, which keeps text legible.
    func innerSurface(radius: CGFloat = Layout.innerRadius) -> some View {
        background(Color.primary.opacity(0.055), in: .rect(cornerRadius: radius))
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
