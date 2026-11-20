import SwiftUI

@main
struct FairyDesktopApplication: App {
    @StateObject private var model = FairyModel()
    #if os(macOS)
    @StateObject private var petController = DesktopPetController()
    #endif

    var body: some Scene {
        #if os(macOS)
        WindowGroup(id: "main") {
            ContentView()
                .environmentObject(model)
                .environmentObject(petController)
        }
        .windowStyle(.titleBar)
        .windowToolbarStyle(.unifiedCompact)
        MenuBarExtra("Fairy", systemImage: "sparkles") {
            FairyMenuBarView()
                .environmentObject(model)
                .environmentObject(petController)
        }
        .menuBarExtraStyle(.window)
        #else
        WindowGroup {
            ContentView()
                .environmentObject(model)
        }
        #endif
    }
}
