// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "FairyApp",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [.executable(name: "FairyApp", targets: ["FairyApp"])],
    targets: [
        .executableTarget(
            name: "FairyApp",
            linkerSettings: [.linkedFramework("Security")]
        )
    ]
)
