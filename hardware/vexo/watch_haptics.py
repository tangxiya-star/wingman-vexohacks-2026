"""Local Mac BLE peripheral for the Vexo Watch demo; never buzzes on connect."""

import argparse
import json
import secrets
import struct
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SERVICE_UUID = "b41732d0-b80c-430b-ad6c-88af4eacb5e3"
COMMAND_UUID = "d50f9664-4e1e-4662-ac29-b1336546f6e5"
RESPONSE_UUID = "b35fe0ba-1cf7-4c2e-a4c2-d20484c2a309"
KINDS = {"notification": 1, "click": 2, "success": 3,
         "match_request": 4, "match_confirmed": 5}
ALERT_KINDS = {4, 5}
RUNTIME = Path(__file__).resolve().parent / "runtime"


@dataclass
class Command:
    packet: bytes
    deadline: float
    sent: bool = False
    result: str | None = None
    done: threading.Event = field(default_factory=threading.Event)
    scope: str | None = None


class Session:
    """Single selected Watch, one outstanding command, no reconnect replay."""

    def __init__(self):
        self.lock = threading.RLock()
        self.session_id = secrets.randbits(32)
        self.sequence = 0
        self.central = None
        self.ready = False
        self.background_ready = False
        self.bluetooth = "starting"
        self.advertising = False
        self.pending = None
        self.last_result = None
        self.scopes = {}

    def snapshot(self):
        with self.lock:
            return {"bluetooth": self.bluetooth, "advertising": self.advertising,
                    "watch_connected": self.central is not None, "watch_ready": self.ready,
                    "watch_can_alert": self.central is not None and (self.ready or self.background_ready),
                    "busy": self.pending is not None, "last_result": self.last_result}

    def subscribe(self, central):
        with self.lock:
            if self.central not in (None, central):
                return False
            self.central = central
            self.ready = False
            self.background_ready = False
            return True

    def set_ready(self, central, ready, background_ready=False):
        with self.lock:
            if central != self.central:
                return False
            self.ready = ready
            self.background_ready = background_ready
            if self.pending and not self.can_send(self.pending):
                self._finish("watch_inactive")
            return True

    def can_send(self, command):
        return self.central is not None and (self.ready or
            (self.background_ready and command.packet[1] in ALERT_KINDS))

    def disconnect(self, central):
        with self.lock:
            if central == self.central:
                self.ready = False
                self.background_ready = False
                self.central = None
                self._finish("disconnected")

    def open_scope(self, scope):
        with self.lock:
            if not isinstance(scope, str) or len(scope) != 32 or any(c not in "0123456789abcdef" for c in scope):
                raise ValueError("Invalid command scope")
            if self.scopes.get(scope) == "cancelled":
                raise RuntimeError("This command scope was already cancelled")
            if scope not in self.scopes and len(self.scopes) >= 4096:
                raise RuntimeError("Session scope capacity reached; restart between demonstrations")
            self.scopes[scope] = "open"
            return {"scope_status": "opened"}

    def cancel_scope(self, scope):
        with self.lock:
            if not isinstance(scope, str) or len(scope) != 32 or any(c not in "0123456789abcdef" for c in scope):
                raise ValueError("Invalid command scope")
            if scope not in self.scopes and len(self.scopes) >= 4096:
                raise RuntimeError("Session scope capacity reached")
            self.scopes[scope] = "cancelled"
            if self.pending and self.pending.scope == scope:
                self._finish("cancelled")
            return {"scope_status": "cancelled"}

    def submit(self, kind, scope=None):
        with self.lock:
            if scope is not None and (not isinstance(scope, str) or self.scopes.get(scope) != "open"):
                raise RuntimeError("Command scope is unknown or cancelled")
            if kind not in KINDS:
                raise ValueError("Unknown haptic kind")
            allowed = self.ready or (self.background_ready and KINDS[kind] in ALERT_KINDS)
            if not allowed or self.central is None:
                raise RuntimeError("Watch is not ready; open Vexo Watch and tap Connect")
            if self.pending is not None:
                raise RuntimeError("A command is already pending; it will not be repeated")
            self.sequence += 1
            packet = struct.pack("<BBII", 1, KINDS[kind], self.session_id, self.sequence)
            self.pending = Command(packet, time.monotonic() + 4, scope=scope)
            return self.pending

    def _finish(self, result):
        if self.pending is not None:
            self.pending.result = result
            self.pending.done.set()
            self.last_result = result
            self.pending = None

    def expire(self, now=None):
        with self.lock:
            if self.pending and (time.monotonic() if now is None else now) >= self.pending.deadline:
                self._finish("timeout_not_retried")

    def receive(self, central, data):
        with self.lock:
            if central != self.central:
                return False
            if data == b"\x01\x00":
                return self.set_ready(central, True)
            if data == b"\x01\xff":
                return self.set_ready(central, False)
            if data == b"\x01\x01":
                return self.set_ready(central, False, True)
            if len(data) != 11 or data[0] != 1:
                return False
            if self.pending and data[:10] == self.pending.packet:
                result = {0: "play_called", 1: "duplicate_ignored", 2: "watch_inactive",
                          3: "notification_scheduled", 4: "notification_denied",
                          5: "notification_failed"}.get(data[10])
                if result is None:
                    return False
                if result == "watch_inactive":
                    # A lost readiness-withdrawal write must not cause repeated
                    # foreground-only pulses to wake a background Watch.
                    self.ready = False
                self._finish(result)
            return True


