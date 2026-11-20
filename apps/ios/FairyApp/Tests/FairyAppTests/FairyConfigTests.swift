import XCTest
@testable import FairyApp

final class FairyConfigTests: XCTestCase {
    func testDecodesBackendConfigWithoutLosingPetPreference() throws {
        let data = Data(
            """
            {
              "revision": 7,
              "daily_minutes": 45,
              "pet_enabled": true,
              "mac_execute": false,
              "mac_file_write": false,
              "autonomous_paid": false,
              "mac_allowed_apps": ["com.apple.TextEdit"],
              "mac_allowed_paths": ["/Users/example/Documents/Fairy"],
              "autonomy_enabled": true,
              "autonomy_daily_minutes": 30,
              "autonomy_daily_items": 10,
              "source_refresh_enabled": false,
              "source_refresh_interval_hours": 24,
              "source_refresh_daily_limit": 5,
              "source_allowed_hosts": ["example.com"]
            }
            """.utf8
        )
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase

        let config = try decoder.decode(FairyConfig.self, from: data)

        XCTAssertEqual(config.revision, 7)
        XCTAssertTrue(config.petEnabled)
        XCTAssertFalse(config.macExecute)
        XCTAssertEqual(config.macAllowedApps, ["com.apple.TextEdit"])
        XCTAssertEqual(config.macAllowedPaths, ["/Users/example/Documents/Fairy"])
        XCTAssertTrue(config.autonomyEnabled)
        XCTAssertEqual(config.sourceAllowedHosts, ["example.com"])
    }
}
