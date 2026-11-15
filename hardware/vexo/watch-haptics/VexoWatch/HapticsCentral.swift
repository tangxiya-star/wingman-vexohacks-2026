import Combine
@preconcurrency import CoreBluetooth
import Foundation
@preconcurrency import UserNotifications
import WatchKit

/// Copy only Sendable values out of the notification-center callback queue.
private struct NotificationPermission: Sendable {
    let allowed: Bool
    let sound: Bool
    let label: String
    let diagnostics: String

    init(_ settings: UNNotificationSettings) {
        allowed = settings.authorizationStatus == .authorized || settings.authorizationStatus == .provisional
        sound = settings.soundSetting == .enabled
        diagnostics = "auth=\(settings.authorizationStatus.rawValue) alert=\(settings.alertSetting.rawValue) sound=\(settings.soundSetting.rawValue)"
        switch settings.authorizationStatus {
        case .notDetermined: label = "通知：尚未允许"
        case .denied: label = "通知：已拒绝，请在设置中更改"
        case .provisional: label = "通知：已允许（静默）"
        case .authorized: label = "通知：已允许"
        @unknown default: label = "通知：状态未知"
        }
    }
}

/// CoreBluetooth delegates run on .main; @preconcurrency bridges its ObjC protocols.
@MainActor
final class HapticsCentral: NSObject, ObservableObject,
    @preconcurrency CBCentralManagerDelegate, @preconcurrency CBPeripheralDelegate,
    UNUserNotificationCenterDelegate {
    static let serviceID = CBUUID(string: "b41732d0-b80c-430b-ad6c-88af4eacb5e3")
    static let commandID = CBUUID(string: "d50f9664-4e1e-4662-ac29-b1336546f6e5")
    static let responseID = CBUUID(string: "b35fe0ba-1cf7-4c2e-a4c2-d20484c2a309")

    @Published private(set) var status = "Disconnected"
    @Published private(set) var isConnecting = false
    @Published private(set) var isConnected = false
    @Published private(set) var isActive = false
    @Published private(set) var isBackground = false
    @Published private(set) var isReady = false
    @Published private(set) var notificationsEnabled = false
    @Published private(set) var notificationPermissionStatus = "通知：读取中…"
    @Published private(set) var notificationDiagnostics = "尚未读取系统状态"
    @Published private(set) var lastConnectionNote = "暂无断连或写入错误"
    @Published private(set) var bluetoothStatus = "蓝牙：尚未检查"
    @Published private(set) var lastDisconnectionReason = "尚未断开"
    @Published private(set) var isRequestingNotifications = false
    @Published private(set) var lastEvent = "No events yet"
    @Published private(set) var lastReceivedAt: Date?

    private var manager: CBCentralManager?
    private var peripheral: CBPeripheral?
    private var knownPeripheral: CBPeripheral?
    private var restoringKnownPeripheral = false
    private var automaticRecoveryUsed = false
    private var backgroundBudgetExceeded = false
    private var commandCharacteristic: CBCharacteristic?
    private var responseCharacteristic: CBCharacteristic?
    private var subscribed = false
    private var wantsConnection = false
    private var timeoutTask: Task<Void, Never>?
    private var ledger = ReceiptLedger()
    private var connectionGeneration = UUID()
    private let notificationCenter = UNUserNotificationCenter.current()
    private var permissionRefreshID = UUID()
    private var bluetoothTasks: [UUID: WKBluetoothAlertRefreshBackgroundTask] = [:]
    private var bluetoothTaskTimeouts: [UUID: Task<Void, Never>] = [:]
    private var observedBluetoothTasks: Set<UUID> = []
    private var processingBluetoothEvents: Set<UUID> = []

    private struct ResponseWrite {
        let data: Data
        let ready: UInt8?
        let eventID: UUID?

        init(data: Data, ready: UInt8?, eventID: UUID? = nil) {
            self.data = data
            self.ready = ready
            self.eventID = eventID
        }
    }
    private var writes: [ResponseWrite] = []
    private var inFlight: ResponseWrite?

    override init() {
        super.init()
        notificationCenter.delegate = self
        refreshNotificationSettings()
    }

    private var currentConnection: ConnectionToken? {
        guard subscribed, let peripheral, peripheral.state == .connected else { return nil }
        return ConnectionToken(peripheral: peripheral.identifier, generation: connectionGeneration)
    }

    private var readiness: UInt8 {
        isActive ? 0 : notificationsEnabled && !backgroundBudgetExceeded ? 1 : 255
    }

    func handleBackgroundTasks(_ tasks: Set<WKRefreshBackgroundTask>) {
        for task in tasks {
            guard let bluetoothTask = task as? WKBluetoothAlertRefreshBackgroundTask,
                  !isActive else {
                task.setTaskCompletedWithSnapshot(false)
                continue
            }
            let id = UUID()
            bluetoothTasks[id] = bluetoothTask
            bluetoothTask.expirationHandler = { [weak self] in
                Task { @MainActor [weak self] in self?.completeBluetoothTask(id) }
            }
            bluetoothTaskTimeouts[id] = Task { [weak self] in
                do { try await Task.sleep(for: .milliseconds(2500)) } catch { return }
                self?.completeBluetoothTask(id)
            }
            // WatchKit calls handle before the associated CoreBluetooth callbacks.
            // Wait for the event, its UN completion and its response write; never complete here.
        }
    }

    private func completeBluetoothTask(_ id: UUID) {
        guard let task = bluetoothTasks.removeValue(forKey: id) else { return }
        bluetoothTaskTimeouts.removeValue(forKey: id)?.cancel()
        observedBluetoothTasks.remove(id)
        task.expirationHandler = nil
        task.setTaskCompletedWithSnapshot(false)
        // Expiration does not cancel a pending notification or drop a later ACK callback.
    }

    private func completeAllBluetoothTasks() {
        for id in Array(bluetoothTasks.keys) { completeBluetoothTask(id) }
    }

    private func beginBluetoothEvent() -> UUID {
        let id = UUID()
        processingBluetoothEvents.insert(id)
        observedBluetoothTasks.formUnion(bluetoothTasks.keys)
        return id
    }

    private func finishBluetoothEvent(_ id: UUID?) {
        guard let id else { return }
        processingBluetoothEvents.remove(id)
        guard processingBluetoothEvents.isEmpty else { return }
        for taskID in Array(observedBluetoothTasks) { completeBluetoothTask(taskID) }
    }

    var sceneDescription: String { isActive ? "active" : isBackground ? "background" : "inactive" }

    private func recordConnectionNote(_ reason: String, error: Error? = nil, sentReady: UInt8? = nil) {
        let sent = sentReady.map { String(format: "%02x", $0) } ?? "ACK/none"
        let failure = error.map { " error=\(($0 as NSError).domain):\(($0 as NSError).code)" } ?? ""
        lastConnectionNote = "\(reason)\(failure) · sent=\(sent) scene=\(sceneDescription) allowed=\(notificationsEnabled) ble=\(peripheral?.state.rawValue ?? -1)"
    }

    func setSceneState(active: Bool, background: Bool) {
        let becameActive = active && !isActive
        let changed = isActive != active || isBackground != background
        isActive = active
        isBackground = background
        if becameActive {
            backgroundBudgetExceeded = false
            automaticRecoveryUsed = false
        }
        if changed && subscribed {
            announceReadiness()
        } else if background && isConnecting && !isConnected && !restoringKnownPeripheral {
            disconnect(message: "Paused — tap Connect")
        }
        if active {
            completeAllBluetoothTasks()
            refreshNotificationSettings()
            removeExpiredInvitations()
            if becameActive && wantsConnection && !isConnected && knownPeripheral != nil {
                if isConnecting {
                    armConnectionTimeout(preserveIntent: true)
                } else {
                    reconnectKnownPeripheral(bounded: true)
                }
            }
        }
        // A permission sheet changes active → inactive. Keep its pending Connect alive.
    }

    func enableNotifications() {
        guard isActive, !isRequestingNotifications else { return }
        isRequestingNotifications = true
        notificationCenter.requestAuthorization(options: [.alert, .sound]) { [weak self] _, error in
            let failed = error != nil
            Task { @MainActor [weak self] in
                guard let self else { return }
                self.isRequestingNotifications = false
                if failed { self.notificationPermissionStatus = "通知：授权请求失败" }
                self.refreshNotificationSettings()
            }
        }
    }

    private func refreshNotificationSettings() {
        let refreshID = UUID()
        permissionRefreshID = refreshID
        notificationCenter.getNotificationSettings { [weak self] settings in
            let permission = NotificationPermission(settings)
            Task { @MainActor [weak self] in
                guard let self, self.permissionRefreshID == refreshID else { return }
                self.applyPermission(permission)
            }
        }
    }

    private func applyPermission(_ permission: NotificationPermission) {
        let changed = notificationsEnabled != permission.allowed
        notificationsEnabled = permission.allowed
        notificationPermissionStatus = permission.label
        notificationDiagnostics = permission.diagnostics
        if changed && subscribed { announceReadiness() }
    }

    private func removeExpiredInvitations() {
        let cutoff = Date().addingTimeInterval(-15 * 60)
        notificationCenter.getDeliveredNotifications { notifications in
            let expired = notifications.filter {
                $0.request.identifier.hasPrefix("vexo-match-") && $0.date < cutoff &&
                    ($0.request.content.userInfo["kind"] as? NSNumber)?.intValue == 4
            }.map { $0.request.identifier }
            UNUserNotificationCenter.current().removeDeliveredNotifications(withIdentifiers: expired)
        }
    }

    func connect() {
        guard isActive, !isConnected, !isConnecting else { return }
        wantsConnection = true
        automaticRecoveryUsed = false
        backgroundBudgetExceeded = false
        connectionGeneration = UUID()
        isConnecting = true
        status = "Checking Bluetooth…"
        armConnectionTimeout(preserveIntent: false)
        if let manager {
            centralManagerDidUpdateState(manager)
        } else {
            manager = CBCentralManager(delegate: self, queue: .main)
        }
    }

    private func armConnectionTimeout(preserveIntent: Bool) {
        timeoutTask?.cancel()
        timeoutTask = Task { [weak self] in
            do { try await Task.sleep(for: .seconds(30)) } catch { return }
            guard let self else { return }
            if preserveIntent {
                self.recordConnectionNote("Known Mac reconnect timed out")
                self.lastDisconnectionReason = "重连已超时"
                if let peripheral = self.peripheral {
                    self.manager?.cancelPeripheralConnection(peripheral)
                }
                self.clearConnection()
                self.status = "重连超时 · 打开App或点Connect重试"
            } else {
                self.disconnect(message: "Timed out — tap Connect")
            }
        }
    }

    private func reconnectKnownPeripheral(bounded: Bool) {
        guard wantsConnection, !backgroundBudgetExceeded, !automaticRecoveryUsed,
              self.peripheral == nil, let knownPeripheral,
              let manager, manager.state == .poweredOn else { return }
        automaticRecoveryUsed = true
        restoringKnownPeripheral = true
        connectionGeneration = UUID()
        self.peripheral = knownPeripheral
        knownPeripheral.delegate = self
        isConnecting = true
        status = "正在重连同一台Mac…"
        manager.stopScan()
        timeoutTask?.cancel()
        timeoutTask = nil
        if bounded { armConnectionTimeout(preserveIntent: true) }
        // One pending system connection request, no scan and no repeating retry timer.
        manager.connect(knownPeripheral)
    }

    func disconnect(message: String = "Disconnected", error: Error? = nil, sentReady: UInt8? = nil) {
        recordConnectionNote(message, error: error, sentReady: sentReady)
        lastDisconnectionReason = message
        // Best-effort withdrawal; disconnect also invalidates readiness on the Mac.
        if subscribed, inFlight == nil, let peripheral,
           peripheral.state == .connected, let responseCharacteristic {
            peripheral.writeValue(Data([1, 255]), for: responseCharacteristic, type: .withResponse)
        }
        wantsConnection = false
        timeoutTask?.cancel()
        timeoutTask = nil
        manager?.stopScan()
        if let peripheral { manager?.cancelPeripheralConnection(peripheral) }
        clearConnection()
        status = message
    }

    func localTest() {
        guard isActive else { return }
        WKInterfaceDevice.current().play(.notification)
        lastEvent = "Local notification called"
        lastReceivedAt = Date()
    }

    private func clearConnection() {
        connectionGeneration = UUID()
        peripheral?.delegate = nil
        peripheral = nil
        restoringKnownPeripheral = false
        commandCharacteristic = nil
        responseCharacteristic = nil
        subscribed = false
        writes.removeAll()
        inFlight = nil
        processingBluetoothEvents.removeAll()
        completeAllBluetoothTasks()
        isConnected = false
        isConnecting = false
        isReady = false
        // Deliberately retain the receipt ledger across connections.
    }

    private func announceReadiness() {
        let ready = readiness
        isReady = false
        writes.removeAll { $0.ready != nil }
        enqueue(ResponseWrite(data: Data([1, ready]), ready: ready))
        if ready == 255 { status = "Connected · notifications disabled" }
    }

    private func enqueue(_ write: ResponseWrite) {
        guard subscribed, peripheral?.state == .connected,
              responseCharacteristic != nil else {
            finishBluetoothEvent(write.eventID)
            return
        }
        guard writes.count < 64 else {
            disconnect(message: "Response queue full — reconnect")
            return
        }
        writes.append(write)
        sendNextWrite()
    }

    private func sendNextWrite() {
        guard inFlight == nil, !writes.isEmpty,
              let peripheral, peripheral.state == .connected,
              let responseCharacteristic else { return }
        let write = writes.removeFirst()
        inFlight = write
        peripheral.writeValue(write.data, for: responseCharacteristic, type: .withResponse)
    }

    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        switch central.state {
        case .poweredOn:
            bluetoothStatus = "蓝牙：已开启"
            if wantsConnection, peripheral == nil, knownPeripheral != nil {
                reconnectKnownPeripheral(bounded: isActive)
                return
            }
            guard wantsConnection, !isBackground, peripheral == nil else { return }
            status = "Looking for Mac…"
            central.scanForPeripherals(withServices: [Self.serviceID], options: [
                CBCentralManagerScanOptionAllowDuplicatesKey: false
            ])
        case .unknown, .resetting:
            bluetoothStatus = "蓝牙：初始化中"
            status = "Bluetooth starting…"
        case .poweredOff:
            bluetoothStatus = "蓝牙：已关闭"
            disconnect(message: "Turn on Bluetooth")
        case .unauthorized:
            bluetoothStatus = "蓝牙：权限未允许"
            disconnect(message: "Allow Bluetooth in Settings")
        case .unsupported:
            bluetoothStatus = "蓝牙：不可用"
            disconnect(message: "Bluetooth unavailable")
        @unknown default:
            bluetoothStatus = "蓝牙：状态未知"
            disconnect(message: "Bluetooth unavailable")
        }
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                        advertisementData: [String: Any], rssi RSSI: NSNumber) {
        guard wantsConnection, !isBackground, self.peripheral == nil,
              knownPeripheral == nil else { return }
        central.stopScan()
        self.peripheral = peripheral
        peripheral.delegate = self
        status = "Connecting to Mac…"
        central.connect(peripheral)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        guard self.peripheral === peripheral, wantsConnection,
              !isBackground || restoringKnownPeripheral else {
            central.cancelPeripheralConnection(peripheral)
            return
        }
        isConnected = true
        knownPeripheral = peripheral
        status = "Finding haptics service…"
        peripheral.discoverServices([Self.serviceID])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral,
                        error: Error?) {
        guard self.peripheral === peripheral else { return }
        if restoringKnownPeripheral && wantsConnection {
            recordConnectionNote("Known Mac reconnection failed", error: error)
            lastDisconnectionReason = "同一台Mac重连失败"
            timeoutTask?.cancel()
            timeoutTask = nil
            clearConnection()
            status = "重连失败 · 打开App或点Connect重试"
            return
        }
        disconnect(message: "Connection failed — tap Connect", error: error)
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral,
                        error: Error?) {
        guard self.peripheral === peripheral else { return }
        recordConnectionNote("System disconnected", error: error)
        lastDisconnectionReason = error.map { "连接意外中断（\(($0 as NSError).domain):\(($0 as NSError).code)）" } ?? "连接意外中断"
        let canRecover = wantsConnection && knownPeripheral === peripheral &&
            !automaticRecoveryUsed && !backgroundBudgetExceeded && central.state == .poweredOn
        timeoutTask?.cancel()
        timeoutTask = nil
        clearConnection()
        if canRecover {
            reconnectKnownPeripheral(bounded: isActive)
        } else {
            status = backgroundBudgetExceeded ? "后台蓝牙额度已用完 · 请打开App" : "连接中断 · 打开App或点Connect重试"
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard self.peripheral === peripheral else { return }
        guard error == nil,
              let service = peripheral.services?.first(where: { $0.uuid == Self.serviceID }) else {
            disconnect(message: "Haptics service unavailable", error: error)
            return
        }
        peripheral.discoverCharacteristics([Self.commandID, Self.responseID], for: service)
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService,
                    error: Error?) {
        guard self.peripheral === peripheral, service.uuid == Self.serviceID else { return }
        guard error == nil,
              let command = service.characteristics?.first(where: { $0.uuid == Self.commandID }),
              let response = service.characteristics?.first(where: { $0.uuid == Self.responseID }),
              command.properties.contains(.notify), response.properties.contains(.write) else {
            disconnect(message: "Incompatible haptics service", error: error)
            return
        }
        commandCharacteristic = command
        responseCharacteristic = response
        status = "Subscribing…"
        peripheral.setNotifyValue(true, for: command)
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateNotificationStateFor characteristic: CBCharacteristic,
                    error: Error?) {
        guard self.peripheral === peripheral, characteristic.uuid == Self.commandID else { return }
        guard error == nil, characteristic.isNotifying else {
            disconnect(message: "Subscription failed — reconnect", error: error)
            return
        }
        subscribed = true
        // Readiness is announced only after CoreBluetooth confirms the subscription.
        announceReadiness()
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic,
                    error: Error?) {
        guard self.peripheral === peripheral, subscribed,
              characteristic.uuid == Self.commandID else { return }
        let eventID = beginBluetoothEvent()
        if let error {
            let failure = error as NSError
            let nearLimit = failure.domain == CBErrorDomain &&
                failure.code == CBError.Code.leGattNearBackgroundNotificationLimit.rawValue
            let exceeded = failure.domain == CBErrorDomain &&
                failure.code == CBError.Code.leGattExceededBackgroundNotificationLimit.rawValue
            recordConnectionNote(exceeded ? "Background BLE budget exceeded" :
                nearLimit ? "Background BLE budget nearly exhausted" : "BLE event failed", error: error)
            if exceeded {
                backgroundBudgetExceeded = true
                isReady = false
                announceReadiness()
                status = "后台蓝牙额度已用完 · 请打开App"
            }
            // The final allowed alert may carry both its value and the near-limit warning.
            guard nearLimit else {
                finishBluetoothEvent(eventID)
                return
            }
        }
        guard let bytes = characteristic.value else {
            finishBluetoothEvent(eventID)
            return
        }
        guard let command = HapticCommand(bytes) else {
            lastEvent = "Invalid event ignored"
            lastReceivedAt = Date()
            finishBluetoothEvent(eventID)
            return
        }
        guard let connection = currentConnection else {
            finishBluetoothEvent(eventID)
            return
        }
        // This reserves the ID before notification permission checks or add() callbacks.
        switch ledger.delivery(for: command, active: isActive) {
        case .play:
            let haptic: WKHapticType = switch command.kind {
            case .notification, .matchRequest: .notification
            case .click: .click
            case .success, .matchConfirmed: .success
            }
            WKInterfaceDevice.current().play(haptic)
            acknowledge(command, result: .playCalled, connection: connection, eventID: eventID)
        case .duplicate:
            acknowledge(command, result: .duplicate, connection: connection, eventID: eventID)
        case .inactive:
            acknowledge(command, result: .inactive, connection: connection, eventID: eventID)
        case .notification:
            scheduleMatchNotification(command, connection: connection, eventID: eventID)
        }
    }

    private func acknowledge(_ command: HapticCommand, result: CommandReceipt, connection: ConnectionToken, eventID: UUID) {
        guard currentConnection == connection else {
            finishBluetoothEvent(eventID)
            return
        }
        lastEvent = "\(command.kind.label) #\(command.id.sequence) · \(result.label)"
        lastReceivedAt = Date()
        enqueue(ResponseWrite(data: command.acknowledgement(status: result.rawValue), ready: nil, eventID: eventID))
    }

    private func scheduleMatchNotification(_ command: HapticCommand, connection: ConnectionToken, eventID: UUID) {
        guard command.kind.allowsBackgroundNotification, currentConnection == connection else {
            finishBluetoothEvent(eventID)
            return
        }
        lastEvent = "\(command.kind.label) #\(command.id.sequence) · checking notification permission"
        lastReceivedAt = Date()
        // Read current settings for every notification; authorization can change in Settings.
        notificationCenter.getNotificationSettings { [weak self] settings in
            let permission = NotificationPermission(settings)
            Task { @MainActor [weak self] in
                guard let self else { return }
                guard self.currentConnection == connection else {
                    self.finishBluetoothEvent(eventID)
                    return
                }
                self.applyPermission(permission)
                guard self.currentConnection == connection else {
                    self.finishBluetoothEvent(eventID)
                    return
                }
                guard permission.allowed else {
                    self.acknowledge(command, result: .notificationDenied, connection: connection, eventID: eventID)
                    return
                }
                let content = UNMutableNotificationContent()
                content.title = command.kind == .matchRequest ? "Someone wants to meet" : "You're matched"
                content.body = command.kind == .matchRequest ?
                    "Raise your Vexo hand to say hello." : "You both raised your hands. Find each other."
                content.threadIdentifier = "vexo-matches"
                content.userInfo = ["kind": command.kind.rawValue,
                                    "session": command.id.session, "sequence": command.id.sequence]
                if permission.sound { content.sound = .default }
                let request = UNNotificationRequest(identifier: command.notificationIdentifier,
                                                    content: content, trigger: nil)
                self.notificationCenter.add(request) { [weak self] error in
                    let receipt: CommandReceipt
                    if let error = error as NSError? {
                        receipt = error.domain == UNErrorDomain && error.code == 1 ?
                            .notificationDenied : .notificationFailed
                    } else {
                        receipt = .notificationScheduled
                    }
                    Task { @MainActor [weak self] in
                        // A disconnect/reconnect may happen while the OS schedules the request.
                        guard let self else { return }
                        guard self.currentConnection == connection else {
                            self.finishBluetoothEvent(eventID)
                            return
                        }
                        self.acknowledge(command, result: receipt, connection: connection, eventID: eventID)
                        if receipt == .notificationDenied { self.refreshNotificationSettings() }
                    }
                }
            }
        }
    }

    nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter,
                                           willPresent notification: UNNotification,
                                           withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
        // Also present if the wrist is raised after scheduling but before OS delivery.
        // This never calls play() or replays the event when the scene becomes active.
        completionHandler(notification.request.identifier.hasPrefix("vexo-match-") ? [.banner, .sound, .list] : [])
    }

    func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic,
                    error: Error?) {
        guard self.peripheral === peripheral, characteristic.uuid == Self.responseID else { return }
        let sent = inFlight
        inFlight = nil
        guard error == nil else {
            if let ready = sent?.ready, peripheral.state == .connected {
                // A failed state announcement does not prove the BLE link has gone away.
                // Retry only after a later scene/permission change, never in a loop here.
                recordConnectionNote("Ready write failed; link kept", error: error, sentReady: ready)
                isReady = false
                isConnecting = false
                timeoutTask?.cancel()
                timeoutTask = nil
                writes.removeAll { $0.ready != nil }
                status = "Connected · status write failed"
                sendNextWrite()
                return
            }
            disconnect(message: "Response failed — reconnect", error: error, sentReady: sent?.ready)
            return
        }
        if let ready = sent?.ready {
            isReady = ready != 255 && ready == readiness
            if ready == readiness {
                status = ready == 0 ? "Ready for Mac" : ready == 1 ?
                    "Ready · match alerts only" : "Connected · notifications disabled"
            }
            isConnecting = false
            timeoutTask?.cancel()
            timeoutTask = nil
        }
        sendNextWrite()
        finishBluetoothEvent(sent?.eventID)
    }
}
