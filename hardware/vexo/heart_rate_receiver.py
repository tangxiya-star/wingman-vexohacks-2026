"""Receive a confirmed Bluetooth heart-rate source on the Mac, without a band."""

import argparse
import asyncio
import sys

from bleak.exc import BleakError

from heart_rate import (
    HeartRateState,
    choose_source,
    log,
    positive_float,
    receive_heart_rate,
    scan_sources,
)


class ConsoleHeartRateState(HeartRateState):
    def __init__(self, label):
        super().__init__()
        self.label = label
        self._reported_reason = None

    def clear(self, reason):
        super().clear(reason)
        if reason != self._reported_reason:
            log(f"[{self.label}] 无有效心率：{reason}")
            self._reported_reason = reason

    def receive(self, data, now=None):
        super().receive(data, now)
        if self.bpm is not None:
            # Print each valid notification, including a freshly repeated BPM.
            log(f"[{self.label}] {self.bpm} BPM")
            self._reported_reason = None


async def check_staleness(state, stale_after):
    while True:
        state.current_bpm(stale_after)
        await asyncio.sleep(0.2)


async def stop_tasks(tasks):
    for task in tasks:
        task.cancel()
    done, pending = await asyncio.wait(tasks, timeout=5)
    if pending:
        # A stalled BLE disconnect must not hold the receiver open indefinitely.
        for task in pending:
            task.cancel()
        finished, pending = await asyncio.wait(pending, timeout=1)
        done |= finished
    for task in done:
        if not task.cancelled():
            task.exception()
    if pending:
        log("蓝牙断连清理仍未完成，已取消等待。")


async def run(args):
    log(f"扫描标准蓝牙心率广播 {args.scan_seconds:g} 秒…")
    found = await scan_sources(args.scan_seconds)
    if args.scan:
        for device, advert in found:
            name = advert.local_name or device.name or "未命名心率源"
            print(f"{name}\t{device.address}", flush=True)
        if not found:
            log("未发现标准心率广播，请在心率设备的 App 中开启心率广播。")
        return 0

    selected = choose_source(found, args.source)
    device, advert = selected
    name = advert.local_name or device.name or "未命名心率源"
    label = f"{args.label} · {name}" if args.label else name
    log(f"Mac 心率输入：{label} [{device.address}]；Ctrl+C 结束。")
    state = ConsoleHeartRateState(label)
    tasks = [
        asyncio.create_task(receive_heart_rate(selected, state, args.scan_seconds,
                                             address=args.source)),
        asyncio.create_task(check_staleness(state, args.stale_after)),
    ]
    try:
        done, _ = await asyncio.wait(tasks, timeout=args.seconds,
                                     return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        await stop_tasks(tasks)
        log(f"[{label}] Mac 心率接收已停止。")
    return 0


def arguments():
    parser = argparse.ArgumentParser(description="标准蓝牙心率 → Mac 实时 BPM；不连接 Vexo，也不保存心率历史。")
    parser.add_argument("--scan", action="store_true", help="只扫描广播名称和 ID，不连接或读取心率")
    parser.add_argument("--source", help="已确认属于本人或朋友的心率源设备 ID")
    parser.add_argument("--seconds", type=positive_float, help="接收指定秒数后退出")
    parser.add_argument("--scan-seconds", type=positive_float, default=10, help="扫描秒数，默认 10")
    parser.add_argument("--stale-after", type=positive_float, default=15, help="通知停更多少秒后报告无有效心率，默认 15")
    parser.add_argument("--label", help="显示标签，例如“朋友的 WHOOP”，便于区分多路心率")
    args = parser.parse_args()
    if args.scan and args.source:
        parser.error("--scan 仅发现广播；连接时去掉 --scan 并使用 --source")
    if not args.scan and not args.source:
        parser.error("连接必须用 --source 指定已确认的设备 ID；可先用 --scan 发现广播")
    return args


def main():
    try:
        return asyncio.run(run(arguments()))
    except KeyboardInterrupt:
        return 0
    except (BleakError, RuntimeError, OSError, TimeoutError) as error:
        print(f"问题：{error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
