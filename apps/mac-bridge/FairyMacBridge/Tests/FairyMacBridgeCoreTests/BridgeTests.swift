import AppKit
import ApplicationServices
import CoreText
import FairyMacBridgeCore
import Foundation
import PDFKit
import XCTest

final class BridgeTests: XCTestCase {
    private func temporaryURL(extension pathExtension: String) -> URL {
        URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("fairy-bridge-\(UUID().uuidString)")
            .appendingPathExtension(pathExtension)
    }

    private func renderedImage(text: String) throws -> CGImage {
        let size = NSSize(width: 900, height: 240)
        let image = NSImage(size: size)
        image.lockFocus()
        NSColor.white.setFill()
        NSBezierPath(rect: NSRect(origin: .zero, size: size)).fill()
        let attributes: [NSAttributedString.Key: Any] = [
            .font: NSFont.boldSystemFont(ofSize: 72),
            .foregroundColor: NSColor.black,
        ]
        (text as NSString).draw(at: NSPoint(x: 40, y: 80), withAttributes: attributes)
        image.unlockFocus()
        return try XCTUnwrap(
            image.cgImage(forProposedRect: nil, context: nil, hints: nil)
        )
    }

    private func renderedPDF(pageTexts: [String]) throws -> URL {
        let url = temporaryURL(extension: "pdf")
        let data = NSMutableData()
        let consumer = try XCTUnwrap(CGDataConsumer(data: data as CFMutableData))
        var mediaBox = CGRect(x: 0, y: 0, width: 612, height: 792)
        let context = try XCTUnwrap(
            CGContext(consumer: consumer, mediaBox: &mediaBox, nil)
        )
        for text in pageTexts {
            context.beginPDFPage(nil)
            context.setFillColor(CGColor(gray: 1, alpha: 1))
            context.fill(mediaBox)
            let attributed = NSAttributedString(
                string: text,
                attributes: [
                    .font: NSFont.boldSystemFont(ofSize: 48),
                    .foregroundColor: NSColor.black,
                ]
            )
            let framesetter = CTFramesetterCreateWithAttributedString(attributed)
            let path = CGPath(
                rect: CGRect(x: 50, y: 600, width: 512, height: 140),
                transform: nil
            )
            let frame = CTFramesetterCreateFrame(
                framesetter, CFRangeMake(0, 0), path, nil
            )
            CTFrameDraw(frame, context)
            context.endPDFPage()
        }
        context.closePDF()
        try data.write(to: url)
        return url
    }

    func testRecognizeTextRejectsMissingFile() {
        let path = temporaryURL(extension: "png").path
        XCTAssertThrowsError(try recognizeText(path: path)) { error in
            XCTAssertEqual(error.localizedDescription, "ocr_image_unreadable")
        }
    }

    func testRecognizePDFRejectsGarbageFile() throws {
        let url = temporaryURL(extension: "pdf")
        try Data("this is not a pdf".utf8).write(to: url)
        defer { try? FileManager.default.removeItem(at: url) }
        XCTAssertThrowsError(try recognizePDF(path: url.path)) { error in
            XCTAssertEqual(error.localizedDescription, "ocr_pdf_unreadable")
        }
    }

    func testAccessibilityTreeRespectsDepthAndNodeLimits() {
        let root = AXUIElementCreateApplication(
            ProcessInfo.processInfo.processIdentifier
        )
        let depthZero = accessibilityTree(root: root, maxDepth: 0, maxNodes: 10)
        XCTAssertEqual(depthZero.count, 1)
        XCTAssertEqual(depthZero.first?["depth"] as? Int, 0)

        let capped = accessibilityTree(root: root, maxDepth: 5, maxNodes: 1)
        XCTAssertLessThanOrEqual(capped.count, 1)

        let full = accessibilityTree(root: root, maxDepth: 5, maxNodes: 250)
        XCTAssertLessThanOrEqual(full.count, 250)
        XCTAssertGreaterThanOrEqual(full.count, 1)
        for row in full {
            let depth = row["depth"] as? Int ?? -1
            XCTAssertTrue((0...5).contains(depth))
        }
    }

    func testRecognizeImageReadsRenderedText() throws {
        let image = try renderedImage(text: "FAIRY 12345")
        let result = try recognizeImage(image)
        XCTAssertEqual(result["method"] as? String, "macos_vision_ocr")
        let lines = try XCTUnwrap(result["lines"] as? [[String: Any]])
        XCTAssertEqual(result["line_count"] as? Int, lines.count)
        let joined = lines.compactMap { $0["text"] as? String }
            .joined(separator: " ")
        XCTAssertTrue(joined.contains("12345"), "OCR output: \(joined)")
    }

    func testRecognizeTextReadsImageFileFromDisk() throws {
        let image = try renderedImage(text: "FAIRY 12345")
        let url = temporaryURL(extension: "png")
        let representation = try XCTUnwrap(
            NSBitmapImageRep(cgImage: image)
                .representation(using: .png, properties: [:])
        )
        try representation.write(to: url)
        defer { try? FileManager.default.removeItem(at: url) }
        let result = try recognizeText(path: url.path)
        let lines = try XCTUnwrap(result["lines"] as? [[String: Any]])
        let joined = lines.compactMap { $0["text"] as? String }
            .joined(separator: " ")
        XCTAssertTrue(joined.contains("12345"), "OCR output: \(joined)")
    }

    func testRecognizePDFReadsPagesAndHonorsPageLimit() throws {
        let url = try renderedPDF(pageTexts: ["PAGE ONE 67890", "PAGE TWO 67890"])
        defer { try? FileManager.default.removeItem(at: url) }
        let full = try recognizePDF(path: url.path)
        XCTAssertEqual(full["method"] as? String, "macos_vision_pdf_ocr")
        XCTAssertEqual(full["page_count"] as? Int, 2)
        let pages = try XCTUnwrap(full["pages"] as? [[String: Any]])
        XCTAssertEqual(pages.first?["page"] as? Int, 1)
        let firstText = pages.first?["text"] as? String ?? ""
        XCTAssertTrue(firstText.contains("67890"), "OCR output: \(firstText)")

        let limited = try recognizePDF(path: url.path, maxPages: 1)
        XCTAssertEqual(limited["page_count"] as? Int, 1)
    }
}
