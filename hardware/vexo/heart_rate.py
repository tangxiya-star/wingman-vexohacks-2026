"""BLE heart rate sets a stepped light tempo; a double tap can replay colour demo."""

import argparse
import asyncio
import sys
import time
from dataclasses import dataclass
from itertools import cycle
from pathlib import Path

from band_config import BAND_NUMBER
from hr_measurement import bpm_period_ms, display_period_ms, parse_heart_rate
from temperature_animation import TemperatureAnimation
from temperature_colour import TemperatureColour
from raise_hand_runtime import RaiseHandMonitor
from motion_state import RUNTIME

sys.path.insert(0, str(Path(__file__).resolve().parent / "vexo-open-kit" / "python"))
from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError
from vexo_open import Band, VexoError
from vexo_open.transports.sim import SimTransport

HEART_RATE_SERVICE = "0000180d-0000-1000-8000-00805f9b34fb"
HEART_RATE_MEASUREMENT = "00002a37-0000-1000-8000-00805f9b34fb"


def log(message):
    print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)


@dataclass
class HeartRateState:
    bpm: int | None = None
    received_at: float | None = None
    reason: str = "等待真实心率"

    def clear(self, reason):
        self.bpm = None
        self.received_at = None
        self.reason = reason

    def receive(self, data, now=None):
        try:
            measurement = parse_heart_rate(bytes(data))
            if measurement.contact is False:
                self.clear("心率源报告未接触皮肤")
                return
            bpm_period_ms(measurement.bpm)
        except ValueError as error:
            self.clear(f"无有效心率：{error}")
            return
        self.bpm = measurement.bpm
        # HRS has no measurement timestamp. This is packet arrival time only.
        self.received_at = time.monotonic() if now is None else now
        self.reason = "正在接收"

    def current_bpm(self, stale_after, now=None):
        now = time.monotonic() if now is None else now
        if self.received_at is not None and now - self.received_at >= stale_after:
            self.clear(f"超过 {stale_after:g} 秒没有收到心率数据")
        return self.bpm


class PulseDisplay:
    def __init__(self, band, state, stale_after=15, brightness=1.0, temperature=None,
                 animation=None):
        if temperature is not None and animation is not None:
            raise ValueError("芯片温度和模拟颜色动画只能选择一种")
        self.band = band
        self.state = state
        self.stale_after = stale_after
        self.brightness = brightness
        self.temperature = temperature
        self.animation = animation
        self.last_setting = None
        self.last_status = None
        self._led_timeouts = 0

    async def update(self, now=None):
        bpm = self.state.current_bpm(self.stale_after, now)
        period = display_period_ms(bpm) if bpm is not None else None
        colour = (self.animation.colour(now) if self.animation is not None else
                  self.temperature.colour(now) if self.temperature is not None else "#ff0000")
        # BLE callbacks can update or invalidate the sample while LED I/O awaits.
        temperature_celsius = self.temperature.celsius if self.temperature is not None else None
        temperature_delta = self.temperature.delta if self.temperature is not None else None
        setting = (period, colour) if period is not None and colour is not None else None
        if setting != self.last_setting:
            if setting is None:
                await self.band.led_off()
            else:
                await self.band.set_led(colour, pattern="blink", period=period,
                                        brightness=self.brightness)
                led = await self.band.get_led()
                rgb = tuple(int(colour[index:index + 2], 16) for index in (1, 3, 5))
                if (led.r, led.g, led.b, led.pattern, led.period) != (*rgb, "blink", period):
                    raise RuntimeError("Vexo 返回的灯光设置与心率不一致，请关闭其他控灯程序。")
                if abs(led.brightness - self.brightness) > 1 / 255:
                    raise RuntimeError("Vexo 返回的亮度与请求不一致，请关闭其他控灯程序。")
            self.last_setting = setting
        if bpm is None:
            status = f"灯光关闭：{self.state.reason}"
        elif colour is None:
            status = "灯光关闭：等待有效芯片温度（演示，非皮温/体温）"
        else:
            status = f"{bpm} BPM → 分档显示周期 {period} ms，半亮半灭，亮度 {self.brightness:.0%}，颜色 {colour}"
            if self.temperature is not None:
                status += (f"；芯片 {temperature_celsius:.2f}°C，"
                           f"较基线 {temperature_delta:+.2f}°C（非皮温/体温）")
            elif self.animation is not None:
                status += "；颜色为温度动画演示（非测温）"
        if status != self.last_status:
            log(status)
            self.last_status = status

    async def update_with_retry(self, now=None):
        try:
            await self.update(now)
        except VexoError as error:
            if (error.code != "timeout" or not self.band.connected
                    or error.message.startswith("The band answered")):
                raise
            # A missing response does not prove LED_SET was not applied.
            # None means confirmed off, so use a distinct unknown cache value.
            self.last_setting = object()
            self._led_timeouts += 1
            if self._led_timeouts >= 3:
                raise
            log(f"灯光应答超时（{self._led_timeouts}/3），动作接收继续，稍后重试最新灯光状态。")
            return False
        if self._led_timeouts:
            log("灯光应答已恢复，设置已重新确认。")
        self._led_timeouts = 0
        return True

    async def run(self):
        while self.band.connected:
            updated = await self.update_with_retry()
            await asyncio.sleep(0.2 if updated else 0.5)
        raise RuntimeError(f"Vexo-HACK-{BAND_NUMBER:02d} 蓝牙已断开。双敲开启连接窗口后重新运行。")


