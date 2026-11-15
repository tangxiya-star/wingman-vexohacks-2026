import SwiftUI
import WatchKit

@MainActor
final class VexoApplicationDelegate: NSObject, @preconcurrency WKApplicationDelegate {
    // The delegate owns the same model used by the UI and all CoreBluetooth callbacks.
    let haptics = HapticsCentral()

    func handle(_ backgroundTasks: Set<WKRefreshBackgroundTask>) {
        haptics.handleBackgroundTasks(backgroundTasks)
    }
}

@main
struct VexoWatchApp: App {
    @WKApplicationDelegateAdaptor(VexoApplicationDelegate.self) private var applicationDelegate
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView(haptics: applicationDelegate.haptics)
                .onChange(of: scenePhase, initial: true) { _, phase in
                    applicationDelegate.haptics.setSceneState(active: phase == .active, background: phase == .background)
                }
        }
    }
}
