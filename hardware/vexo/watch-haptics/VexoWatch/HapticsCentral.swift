import Combine
@preconcurrency import CoreBluetooth
import Foundation
import WatchKit

/// CoreBluetooth delegates run on .main; @preconcurrency bridges its ObjC protocols.
@MainActor
final class HapticsCentral: NSObject, ObservableObject,
    @preconcurrency CBCentralManagerDelegate, @preconcurrency CBPeripheralDelegate {
    static let serviceID = CBUUID(string: "b41732d0-b80c-430b-ad6c-88af4eacb5e3")
    static let commandID = CBUUID(string: "d50f9664-4e1e-4662-ac29-b1336546f6e5")
    static let responseID = CBUUID(string: "b35fe0ba-1cf7-4c2e-a4c2-d20484c2a309")

    @Published private(set) var status = "Disconnected"
    @Published private(set) var isConnecting = false
    @Published private(set) var isConnected = false
    @Published private(set) var isActive = false
    @Published private(set) var isReady = false
    @Published private(set) var lastEvent = "No events yet"
    @Published private(set) var lastReceivedAt: Date?

    private var manager: CBCentralManager?
    private var peripheral: CBPeripheral?
    private var commandCharacteristic: CBCharacteristic?
    private var responseCharacteristic: CBCharacteristic?
    private var subscribed = false
    private var wantsConnection = false
    private var timeoutTask: Task<Void, Never>?
    private var ledger = ReceiptLedger()

    private struct ResponseWrite {
        let data: Data
        let ready: Bool?
    }
    private var writes: [ResponseWrite] = []
    private var inFlight: ResponseWrite?

    func setActive(_ active: Bool) {
        guard isActive != active else { return }
        isActive = active
        if subscribed {
            announceReadiness(active)
        } else if !active && isConnecting {
            disconnect(message: "Paused — tap Connect")
        }
    }

    func connect() {
        guard isActive, !isConnected, !isConnecting else { return }
        wantsConnection = true
        isConnecting = true
        status = "Checking Bluetooth…"
        timeoutTask?.cancel()
        timeoutTask = Task { [weak self] in
            do { try await Task.sleep(for: .seconds(30)) } catch { return }
            self?.disconnect(message: "Timed out — tap Connect")
        }
        if let manager {
            centralManagerDidUpdateState(manager)
        } else {
            manager = CBCentralManager(delegate: self, queue: .main)
        }
    }

    func disconnect(message: String = "Disconnected") {
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
        peripheral?.delegate = nil
        peripheral = nil
        commandCharacteristic = nil
        responseCharacteristic = nil
        subscribed = false
        writes.removeAll()
        inFlight = nil
        isConnected = false
        isConnecting = false
        isReady = false
        // Deliberately retain the receipt ledger across connections.
    }

    private func announceReadiness(_ ready: Bool) {
        isReady = false
        writes.removeAll { $0.ready != nil }
        enqueue(ResponseWrite(data: Data([1, ready ? 0 : 255]), ready: ready))
        if !ready { status = "Connected · paused" }
    }

    private func enqueue(_ write: ResponseWrite) {
        guard subscribed, peripheral?.state == .connected,
              responseCharacteristic != nil else { return }
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
            guard wantsConnection, isActive, peripheral == nil else { return }
            status = "Looking for Mac…"
            central.scanForPeripherals(withServices: [Self.serviceID], options: [
                CBCentralManagerScanOptionAllowDuplicatesKey: false
            ])
        case .unknown, .resetting:
            status = "Bluetooth starting…"
        case .poweredOff:
            disconnect(message: "Turn on Bluetooth")
        case .unauthorized:
            disconnect(message: "Allow Bluetooth in Settings")
        case .unsupported:
            disconnect(message: "Bluetooth unavailable")
        @unknown default:
            disconnect(message: "Bluetooth unavailable")
        }
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral,
                        advertisementData: [String: Any], rssi RSSI: NSNumber) {
        guard wantsConnection, isActive, self.peripheral == nil else { return }
        central.stopScan()
        self.peripheral = peripheral
        peripheral.delegate = self
        status = "Connecting to Mac…"
        central.connect(peripheral)
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        guard self.peripheral === peripheral, wantsConnection, isActive else {
            central.cancelPeripheralConnection(peripheral)
            return
        }
        isConnected = true
        status = "Finding haptics service…"
        peripheral.discoverServices([Self.serviceID])
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral,
                        error: Error?) {
        guard self.peripheral === peripheral else { return }
        disconnect(message: "Connection failed — tap Connect")
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral,
                        error: Error?) {
        guard self.peripheral === peripheral else { return }
        wantsConnection = false
        timeoutTask?.cancel()
        timeoutTask = nil
        clearConnection()
        status = "Disconnected — tap Connect"
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard self.peripheral === peripheral else { return }
        guard error == nil,
              let service = peripheral.services?.first(where: { $0.uuid == Self.serviceID }) else {
            disconnect(message: "Haptics service unavailable")
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
            disconnect(message: "Incompatible haptics service")
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
            disconnect(message: "Subscription failed — reconnect")
            return
        }
        subscribed = true
        // Readiness is announced only after CoreBluetooth confirms the subscription.
        announceReadiness(isActive)
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic,
                    error: Error?) {
        guard self.peripheral === peripheral, subscribed,
              characteristic.uuid == Self.commandID, error == nil,
              let bytes = characteristic.value else { return }
        guard let command = HapticCommand(bytes) else {
            lastEvent = "Invalid event ignored"
            lastReceivedAt = Date()
            return
        }
        let result = ledger.status(for: command, active: isActive)
        if result == 0 {
            let haptic: WKHapticType = switch command.kind {
            case .notification: .notification
            case .click: .click
            case .success: .success
            }
            WKInterfaceDevice.current().play(haptic)
        }
        let outcome = result == 0 ? "called" : result == 1 ? "duplicate ignored" : "inactive ignored"
        lastEvent = "\(command.kind.label) #\(command.id.sequence) · \(outcome)"
        lastReceivedAt = Date()
        enqueue(ResponseWrite(data: command.acknowledgement(status: result), ready: nil))
    }

    func peripheral(_ peripheral: CBPeripheral, didWriteValueFor characteristic: CBCharacteristic,
                    error: Error?) {
        guard self.peripheral === peripheral, characteristic.uuid == Self.responseID else { return }
        let sent = inFlight
        inFlight = nil
        guard error == nil else {
            disconnect(message: "Response failed — reconnect")
            return
        }
        if let ready = sent?.ready {
            isReady = ready && isActive
            status = isReady ? "Ready for Mac" : "Connected · paused"
            isConnecting = false
            timeoutTask?.cancel()
            timeoutTask = nil
        }
        sendNextWrite()
    }
}