async def enable_temperature_animation(band, animation):
    def restart_animation(_event):
        animation.restart()
        log("收到双敲：温度颜色演示从蓝色重播，蓝→青→黄→橙→红，各 3 秒，15 秒后回蓝。")

    band.on("double-tap", restart_animation)
    events = await band.get_events()
    if "double-tap" not in events.kinds:
        await band.set_events(kinds=[*events.kinds, "double-tap"])
    await band.configure(events=True, temperature=False)


async def scan_sources(seconds):
    # This scan is for standard heart-rate services, never for other Vexo bands.
    found = await BleakScanner.discover(timeout=seconds, return_adv=True,
                                        service_uuids=[HEART_RATE_SERVICE])
    return [(device, advert) for device, advert in found.values()
            if HEART_RATE_SERVICE in [uuid.lower() for uuid in advert.service_uuids]]


def source_name(item):
    device, advert = item
    return advert.local_name or device.name or "未命名心率源"


def choose_source(found, address=None):
    if address:
        matches = [item for item in found if item[0].address.casefold() == address.casefold()]
    else:
        matches = [item for item in found
                   if source_name(item).casefold() == "heartcast"
                   or source_name(item).casefold().startswith("heartcast-")]
        if matches:
            devices = "\n".join(f"  {source_name(item)}  {item[0].address}" for item in matches)
            raise RuntimeError("已发现 HeartCast，但尚未确认哪台属于你，未建立连接。"
                               "请确认自己的设备 ID，再用 --source 指定：\n" + devices)
    if not matches:
        raise RuntimeError("没有找到指定蓝牙心率源。请开启该设备的心率广播并靠近 Mac。"
                           "HeartCast 需从 Watch 点 Start、手机 App 保持前台；"
                           "WHOOP 需在设备设置开启 Heart Rate Broadcast。"
                           "用 --scan 查看广播，再用 --source 指定已确认的设备 ID。")
    if len(matches) > 1:
        raise RuntimeError("所选设备 ID 不唯一，未建立连接。请重新扫描。")
    return matches[0]


async def receive_heart_rate(initial, state, scan_seconds, address=None):
    if initial is not None:
        device, _ = initial
        address = device.address
        label = source_name(initial)
    else:
        if not address:
            raise RuntimeError("等待心率源前必须指定已确认属于自己的设备 ID。")
        label = "已确认的蓝牙心率源"
    first = initial is not None
    while True:
        state.clear("等待心率源连接")
        try:
            if not first:
                found = await scan_sources(scan_seconds)
                device, _ = choose_source(found, address)
            first = False
            disconnected = asyncio.Event()
            def source_disconnected(_client):
                state.clear("心率源已断开")
                disconnected.set()

            log(f"连接心率源 {label} [{address}]")
            async with BleakClient(device, disconnected_callback=source_disconnected, timeout=20) as client:
                service = client.services.get_service(HEART_RATE_SERVICE)
                if service is None or service.get_characteristic(HEART_RATE_MEASUREMENT) is None:
                    raise RuntimeError("所选设备没有标准心率测量特征。")
                await client.start_notify(HEART_RATE_MEASUREMENT, lambda _char, data: state.receive(data))
                log("心率通知已订阅；正在等待 BPM。")
                await disconnected.wait()
        except (BleakError, TimeoutError, OSError, RuntimeError) as error:
            log(f"心率源暂不可用：{error}")
        finally:
            state.clear("心率源已断开")
        log("3 秒后重连同一个心率源；不会切换到其他设备。")
        await asyncio.sleep(3)


