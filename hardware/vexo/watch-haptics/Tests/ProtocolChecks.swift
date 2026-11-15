import Foundation

@main
enum ProtocolChecks {
    static func main() {
        let bytes = Data([1, 1, 0x78, 0x56, 0x34, 0x12, 0xef, 0xcd, 0xab, 0x90])
        let command = HapticCommand(bytes)!
        precondition(command.id.session == 0x12345678)
        precondition(command.id.sequence == 0x90abcdef)
        precondition(command.kind == .notification)
        precondition(command.acknowledgement(status: 0) == bytes + Data([0]))
        precondition(command.acknowledgement(status: 2).count == 11)
        precondition(HapticCommand(bytes.dropLast()) == nil)
        precondition(HapticCommand(bytes + Data([0])) == nil)
        precondition(HapticCommand(Data([2, 1]) + bytes.dropFirst(2)) == nil)
        precondition(HapticCommand(Data([1, 6]) + bytes.dropFirst(2)) == nil)
        for kind in UInt8(1)...5 {
            precondition(HapticCommand(Data([1, kind]) + bytes.dropFirst(2))?.kind.rawValue == kind)
        }
        precondition(command.notificationIdentifier == "vexo-match-305419896-2427178479")
        for status in UInt8(0)...5 {
            precondition(CommandReceipt(rawValue: status) != nil)
            precondition(command.acknowledgement(status: status) == bytes + Data([status]))
        }

        var ledger = ReceiptLedger()
        precondition(ledger.delivery(for: command, active: true) == .play)
        precondition(ledger.delivery(for: command, active: true) == .duplicate)
        precondition(ledger.delivery(for: command, active: false) == .duplicate)

        let differentSession = HapticCommand(Data([1, 1, 1, 0, 0, 0]) + bytes.suffix(4))!
        precondition(ledger.delivery(for: differentSession, active: true) == .play)

        let inactiveCommand = HapticCommand(Data([1, 3, 1, 0, 0, 0, 8, 0, 0, 0]))!
        precondition(ledger.delivery(for: inactiveCommand, active: false) == .inactive)
        // Foreground restoration must never play an event first received while inactive.
        precondition(ledger.delivery(for: inactiveCommand, active: true) == .duplicate)

        for kind in UInt8(1)...5 {
            let event = HapticCommand(Data([1, kind, 7, 0, 0, 0, kind, 0, 0, 0]))!
            var activeLedger = ReceiptLedger()
            precondition(activeLedger.delivery(for: event, active: true) == .play)
            let delivery = ledger.delivery(for: event, active: false)
            precondition(delivery == (kind >= 4 ? .notification : .inactive))
            // The ID is already reserved while permission/add completion is pending.
            precondition(ledger.delivery(for: event, active: false) == .duplicate)
            precondition(ledger.delivery(for: event, active: true) == .duplicate)
        }
        let changedKindSameID = HapticCommand(Data([1, 5, 7, 0, 0, 0, 4, 0, 0, 0]))!
        precondition(ledger.delivery(for: changedKindSameID, active: true) == .duplicate)

        let deviceID = UUID()
        let previousConnection = ConnectionToken(peripheral: deviceID, generation: UUID())
        let reconnected = ConnectionToken(peripheral: deviceID, generation: UUID())
        precondition(previousConnection != reconnected)
        print("Protocol checks passed: five kinds, exact ACKs, foreground/background routing, pre-reserved duplicate IDs, no replay, connection generation isolation.")
    }
}
