// swift-tools-version:6.2
import PackageDescription

let package = Package(
    name: "Translator",
    platforms: [.macOS(.v26)],
    products: [
        .executable(name: "Translator", targets: ["Translator"]),
        // Signed launcher for the login agent, so the background item the user sees in
        // Login Items belongs to this app instead of being an unsigned loose script.
        .executable(name: "TranslatorBackend", targets: ["TranslatorBackend"]),
        .library(name: "TranslatorCore", targets: ["TranslatorCore"]),
    ],
    targets: [
        // Pure logic: wire protocol models, NDJSON framing, hot-key model, popup geometry.
        // No AppKit/SwiftUI so it is unit-testable on the CLT-only toolchain.
        .target(
            name: "TranslatorCore",
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
        .executableTarget(
            name: "Translator",
            dependencies: ["TranslatorCore"],
            swiftSettings: [.swiftLanguageMode(.v5)],
            linkerSettings: [
                .linkedFramework("AppKit"),
                .linkedFramework("SwiftUI"),
                .linkedFramework("Carbon"),
                .linkedFramework("ApplicationServices"),
                .linkedFramework("Translation"),
            ]
        ),
        .executableTarget(
            name: "TranslatorBackend",
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
        .testTarget(
            name: "TranslatorCoreTests",
            dependencies: ["TranslatorCore"],
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
    ]
)
