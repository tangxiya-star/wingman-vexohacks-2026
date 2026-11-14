"""Vexo 芯片温度灯光演示；不是皮温或体温。

请先退出心率程序、敲击 demo 和 Dashboard；它们不能同时控制同一只手环。
首次温度读数作为芯片基线，基线 -2°C 到 +2°C 映射为蓝 → 绿 → 红。
"""

import argparse
import colorsys
import math
import sys
from pathlib import Path

from band_config import BAND_NUMBER

sys.path.insert(0, str(Path(__file__).resolve().parent / "vexo-open-kit" / "python"))
from vexo_open.sync import Band


def colour_for_delta(delta: float) -> str:
    """Illustrative relative chip temperature, not a body-temperature threshold."""
    position = min(1.0, max(0.0, (delta + 2.0) / 4.0))
    rgb = colorsys.hsv_to_rgb((1.0 - position) * 2.0 / 3.0, 1.0, 1.0)
    return "#" + "".join(f"{round(channel * 255):02x}" for channel in rgb)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    transport = parser.add_mutually_exclusive_group()
    transport.add_argument("--sim", dest="mode", action="store_const", const="sim",
                           help="使用模拟手环和模拟芯片温度")
    transport.add_argument("--usb", dest="mode", action="store_const", const="serial",
                           help="通过 USB 数据线连接")
    parser.add_argument("--seconds", type=float, help="运行指定秒数后退出（默认 Ctrl+C 退出）")
    parser.set_defaults(mode="ble")
    args = parser.parse_args()
    if args.seconds is not None and (not math.isfinite(args.seconds) or args.seconds <= 0):
        parser.error("--seconds 必须是大于 0 的有限数值")

    print("【芯片温度演示，非皮温/体温】请先退出心率程序、敲击 demo 和 Dashboard。", flush=True)
    if args.mode == "sim":
        print("当前为模拟模式，温度读数也是模拟数据。", flush=True)
    print(f"正在连接 Vexo-HACK-{BAND_NUMBER:02d}（{args.mode}）…", flush=True)
    try:
        with Band.connect(BAND_NUMBER, transport=args.mode, set_clock=False) as band:
            baseline = None
            band.configure(audio=False, mic_level=False)
            band.set_led("#000000")

            @band.on("temperature")
            def show_temperature(event):
                nonlocal baseline
                celsius = event.celsius
                if baseline is None:
                    baseline = celsius
                    print(f"芯片基线：{baseline:.2f}°C；基线 ±2°C 映射蓝 → 绿 → 红。", flush=True)
                delta = celsius - baseline
                colour = colour_for_delta(delta)
                band.set_led(colour)
                print(
                    f"【芯片温度演示，非皮温/体温】{celsius:.2f}°C，"
                    f"相对芯片基线 {delta:+.2f}°C，LED {colour}",
                    flush=True,
                )

            band.configure(temperature=1)
            print(f"已连接 {band.name}，每秒更新；Ctrl+C 退出并关闭灯光。", flush=True)
            if not band.wait(args.seconds):
                print("手环已断开。", file=sys.stderr)
                return 1
    except KeyboardInterrupt:
        pass
    print("温度演示已停止。", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