def make_http(session, token, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, status, body):
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if self.path != "/status":
                return self.respond(404, {"error": "not_found"})
            self.respond(200, session.snapshot())

        def do_POST(self):
            if self.path not in ("/buzz", "/scope/open", "/scope/cancel"):
                return self.respond(404, {"error": "not_found"})
            supplied = self.headers.get("X-Vexo-Token", "")
            if not secrets.compare_digest(supplied, token):
                return self.respond(403, {"error": "unauthorized"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 1 <= size <= 512:
                    raise ValueError("Expected a small JSON request body")
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError("Expected a JSON object")
                if self.path == "/scope/open":
                    return self.respond(200, session.open_scope(body.get("scope")))
                if self.path == "/scope/cancel":
                    return self.respond(200, session.cancel_scope(body.get("scope")))
                command = session.submit(body.get("kind", "notification"), body.get("scope"))
            except (ValueError, TypeError) as error:
                return self.respond(400, {"error": str(error)})
            except RuntimeError as error:
                return self.respond(409, {"error": str(error)})
            command.done.wait(4.5)
            session.expire()
            success = command.result in ("play_called", "notification_scheduled")
            self.respond(200 if success else 409, {"result": command.result or "timeout_not_retried",
                         "meaning": "Watch called haptics or scheduled a local notification; wearer confirmation is separate"})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be in 1..65535")

    # Importing the module for offline tests does not instantiate Bluetooth.
    import CoreBluetooth as CB
    from Foundation import NSObject, NSData, NSDate, NSRunLoop
    import objc

    session = Session()
    token = secrets.token_urlsafe(32)
    server = make_http(session, token, args.port)
    RUNTIME.mkdir(exist_ok=True)
    token_path = RUNTIME / "watch_haptics.token"
    import os
    descriptor = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as output:
        output.write(token)
    token_path.chmod(0o600)

    def log(message):
        print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)

    class PeripheralDelegate(NSObject):
        def init(self):
            self = objc.super(PeripheralDelegate, self).init()
            if self is not None:
                self.command_characteristic = None
                self.response_characteristic = None
                self.target = None
                self.can_update = True
            return self

        def peripheralManagerDidUpdateState_(self, manager):
            state = manager.state()
            session.bluetooth = "powered_on" if state == CB.CBManagerStatePoweredOn else f"state_{state}"
            if state != CB.CBManagerStatePoweredOn:
                session.disconnect(session.central)
                session.advertising = False
                log(f"Bluetooth unavailable: {state}")
                return
            self.command_characteristic = CB.CBMutableCharacteristic.alloc().initWithType_properties_value_permissions_(
                CB.CBUUID.UUIDWithString_(COMMAND_UUID), CB.CBCharacteristicPropertyNotify,
                None, CB.CBAttributePermissionsReadable)
            self.response_characteristic = CB.CBMutableCharacteristic.alloc().initWithType_properties_value_permissions_(
                CB.CBUUID.UUIDWithString_(RESPONSE_UUID), CB.CBCharacteristicPropertyWrite,
                None, CB.CBAttributePermissionsWriteable)
            service = CB.CBMutableService.alloc().initWithType_primary_(CB.CBUUID.UUIDWithString_(SERVICE_UUID), True)
            service.setCharacteristics_([self.command_characteristic, self.response_characteristic])
            manager.addService_(service)

        def peripheralManager_didAddService_error_(self, manager, service, error):
            if error is not None:
                session.bluetooth = f"service_error: {error}"
                log(session.bluetooth)
                return
            manager.startAdvertising_({CB.CBAdvertisementDataLocalNameKey: "Vexo-Mac",
                CB.CBAdvertisementDataServiceUUIDsKey: [CB.CBUUID.UUIDWithString_(SERVICE_UUID)]})

        def peripheralManagerDidStartAdvertising_error_(self, manager, error):
            session.advertising = error is None
            log(f"Advertising failed: {error}" if error else "Mac 蓝牙服务已广播；等待 Watch App 连接。")

        def peripheralManager_central_didSubscribeToCharacteristic_(self, manager, central, characteristic):
            if str(characteristic.UUID()).lower() != COMMAND_UUID:
                return
            identifier = str(central.identifier())
            if session.subscribe(identifier):
                self.target = central
                log("Watch 已订阅；等待 App 前台就绪。")

        def peripheralManager_central_didUnsubscribeFromCharacteristic_(self, manager, central, characteristic):
            identifier = str(central.identifier())
            if identifier == session.central:
                session.disconnect(identifier)
                self.target = None
                log("Watch 已断开；不会重播旧指令。")

        def peripheralManager_didReceiveWriteRequests_(self, manager, requests):
            # This protocol has a single small, non-offset write per command.
            if len(requests) != 1:
                manager.respondToRequest_withResult_(requests[0], CB.CBATTErrorRequestNotSupported)
                return
            request = requests[0]
            valid = (str(request.characteristic().UUID()).lower() == RESPONSE_UUID
                     and request.offset() == 0)
            data = bytes(request.value()) if request.value() is not None else b""
            valid = valid and session.receive(str(request.central().identifier()), data)
            manager.respondToRequest_withResult_(request, CB.CBATTErrorSuccess if valid else CB.CBATTErrorWriteNotPermitted)
            if valid and data == b"\x01\x00":
                log("Watch App 已就绪；现在可发送一次震动。")
            elif valid and data == b"\x01\x01":
                log("Watch 已切到后台通知模式；连续震动暂停。")
            elif valid and len(data) == 11:
                log(f"Watch 应答：{session.last_result}")

        def peripheralManagerIsReadyToUpdateSubscribers_(self, manager):
            self.can_update = True

        @objc.python_method
        def flush(self, manager):
            session.expire()
            with session.lock:
                command = session.pending
                if not command or command.sent or not session.can_send(command) or self.target is None or not self.can_update:
                    return
                data = NSData.dataWithBytes_length_(command.packet, len(command.packet))
                # False means CoreBluetooth did not enqueue; no successful send is repeated.
                command.sent = bool(manager.updateValue_forCharacteristic_onSubscribedCentrals_(
                    data, self.command_characteristic, [self.target]))
                self.can_update = command.sent

    delegate = PeripheralDelegate.alloc().init()
    manager = CB.CBPeripheralManager.alloc().initWithDelegate_queue_options_(delegate, None, None)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    log(f"Watch 控制服务：http://127.0.0.1:{args.port}/status；不会自动触发震动。")
    try:
        while True:
            NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))
            delegate.flush(manager)
    except KeyboardInterrupt:
        log("Watch 控制服务已停止。")
    finally:
        session.disconnect(session.central)
        manager.stopAdvertising()
        manager.removeAllServices()
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
