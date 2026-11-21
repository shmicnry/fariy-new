import ApplicationServices
import FairyMacBridgeCore
import Foundation

func main() throws {
    let arguments = CommandLine.arguments
    let command = arguments.count > 1 ? arguments[1] : "status"
    switch command {
    case "status":
        try writeJSON([
            "bridge": "fairy-mac-bridge",
            "version": "0.1.1",
            "read_only": true,
            "input_injection": false,
            "screen_capture_content": false,
            "tcc": tccStatus(),
            "applications": runningApplications(),
        ])
    case "applications":
        try writeJSON(["applications": runningApplications()])
    case "ax-tree":
        guard AXIsProcessTrusted() else {
            throw BridgeError(
                errorDescription: "accessibility_permission_required"
            )
        }
        let bundleID = arguments.count > 2 ? arguments[2] : nil
        guard let application = application(for: bundleID) else {
            throw BridgeError(errorDescription: "application_not_running")
        }
        let root = AXUIElementCreateApplication(application.processIdentifier)
        try writeJSON([
            "application": application.localizedName ?? "",
            "bundle_id": application.bundleIdentifier ?? "",
            "pid": Int(application.processIdentifier),
            "max_depth": 5,
            "max_nodes": 250,
            "nodes": accessibilityTree(root: root, maxDepth: 5, maxNodes: 250),
        ])
    case "ocr":
        guard arguments.count > 2 else {
            throw BridgeError(errorDescription: "ocr_path_required")
        }
        try writeJSON(try recognizeText(path: arguments[2]))
    case "ocr-pdf":
        guard arguments.count > 2 else {
            throw BridgeError(errorDescription: "ocr_pdf_path_required")
        }
        try writeJSON(try recognizePDF(path: arguments[2]))
    default:
        throw BridgeError(
            errorDescription: "usage: FairyMacBridge status|applications|ax-tree [bundle-id]|ocr <image>|ocr-pdf <pdf>"
        )
    }
}

do {
    try main()
} catch {
    FileHandle.standardError.write(Data("\(error.localizedDescription)\n".utf8))
    exit(1)
}
