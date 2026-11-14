import SwiftUI

struct ContentView: View {
    @ObservedObject var haptics: HapticsCentral

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 12) {
                Text("Vexo Haptics").font(.headline)
                HStack(alignment: .top, spacing: 6) {
                    Circle().fill(haptics.isReady ? .green : .orange)
                        .frame(width: 7, height: 7).padding(.top, 4)
                    Text(haptics.status).font(.caption)
                }
                Text(haptics.isActive ? "Active · Keep app open" : "Paused · Open app to receive")
                    .font(.caption2).foregroundStyle(.secondary)

                if haptics.isConnected || haptics.isConnecting {
                    Button("Disconnect", role: .destructive) { haptics.disconnect() }
                } else {
                    Button("Connect to Mac") { haptics.connect() }
                        .disabled(!haptics.isActive)
                }
                Button("Local haptic test") { haptics.localTest() }
                    .disabled(!haptics.isActive)

                Divider()
                Text("LAST EVENT").font(.caption2).foregroundStyle(.secondary)
                Text(haptics.lastEvent).font(.caption2)
                if let time = haptics.lastReceivedAt {
                    Text(time, style: .time).font(.caption2).monospacedDigit()
                        .foregroundStyle(.secondary)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 4)
        }
    }
}
