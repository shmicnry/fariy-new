import AppKit
import ApplicationServices
import Foundation
import ImageIO
import PDFKit
import Vision

public struct BridgeError: LocalizedError {
    public let errorDescription: String?

    public init(errorDescription: String?) {
        self.errorDescription = errorDescription
    }
}

public func writeJSON(_ object: Any) throws {
    let data = try JSONSerialization.data(
        withJSONObject: object,
        options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
    )
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
}

public func tccStatus() -> [String: Any] {
    [
        "accessibility": AXIsProcessTrusted(),
        "screen_recording": CGPreflightScreenCaptureAccess(),
        "probed": true,
    ]
}

public func runningApplications() -> [[String: Any]] {
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

public func application(for bundleID: String?) -> NSRunningApplication? {
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

public func accessibilityTree(
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

public func recognizeImage(_ image: CGImage, includeLines: Bool = true) throws -> [String: Any] {
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
    var result: [String: Any] = [
        "method": "macos_vision_ocr",
        "line_count": lines.count,
    ]
    if includeLines {
        result["lines"] = lines
    } else {
        result["text"] = lines.compactMap { $0["text"] as? String }.joined(separator: "\n")
    }
    return result
}

public func recognizeText(path: String) throws -> [String: Any] {
    let url = URL(fileURLWithPath: path)
    guard url.isFileURL,
          let source = CGImageSourceCreateWithURL(url as CFURL, nil),
          let image = CGImageSourceCreateImageAtIndex(source, 0, nil) else {
        throw BridgeError(errorDescription: "ocr_image_unreadable")
    }
    return try recognizeImage(image)
}

public func recognizePDF(path: String, maxPages: Int = 100) throws -> [String: Any] {
    let url = URL(fileURLWithPath: path)
    guard let document = PDFDocument(url: url), document.pageCount > 0 else {
        throw BridgeError(errorDescription: "ocr_pdf_unreadable")
    }
    var pages: [[String: Any]] = []
    var totalCharacters = 0
    for index in 0..<min(document.pageCount, maxPages) {
        guard let page = document.page(at: index) else { continue }
        let bounds = page.bounds(for: .mediaBox)
        let scale = min(2.0, 2000.0 / max(bounds.width, bounds.height, 1))
        let size = NSSize(
            width: max(1, bounds.width * scale),
            height: max(1, bounds.height * scale)
        )
        let image = NSImage(size: size)
        image.lockFocus()
        NSColor.white.setFill()
        NSBezierPath(rect: NSRect(origin: .zero, size: size)).fill()
        if let context = NSGraphicsContext.current?.cgContext {
            context.saveGState()
            context.scaleBy(x: scale, y: scale)
            page.draw(with: .mediaBox, to: context)
            context.restoreGState()
        }
        image.unlockFocus()
        guard let cgImage = image.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
            continue
        }
        let recognized = try recognizeImage(cgImage, includeLines: false)
        let text = (recognized["text"] as? String ?? "").trimmingCharacters(
            in: .whitespacesAndNewlines
        )
        totalCharacters += text.count
        if totalCharacters > 256_000 {
            throw BridgeError(errorDescription: "ocr_pdf_text_too_large")
        }
        pages.append([
            "page": index + 1,
            "text": text,
            "line_count": recognized["line_count"] ?? 0,
        ])
    }
    return [
        "method": "macos_vision_pdf_ocr",
        "page_count": pages.count,
        "pages": pages,
    ]
}
