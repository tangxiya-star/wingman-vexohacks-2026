import argparse
import sys
from itertools import cycle
from pathlib import Path

from band_config import BAND_NUMBER

sys.path.insert(0, str(Path(__file__).resolve().parent / "vexo-open-kit" / "python"))
from vexo_open.sync import Band

def main():
    parser = argparse.ArgumentParser(description="单敲 Vexo Open 手环切换 LED 颜色。")
    transport = parser.add_mutually_exclusive_group()
    transport.add_argument("--sim", dest="mode", action="store_const", const="sim", help="使用模拟手环")
    transport.add_argument("--usb", dest="mode", action="store_const", const="serial", help="通过 USB 数据线连接")
    parser.add_argument("--seconds", type=float, help="运行指定秒数后退出")
    parser.set_defaults(mode="ble")
    args = parser.parse_args()

    colours = cycle([("紫色", "#a855f7"), ("绿色", "#22c55e")])
    print(f"正在连接 Vexo-HACK-{BAND_NUMBER:02d}（{args.mode}）…", flush=True)
    with Band.connect(BAND_NUMBER, transport=args.mode, set_clock=False) as band:
        name, colour = next(colours)
        band.set_led(colour)

        @band.on("tap")
        def change_colour(_event):
            name, colour = next(colours)
            band.set_led(colour)
            print(f"收到单敲，LED 已切换为{name}（{colour}）", flush=True)

        band.configure(events=True)
        print(f"已连接 {band.name}，当前为{name}。单敲切换颜色，Ctrl+C 退出。", flush=True)
        if not band.wait(args.seconds):
            print("手环已断开。", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
