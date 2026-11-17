// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "FairyMacBridge",
    platforms: [.macOS(.v14)],
    products: [.executable(name: "FairyMacBridge", targets: ["FairyMacBridge"])],
    targets: [
        .executableTarget(
            name: "FairyMacBridge",
            linkerSettings: [
                .linkedFramework("AppKit"),
                .linkedFramework("ApplicationServices"),
                .linkedFramework("ImageIO"),
                .linkedFramework("Vision"),
            ]
        )
    ]
)
