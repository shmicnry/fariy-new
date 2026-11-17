import AppKit
import ApplicationServices
import Foundation
import ImageIO
import Vision

struct BridgeError: LocalizedError {
    let errorDescription: String?
}

func writeJSON(_ object: Any) throws {
    let data = try JSONSerialization.data(
        withJSONObject: object,
        options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
    )
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
}

func tccStatus() -> [String: Any] {
    [
        "accessibility": AXIsProcessTrusted(),
        "screen_recording": CGPreflightScreenCaptureAccess(),
        "probed": true,
    ]
}

func runningApplications() -> [[String: Any]] {
    NSWorkspace.shared.runningApplications
        .filter { $0.activationPolicy != .prohibited }
        .sorted {
            ($0.localizedName ?? "").localizedCaseInsensitiveCompare($1.localizedName ?? "")
                == .orderedAscending
        }
        .prefix(200)
        .map { application in
            [
                "name": application.localizedName ?? "",
                "bundle_id": application.bundleIdentifier ?? "",
                "pid": Int(application.processIdentifier),
                "active": application.isActive,
                "hidden": application.isHidden,
            ]
        }
}

func application(for bundleID: String?) -> NSRunningApplication? {
    let candidates = NSWorkspace.shared.runningApplications.filter {
        $0.activationPolicy != .prohibited
    }
    if let bundleID, !bundleID.isEmpty {
        return candidates.first { $0.bundleIdentifier == bundleID }
    }
    return NSWorkspace.shared.frontmostApplication
}

func attribute(_ element: AXUIElement, _ name: CFString) -> AnyObject? {
    var value: CFTypeRef?
    let result = AXUIElementCopyAttributeValue(element, name, &value)
    return result == .success ? value : nil
}

func textValue(_ value: AnyObject?) -> String? {
    guard let value else { return nil }
    if let text = value as? String {
        return text
    }
    if CFGetTypeID(value) == AXValueGetTypeID() {
        return nil
    }
    return nil
}

func children(_ element: AXUIElement) -> [AXUIElement] {
    guard let value = attribute(element, kAXChildrenAttribute as CFString) else {
        return []
    }
    return value as? [AXUIElement] ?? []
}

func accessibilityTree(
    root: AXUIElement,
    maxDepth: Int,
    maxNodes: Int
) -> [[String: Any]] {
    var output: [[String: Any]] = []
    var queue: [(AXUIElement, Int)] = [(root, 0)]
    while !queue.isEmpty && output.count < maxNodes {
        let (element, depth) = queue.removeFirst()
        var row: [String: Any] = ["depth": depth]
        if let role = textValue(attribute(element, kAXRoleAttribute as CFString)) {
            row["role"] = role
        }
        if let subrole = textValue(attribute(element, kAXSubroleAttribute as CFString)) {
            row["subrole"] = subrole
        }
        if let title = textValue(attribute(element, kAXTitleAttribute as CFString)) {
            row["title"] = String(title.prefix(500))
        }
        if let description = textValue(attribute(element, kAXDescriptionAttribute as CFString)) {
            row["description"] = String(description.prefix(500))
        }
        if let value = textValue(attribute(element, kAXValueAttribute as CFString)) {
            row["value"] = String(value.prefix(500))
        }
        row["enabled"] = attribute(element, kAXEnabledAttribute as CFString) as? Bool
        output.append(row)
        if depth < maxDepth {
            for child in children(element).prefix(100) {
                queue.append((child, depth + 1))
            }
        }
    }
    return output
}

func recognizeText(path: String) throws -> [String: Any] {
    let url = URL(fileURLWithPath: path)
    guard url.isFileURL,
          let source = CGImageSourceCreateWithURL(url as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        throw BridgeError(errorDescription: "ocr_image_unreadable")
    }
    let request = VNRecognizeTextRequest()
    request.recognitionLevel = .accurate
    request.usesLanguageCorrection = true
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    let handler = VNImageRequestHandler(cgImage: image)
    try handler.perform([request])
    let observations = request.results ?? []
    let lines = observations.prefix(500).compactMap { observation -> [String: Any]? in
        guard let candidate = observation.topCandidates(1).first else { return nil }
        let box = observation.boundingBox
        return [
            "text": String(candidate.string.prefix(2000)),
            "confidence": candidate.confidence,
            "x": box.origin.x,
            "y": box.origin.y,
            "width": box.size.width,
            "height": box.size.height,
        ]
    }
    return [
        "method": "macos_vision_ocr",
        "line_count": lines.count,
        "lines": lines,
    ]
}

func main() throws {
    let arguments = CommandLine.arguments
    let command = arguments.count > 1 ? arguments[1] : "status"
    switch command {
    case "status":
        try writeJSON([
            "bridge": "fairy-mac-bridge",
            "version": "0.1.0",
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
    default:
        throw BridgeError(
            errorDescription: "usage: FairyMacBridge status|applications|ax-tree [bundle-id]|ocr <path>"
        )
    }
}

do {
    try main()
} catch {
    FileHandle.standardError.write(Data("\(error.localizedDescription)\n".utf8))
    exit(1)
}
