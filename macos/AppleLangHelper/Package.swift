// swift-tools-version:6.2
import PackageDescription

let package = Package(
    name: "AppleLangHelper",
    platforms: [.macOS(.v26)],
    products: [
        .executable(name: "apple-lang-helper", targets: ["AppleLangHelper"]),
    ],
    targets: [
        .executableTarget(
            name: "AppleLangHelper",
            path: "Sources/AppleLangHelper",
            swiftSettings: [.swiftLanguageMode(.v5)],
            linkerSettings: [
                .linkedFramework("CoreServices"),
                .linkedFramework("Translation"),
            ]
        ),
    ]
)
