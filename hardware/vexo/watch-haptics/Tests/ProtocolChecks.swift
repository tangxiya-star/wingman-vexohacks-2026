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
        precondition(HapticCommand(Data([1, 4]) + bytes.dropFirst(2)) == nil)
        for kind in UInt8(1)...3 {
            precondition(HapticCommand(Data([1, kind]) + bytes.dropFirst(2))?.kind.rawValue == kind)
        }

        var ledger = ReceiptLedger()
        precondition(ledger.status(for: command, active: true) == 0)
        precondition(ledger.status(for: command, active: true) == 1)
        precondition(ledger.status(for: command, active: false) == 1)

        let differentSession = HapticCommand(Data([1, 1, 1, 0, 0, 0]) + bytes.suffix(4))!
        precondition(ledger.status(for: differentSession, active: true) == 0)

        let inactiveCommand = HapticCommand(Data([1, 3, 1, 0, 0, 0, 8, 0, 0, 0]))!
        precondition(ledger.status(for: inactiveCommand, active: false) == 2)
        // Foreground restoration must never play an event first received while inactive.
        precondition(ledger.status(for: inactiveCommand, active: true) == 1)
        print("Protocol checks passed: length/version/kind, LE IDs, ACK bytes, duplicate and inactive replay guards.")
    }
}