async def simulated_heart_rate(state, fixed_bpm):
    log("【模拟心率输入】这不是 Apple Watch 的测量值。")
    for bpm in cycle([fixed_bpm] if fixed_bpm else [60, 90, 120, 75]):
        # Pass through the real BLE decoder; refresh identical readings too.
        payload = bytes([1]) + bpm.to_bytes(2, "little")
        for _ in range(4):
            state.receive(payload)
            await asyncio.sleep(1)


async def cleanup(band, tasks):
    for task in tasks:
        task.cancel()
    # A slow heart-rate peripheral must not delay stopping the Vexo light.
    if len(tasks) > 1:
        await asyncio.wait([tasks[1]], timeout=3)
    try:
        if band.connected:
            try:
                await asyncio.wait_for(band.led_off(), timeout=3)
            except (VexoError, BleakError, OSError, TimeoutError) as error:
                log(f"关闭灯光时连接不可用：{error}")
    finally:
        try:
            await asyncio.wait_for(band.disconnect(), timeout=5)
        except (VexoError, BleakError, OSError, TimeoutError) as error:
            log(f"手环断连清理未得到确认：{error}")
        finally:
            if tasks:
                done, pending = await asyncio.wait(tasks, timeout=3)
                for task in pending:
                    task.cancel()
                for task in done:
                    if not task.cancelled():
                        task.exception()
                if pending:
                    log("心率源断连清理超时，已取消等待。")


