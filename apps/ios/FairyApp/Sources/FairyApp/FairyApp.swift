import SwiftUI

@main
struct FairyDesktopApplication: App {
    @StateObject private var model = FairyModel()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(model)
        }
        #if os(macOS)
        .windowStyle(.titleBar)
        .windowToolbarStyle(.unifiedCompact)
        #endif
    }
}
