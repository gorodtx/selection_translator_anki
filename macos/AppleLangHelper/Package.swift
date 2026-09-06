// swift-tools-version:5.9
import PackageDescription

let package = Package(
    name: "AppleLangHelper",
    platforms: [.macOS(.v14)],
    products: [
        .executable(name: "apple-lang-helper", targets: ["AppleLangHelper"]),
        .library(name: "AppleLangHelperCore", targets: ["AppleLangHelperCore"]),
    ],
    targets: [
        .target(
            name: "AppleLangHelperCore",
            linkerSettings: [
                .linkedFramework("CoreServices"),
                .linkedFramework("Translation"),
            ]
        ),
        .executableTarget(
            name: "AppleLangHelper",
            dependencies: ["AppleLangHelperCore"]
        ),
        .testTarget(
            name: "AppleLangHelperCoreTests",
            dependencies: ["AppleLangHelperCore"]
        ),
    ]
)