async def run(args):
    if args.scan:
        log(f"扫描标准蓝牙心率广播 {args.scan_seconds:g} 秒（不连接、不读取心率）…")
        found = await scan_sources(args.scan_seconds)
        for item in found:
            print(f"{source_name(item)}\t{item[0].address}", flush=True)
        if not found:
            log("未发现心率广播。手机 HeartCast 需在前台，Watch 上点 Start。")
        return 0

    simulated = args.sim or args.demo_bpm is not None
    selected = None
    if not simulated:
        log("查找 HeartCast 标准心率广播…")
        try:
            selected = choose_source(await scan_sources(args.scan_seconds), args.source)
        except RuntimeError:
            if not (args.raise_hand and args.source):
                raise
            log("已确认的心率源暂未广播；先开启手环动作识别，后台继续重连该心率源。")
        if selected is not None:
            log(f"锁定心率源：{source_name(selected)} [{selected[0].address}]")
            log(f"下次可用 --source {selected[0].address} 锁定同一设备。")
    mode = "sim" if args.sim else "serial" if args.usb else "ble"
    log(f"连接 Vexo-HACK-{BAND_NUMBER:02d}（{mode}）…")
    transport = SimTransport(BAND_NUMBER, auto_tap=False) if args.sim else mode
    band = await Band.connect(BAND_NUMBER, transport=transport, set_clock=False)
    tasks = []
    monitor = None
    try:
        # SDK already verifies the reported band number before returning.
        await band.configure(audio=False, mic_level=False)
        await band.led_off()
        state = HeartRateState()
        temperature = TemperatureColour(warm_delta=args.temperature_span) if args.temperature else None
        animation = TemperatureAnimation() if args.temperature_demo else None
        if animation is not None:
            await enable_temperature_animation(band, animation)
            log("温度颜色是模拟动画：默认蓝色，双敲手环开始 15 秒演示；任何颜色下再次双敲都从蓝色重播。")
            if args.sim:
                log("【模拟手环】2 秒后注入一次双敲，用于预览完整动画。")
                transport.after(2, lambda: transport.tap("double-tap"))
        if temperature is not None:
            def receive_temperature(event):
                first = temperature.baseline is None
                if temperature.receive(event.celsius) and first:
                    log(f"芯片基线 {temperature.baseline:.2f}°C = 蓝色；"
                        f"升高 {args.temperature_span:g}°C → 红色。这是芯片温度演示，非皮温/体温。")

            band.on("temperature", receive_temperature)
            await band.configure(temperature=1)
        display = PulseDisplay(band, state, args.stale_after, args.brightness, temperature,
                               animation=animation)
        if args.raise_hand:
            events_path = (args.events_file or Path(__file__).resolve().parent / "runtime" /
                           ("sim_hand_events.jsonl" if args.sim else "hand_events.jsonl"))
            state_path = RUNTIME / f"{'sim_' if args.sim else ''}motion_state_{BAND_NUMBER}.json"
            monitor = RaiseHandMonitor(band, events_path, log, simulated=args.sim,
                                       state_path=state_path)
            await monitor.start()
            log(f"Mac 动作事件记录：{events_path}")
        source = (simulated_heart_rate(state, args.demo_bpm) if simulated else
                  receive_heart_rate(selected, state, args.scan_seconds, address=args.source))
        tasks = [asyncio.create_task(source), asyncio.create_task(display.run())]
        if monitor is not None:
            tasks.append(asyncio.create_task(monitor.run()))
        colour_mode = ("双敲播放温度颜色动画" if animation is not None else
                       "芯片温度决定颜色" if temperature is not None else "红灯")
        log(f"已就绪：心率每 5 BPM 一档，显示周期 1.0～0.1 秒；{colour_mode}。"
            "这是放大的快慢提示，非真实每搏同步。Ctrl+C 结束。")
        done, _ = await asyncio.wait(tasks, timeout=args.seconds, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        try:
            if monitor is not None:
                monitor.close()
        finally:
            await cleanup(band, tasks)
        log("心率程序已停止。")
    return 0


def positive_float(value):
    value = float(value)
    if not 0 < value < float("inf"):
        raise argparse.ArgumentTypeError("请输入大于 0 的有限数字")
    return value


def arguments():
    parser = argparse.ArgumentParser(description="Apple Watch 心率分档控制 Vexo 快慢；可选双敲温度动画。请关闭其他控灯程序。")
    parser.add_argument("--scan", action="store_true", help="只列出心率广播，不连接设备")
    parser.add_argument("--source", help="确认属于自己的心率源设备 ID；未指定时只发现候选、不连接")
    parser.add_argument("--scan-seconds", type=positive_float, default=10, help="扫描秒数，默认 10")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--sim", action="store_true", help="模拟心率和手环，不使用蓝牙")
    mode.add_argument("--usb", action="store_true", help="Vexo 用 USB；心率仍用蓝牙")
    parser.add_argument("--demo-bpm", type=int, help="用明确标记的固定模拟 BPM 测试灯光（6..600）")
    parser.add_argument("--seconds", type=positive_float, help="运行指定秒数后结束")
    parser.add_argument("--stale-after", type=positive_float, default=15, help="无心率通知超过此秒数时停灯，默认 15")
    parser.add_argument("--brightness", type=float, default=1.0, help="灯光亮度 0..1，默认 1（最大）")
    parser.add_argument("--raise-hand", action="store_true", help="识别从下垂快速举过头顶，向 Mac 输出 hand_raise 事件")
    parser.add_argument("--events-file", type=Path, help="抬手事件 JSONL 路径，默认 runtime/hand_events.jsonl")
    colour = parser.add_mutually_exclusive_group()
    colour.add_argument("--temperature-demo", action="store_true", help="平时蓝色；每次双敲从蓝色重播，蓝青黄橙红各 3 秒")
    colour.add_argument("--temperature", action="store_true", help="可选实测芯片温度决定颜色，与模拟温度动画互斥")
    parser.add_argument("--temperature-span", type=positive_float, default=1.0,
                        help="从蓝色到红色需要比初始芯片温度升高多少 °C，默认 1；仅 --temperature 生效")
    args = parser.parse_args()
    if not 0 <= args.brightness <= 1:
        parser.error("--brightness 必须在 0..1")
    if args.demo_bpm is not None:
        try:
            bpm_period_ms(args.demo_bpm)
        except ValueError as error:
            parser.error(str(error))
    if args.source and (args.sim or args.demo_bpm is not None):
        parser.error("真实 --source 不能与模拟心率输入同时使用")
    if args.events_file is not None and not args.raise_hand:
        parser.error("--events-file 需与 --raise-hand 一起使用")
    if args.scan and (args.sim or args.demo_bpm is not None or args.usb or args.temperature
                      or args.temperature_demo or args.raise_hand):
        parser.error("--scan 仅用于真实心率广播发现")
    return args


def main():
    try:
        return asyncio.run(run(arguments()))
    except KeyboardInterrupt:
        return 0
    except (VexoError, BleakError, RuntimeError, OSError, TimeoutError) as error:
        print(f"问题：{error}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
