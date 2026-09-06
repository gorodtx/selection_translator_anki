// swift-tools-version:6.2
import PackageDescription

let package = Package(
    name: "Translator",
    platforms: [.macOS(.v26)],
    products: [
        .executable(name: "Translator", targets: ["Translator"]),
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
        .testTarget(
            name: "TranslatorCoreTests",
            dependencies: ["TranslatorCore"],
            swiftSettings: [.swiftLanguageMode(.v5)]
        ),
    ]
)
