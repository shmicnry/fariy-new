// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "FairyMacBridge",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "FairyMacBridge", targets: ["FairyMacBridge"])],
    targets: [
        .target(
            name: "FairyMacBridgeCore",
            linkerSettings: [
                .linkedFramework("AppKit"),
                .linkedFramework("ApplicationServices"),
                .linkedFramework("CoreText"),
                .linkedFramework("ImageIO"),
                .linkedFramework("PDFKit"),
                .linkedFramework("Vision"),
            ]
        ),
        .executableTarget(
            name: "FairyMacBridge",
            dependencies: ["FairyMacBridgeCore"]
        ),
        .testTarget(
            name: "FairyMacBridgeCoreTests",
            dependencies: ["FairyMacBridgeCore"]
        ),
    ]
)
