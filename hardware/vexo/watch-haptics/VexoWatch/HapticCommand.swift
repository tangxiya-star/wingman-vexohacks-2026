import Foundation

struct HapticCommand {
    enum Kind: UInt8 {
        case notification = 1
        case click = 2
        case success = 3

        var label: String {
            switch self {
            case .notification: "Notification"
            case .click: "Click"
            case .success: "Success"
            }
        }
    }

    struct ID: Hashable {
        let session: UInt32
        let sequence: UInt32
    }

    let kind: Kind
    let id: ID
    let bytes: Data

    init?(_ data: Data) {
        let bytes = [UInt8](data)
        guard bytes.count == 10, bytes[0] == 1,
              let kind = Kind(rawValue: bytes[1]) else { return nil }
        func littleEndian(at offset: Int) -> UInt32 {
            (0..<4).reduce(UInt32(0)) { value, index in
                value | UInt32(bytes[offset + index]) << (index * 8)
            }
        }
        self.kind = kind
        self.id = ID(session: littleEndian(at: 2), sequence: littleEndian(at: 6))
        self.bytes = data
    }

    func acknowledgement(status: UInt8) -> Data {
        bytes + Data([status])
    }
}

/// Keep the receipt ledger across disconnects. No command is queued for later play.
struct ReceiptLedger {
    private var seen: Set<HapticCommand.ID> = []

    mutating func status(for command: HapticCommand, active: Bool) -> UInt8 {
        guard seen.insert(command.id).inserted else { return 1 }
        return active ? 0 : 2
    }
}
