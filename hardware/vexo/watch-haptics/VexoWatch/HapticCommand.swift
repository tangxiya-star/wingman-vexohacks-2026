import Foundation

struct HapticCommand: Sendable {
    enum Kind: UInt8, Sendable {
        case notification = 1
        case click = 2
        case success = 3
        case matchRequest = 4
        case matchConfirmed = 5

        var label: String {
            switch self {
            case .notification: "Notification"
            case .click: "Click"
            case .success: "Success"
            case .matchRequest: "Match invitation"
            case .matchConfirmed: "Match confirmed"
            }
        }

        var allowsBackgroundNotification: Bool {
            self == .matchRequest || self == .matchConfirmed
        }
    }

    struct ID: Hashable, Sendable {
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

    var notificationIdentifier: String {
        "vexo-match-\(id.session)-\(id.sequence)"
    }
}

enum CommandReceipt: UInt8, Sendable {
    case playCalled = 0
    case duplicate = 1
    case inactive = 2
    case notificationScheduled = 3
    case notificationDenied = 4
    case notificationFailed = 5

    var label: String {
        switch self {
        case .playCalled: "called"
        case .duplicate: "duplicate ignored"
        case .inactive: "inactive ignored"
        case .notificationScheduled: "notification scheduled"
        case .notificationDenied: "notification denied"
        case .notificationFailed: "notification failed"
        }
    }
}

enum CommandDelivery: Equatable {
    case play
    case duplicate
    case inactive
    case notification
}

/// A new generation for every connection prevents async ACKs crossing reconnections.
struct ConnectionToken: Equatable, Sendable {
    let peripheral: UUID
    let generation: UUID
}

/// Retain across disconnects; reserve before any asynchronous notification work.
struct ReceiptLedger {
    private var seen: Set<HapticCommand.ID> = []

    mutating func delivery(for command: HapticCommand, active: Bool) -> CommandDelivery {
        guard seen.insert(command.id).inserted else { return .duplicate }
        if active { return .play }
        return command.kind.allowsBackgroundNotification ? .notification : .inactive
    }
}
