"""One explicit haptic on a serial-verified WHOOP 5; never auto-retry it."""

import argparse
import asyncio
import sys
import time

from bleak import BleakClient, BleakScanner

from whoop_haptics_protocol import (
    CLIENT_HELLO, COMMAND_UUID, NOTIFY_UUIDS, SERVICE_UUID,
    Reassembler, one_buzz_frame, one_second_frame, stop_frame,
)


def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


async def run(args):
    build_haptic, label = {
        "notification": (one_buzz_frame, "短震"),
        "one-second": (one_second_frame, "约 1 秒长震"),
    }[getattr(args, "pattern", "notification")]
    log("查找已确认的 WHOOP 蓝牙 UUID…")
    device = await BleakScanner.find_device_by_address(args.source, timeout=12)
    if device is None:
        raise RuntimeError("指定的 WHOOP 未广播；未连接其他设备。")
    log("已发现目标，建立蓝牙连接…")
    async with BleakClient(device, timeout=20) as client:
        log("已连接，读取设备身份。")
        async def read_text(short_uuid):
            raw = await asyncio.wait_for(client.read_gatt_char(
                f"0000{short_uuid}-0000-1000-8000-00805f9b34fb"), timeout=5)
            return bytes(raw).decode("utf-8", errors="strict").rstrip("\x00")

        serial = await read_text("2a25")
        model = await read_text("2a24")
        firmware = await read_text("2a26")
        if serial != args.serial:
            raise RuntimeError(f"序列号不匹配：收到 {serial}，未发送任何控制命令。")
        if model not in ("5.0", "MG") or client.services.get_service(SERVICE_UUID) is None:
            raise RuntimeError(f"不是已支持的 WHOOP 5/MG 控制服务：型号 {model}。")
        log(f"身份确认：WHOOP {serial}，型号 {model}，固件 {firmware}。")
        if not args.buzz:
            log("只读检查完成；未发送控制命令。")
            return

        # NOOP requires the confirmed hello write BEFORE private subscriptions.
        # This may trigger normal OS bonding; a refusal terminates this attempt.
        log("发送一次 CLIENT_HELLO 握手，等待蓝牙确认…")
        await asyncio.wait_for(client.write_gatt_char(
            COMMAND_UUID, CLIENT_HELLO, response=True), timeout=15)
        log("握手写入已确认，订阅控制应答。")
        responses = asyncio.Queue(maxsize=64)
        decoders = {}

        def callback(uuid):
            decoder = decoders[uuid] = Reassembler()

            def receive(_characteristic, data):
                for packet in decoder.feed(data):
                    if packet.packet_type in (36, 38) and packet.command in (19, 122):
                        log(f"控制应答 cmd={packet.command} request={packet.response_sequence} "
                            f"result={packet.result_name} body={packet.body.hex()}")
                        if not responses.full():
                            responses.put_nowait(packet)
            return receive

        for uuid in NOTIFY_UUIDS:
            if client.services.get_characteristic(uuid) is not None:
                await asyncio.wait_for(client.start_notify(uuid, callback(uuid)), timeout=5)

        async def final_response(command, seq, timeout):
            deadline = asyncio.get_running_loop().time() + timeout
            while True:
                packet = await asyncio.wait_for(responses.get(),
                    timeout=max(0.001, deadline - asyncio.get_running_loop().time()))
                if packet.command == command and packet.response_sequence == seq:
                    if packet.result != 2:
                        return packet

        attempted = False
        try:
            log(f"发送一次{label}，零次重复。")
            attempted = True
            await asyncio.wait_for(client.write_gatt_char(
                COMMAND_UUID, build_haptic(2), response=True), timeout=8)
            log(f"{label}写入已确认；等待设备完成应答（仍需佩戴者确认体感）。")
            result = await final_response(19, 2, 8)
            if result.result != 1 or result.body[:2] != b"\x01\x05":
                raise RuntimeError(f"{label}未确认完成：{result.result_name} / {result.body.hex()}")
            log(f"设备报告{label}已完成；请确认是否实际感觉到震动。")
        finally:
            # A timed-out write may still have applied: never repeat the buzz.
            if attempted and client.is_connected:
                try:
                    await asyncio.wait_for(client.write_gatt_char(
                        COMMAND_UUID, stop_frame(3), response=True), timeout=5)
                    log("已发送停止指令。")
                    result = await final_response(122, 3, 3)
                    log(f"停止应答：{result.result_name}。")
                except Exception as error:
                    log(f"停止应答未确认：{type(error).__name__}: {error}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="已确认 WHOOP 的 Mac 蓝牙 UUID")
    parser.add_argument("--serial", required=True, help="必须与设备读回序列号一致")
    parser.add_argument("--buzz", action="store_true", help="显式执行一次震动；默认仅检查身份")
    parser.add_argument("--pattern", choices=("notification", "one-second"),
                        default="notification", help="短震，或原厂标称 1000 ms 的单次波形")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        log(f"本次测试停止：{type(error).__name__}: {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
