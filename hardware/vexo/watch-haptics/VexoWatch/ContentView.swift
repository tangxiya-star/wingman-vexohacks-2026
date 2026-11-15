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
                Text(haptics.isActive ? "前台 · 可触发震动" : "非活跃 · 仅匹配通知")
                    .font(.caption2).foregroundStyle(.secondary)
                Text(haptics.bluetoothStatus + (haptics.isConnected ? " · 已连接Mac" : haptics.isConnecting ? " · 连接中" : " · 未连接"))
                    .font(.caption2)

                Text(haptics.notificationPermissionStatus).font(.caption2)
                Button(haptics.isRequestingNotifications ? "等待系统授权…" : "允许匹配通知") {
                    haptics.enableNotifications()
                }
                .disabled(!haptics.isActive || haptics.isRequestingNotifications || haptics.notificationsEnabled)

                if haptics.isConnected || haptics.isConnecting {
                    Button("Disconnect", role: .destructive) { haptics.disconnect() }
                } else {
                    Button("Connect to Mac") { haptics.connect() }
                        .disabled(!haptics.isActive)
                }
                Button("Local haptic test") { haptics.localTest() }
                    .disabled(!haptics.isActive)
                Text("上次断开：\(haptics.lastDisconnectionReason)")
                    .font(.caption2).foregroundStyle(.secondary)

                Text("后台匹配提醒需要通知权限和蓝牙连接，可能受系统延迟或限额影响。")
                    .font(.caption2).foregroundStyle(.secondary)

                Divider()
                Text("LAST EVENT").font(.caption2).foregroundStyle(.secondary)
                Text(haptics.lastEvent).font(.caption2)
                if let time = haptics.lastReceivedAt {
                    Text(time, style: .time).font(.caption2).monospacedDigit()
                        .foregroundStyle(.secondary)
                }
                Divider()
                Text("诊断").font(.caption2).foregroundStyle(.secondary)
                Text("Scene: \(haptics.sceneDescription)").font(.caption2)
                Text(haptics.notificationDiagnostics).font(.caption2)
                Text(haptics.lastConnectionNote).font(.caption2)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 4)
        }
    }
}
