import SwiftUI

@main
struct VexoWatchApp: App {
    @StateObject private var haptics = HapticsCentral()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView(haptics: haptics)
                .onChange(of: scenePhase, initial: true) { _, phase in
                    haptics.setActive(phase == .active)
                }
        }
    }
}
