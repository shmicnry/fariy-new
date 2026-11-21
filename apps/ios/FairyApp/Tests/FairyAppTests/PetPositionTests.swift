#if os(macOS)
import XCTest
@testable import FairyApp

@MainActor
final class PetPositionTests: XCTestCase {
    private let frame = NSRect(x: 0, y: 25, width: 1440, height: 875)
    private let size = NSSize(width: 220, height: 270)

    func testDefaultOriginSitsInsideVisibleFrame() {
        let origin = DesktopPetController.origin(
            normalizedX: nil, normalizedY: nil, in: frame, size: size
        )
        XCTAssertGreaterThanOrEqual(origin.x, frame.minX)
        XCTAssertGreaterThanOrEqual(origin.y, frame.minY)
        XCTAssertLessThanOrEqual(origin.x + size.width, frame.maxX)
        XCTAssertLessThanOrEqual(origin.y + size.height, frame.maxY)
    }

    func testSavedFractionRestoresProportionallyOnSmallerScreen() {
        let smaller = NSRect(x: 0, y: 25, width: 1024, height: 640)
        let origin = DesktopPetController.origin(
            normalizedX: 0.5, normalizedY: 0.5, in: smaller, size: size
        )
        XCTAssertEqual(origin.x, smaller.minX + 0.5 * smaller.width, accuracy: 0.001)
        XCTAssertEqual(origin.y, smaller.minY + 0.5 * smaller.height, accuracy: 0.001)
    }

    func testOffscreenPositionClampsBackIntoVisibleFrame() {
        let origin = DesktopPetController.origin(
            normalizedX: 1.4, normalizedY: -0.3, in: frame, size: size
        )
        XCTAssertEqual(origin.x, frame.maxX - size.width, accuracy: 0.001)
        XCTAssertEqual(origin.y, frame.minY, accuracy: 0.001)
    }
}
#endif
