import Foundation

/// How a surface should be drawn for the accessibility settings in force.
///
/// The two environment keys that decide this (`accessibilityReduceTransparency` and
/// `colorSchemeContrast`) are read-only: a test cannot inject them, and changing the
/// real settings to check a branch is not something a test may do. So the decision lives
/// here as a pure function and the view only applies what it returns.
public enum SurfaceStyle: Equatable, Sendable {
    /// Liquid Glass, the default look.
    case glass
    /// An opaque ground with a border of the given opacity.
    case opaque(border: Double)

    public var isGlass: Bool { self == .glass }
}

/// Values for a section drawn inside a panel.
public struct InnerSurfaceStyle: Equatable, Sendable {
    public let fill: Double
    public let border: Double?

    public init(fill: Double, border: Double?) {
        self.fill = fill
        self.border = border
    }
}

public enum SurfaceStyleResolver {
    /// Glass is wrong under either setting.
    ///
    /// Reduce Transparency asks for no translucency at all. Increase Contrast asks for a
    /// ground that text is guaranteed to read against and an edge that is actually
    /// visible, which a blurred surface over arbitrary content cannot promise — so both
    /// take the opaque path, and increased contrast additionally deepens the border.
    public static func panel(
        reduceTransparency: Bool,
        increasedContrast: Bool
    ) -> SurfaceStyle {
        guard reduceTransparency || increasedContrast else { return .glass }
        return .opaque(border: increasedContrast ? 0.45 : 0.18)
    }

    /// A section inside a panel is never a second translucent layer; it is a faint fill.
    ///
    /// Faint is right until more contrast is asked for, at which point the section has to
    /// be told apart from the panel it sits on, so the fill deepens and gains a border.
    public static func inner(increasedContrast: Bool) -> InnerSurfaceStyle {
        increasedContrast
            ? InnerSurfaceStyle(fill: 0.12, border: 0.45)
            : InnerSurfaceStyle(fill: 0.055, border: nil)
    }
}
