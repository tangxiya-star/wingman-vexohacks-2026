"""A loopback-only heart-rate page, optionally driving one selected Vexo band."""

import argparse
import asyncio
import json
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from bleak.exc import BleakError

from heart_rate import (HeartRateState, choose_source, log, positive_float,
                        receive_heart_rate, scan_sources)
from whoop_band import band_worker
from motion_state import RUNTIME, read_motion_states


class DashboardState(HeartRateState):
    def __init__(self, source_name, stale_after=15):
        super().__init__()
        self.source_name = source_name
        self.stale_after = stale_after
        self._lock = threading.RLock()
        self._history = deque(maxlen=180)
        self._last_received_at = None
        self._status = "waiting"
        self._seen_live = False

    def clear(self, reason):
        with self._lock:
            super().clear(reason)
            if "断开" in reason:
                self._status = "disconnected"
            elif reason.startswith("超过"):
                self._status = "stale"
            elif reason == "等待心率源连接":
                self._status = "disconnected" if self._seen_live else "waiting"
            else:
                self._status = "stale" if self._seen_live else "waiting"

    def receive(self, data, now=None, wall_now=None):
        with self._lock:
            super().receive(data, now)
            if self.bpm is not None:
                stamp = time.time() if wall_now is None else wall_now
                self._last_received_at = stamp
                self._history.append({"time": stamp, "bpm": self.bpm})
                self._status = "live"
                self._seen_live = True
                self._prune(stamp)

    def _prune(self, wall_now):
        while self._history and self._history[0]["time"] < wall_now - 60:
            self._history.popleft()

    def current_bpm(self, stale_after, now=None):
        # The LED loop and HTTP snapshot read the same state; expiration can
        # call clear(), so both paths share the same reentrant lock.
        with self._lock:
            return super().current_bpm(stale_after, now)

    def snapshot(self, now=None, wall_now=None):
        with self._lock:
            wall_now = time.time() if wall_now is None else wall_now
            self.current_bpm(self.stale_after, now)
            self._prune(wall_now)
            return {
                "source_name": self.source_name,
                "status": self._status,
                "bpm": self.bpm,
                "last_received_at": self._last_received_at,
                "server_time": wall_now,
                "history": [dict(point) for point in self._history],
                "message": "实时接收中" if self._status == "live" else self.reason,
            }


def make_server(state, port=8765, static_dir=None, motion_dir=None):
    static_dir = Path(static_dir) if static_dir is not None else Path(__file__).parent / "dashboard"
    routes = {
        "/": ("index.html", "text/html; charset=utf-8"),
        "/app.js": ("app.js", "text/javascript; charset=utf-8"),
        "/style.css": ("style.css", "text/css; charset=utf-8"),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            route = urlsplit(self.path).path
            if route == "/api/motion":
                body = json.dumps(read_motion_states(motion_dir), ensure_ascii=False,
                                  allow_nan=False).encode("utf-8")
                self._respond(200, body, "application/json; charset=utf-8", "no-store")
            elif route == "/api/state":
                body = json.dumps(state.snapshot(), ensure_ascii=False,
                                  allow_nan=False).encode("utf-8")
                self._respond(200, body, "application/json; charset=utf-8", "no-store")
            elif route in routes:
                filename, mime = routes[route]
                try:
                    body = (static_dir / filename).read_bytes()
                except OSError:
                    self._respond(404, b"Not found", "text/plain; charset=utf-8", "no-store")
                else:
                    self._respond(200, body, mime, "no-cache")
            else:
                self._respond(404, b"Not found", "text/plain; charset=utf-8", "no-store")

        def _respond(self, status, body, mime, cache_control):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache_control)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, _format, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


async def source_worker(state, source, scan_seconds):
    while True:
        try:
            found = await scan_sources(scan_seconds)
            try:
                initial = choose_source(found, source)
            except RuntimeError:
                initial = None
            await receive_heart_rate(initial, state, scan_seconds, address=source)
        except (BleakError, OSError, RuntimeError, TimeoutError) as error:
            state.clear("心率源已断开，正在重连")
            log(f"心率源暂不可用：{error}")
            await asyncio.sleep(3)


async def run(args):
    state = DashboardState(args.name)
    server = make_server(state, args.port)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.2},
                              daemon=True, name="whoop-dashboard-http")
    thread.start()
    log(f"心率页面：http://127.0.0.1:{server.server_port} （仅本机可访问）")
    if getattr(args, "no_heart_rate", False):
        state.clear("心率接收暂停，手环动作和面板继续运行")
        log("心率接收暂停：未连接 WHOOP，手环动作和面板继续运行。")
        source_task = asyncio.create_task(asyncio.Event().wait())
    else:
        log(f"只接收已指定的心率源 {args.source}；最近一分钟数据仅保存在内存。")
        source_task = asyncio.create_task(source_worker(state, args.source, args.scan_seconds))
    tasks = [source_task]
    if args.band is not None:
        tasks.append(asyncio.create_task(band_worker(
            state, args.band, args.scan_seconds,
            raise_hand=args.raise_hand, events_path=args.events_file,
            state_path=RUNTIME / f"motion_state_{args.band}.json")))
    try:
        done, _ = await asyncio.wait([source_task], return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        # The optional band worker gets time to turn its LED off and disconnect.
        done, pending = await asyncio.wait(tasks, timeout=10)
        if pending:
            for task in pending:
                task.cancel()
            more_done, pending = await asyncio.wait(pending, timeout=1)
            done.update(more_done)
        for task in done:
            if not task.cancelled():
                task.exception()
        state.clear("心率源已断开")
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(timeout=1)
        log("心率页面已停止。")
    return 0


def arguments():
    parser = argparse.ArgumentParser(description="在 localhost 查看已确认蓝牙设备的实时心率。")
    parser.add_argument("--source", required=True, help="已确认设备的 Mac 蓝牙 UUID")
    parser.add_argument("--name", default="WHOOP", help="页面显示的设备名称")
    parser.add_argument("--port", type=int, default=8765, help="本机 HTTP 端口，默认 8765")
    parser.add_argument("--scan-seconds", type=positive_float, default=10)
    parser.add_argument("--band", type=int, help="可选：同步灯光的已确认 Vexo 编号")
    parser.add_argument("--no-heart-rate", action="store_true",
                        help="临时让出 WHOOP 连接，仅运行网页和 Vexo 动作接收")
    parser.add_argument("--raise-hand", action="store_true",
                        help="在同一只 Vexo 上训练并识别抬手动作，需要 --band")
    parser.add_argument("--events-file", type=Path,
                        help="抬手事件 JSONL 路径，默认 runtime/hand_events_编号.jsonl")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port 必须在 1..65535")
    if args.band is not None and not 1 <= args.band <= 999:
        parser.error("--band 必须在 1..999")
    if args.raise_hand and args.band is None:
        parser.error("--raise-hand 需要 --band 指定自己的手环编号")
    if args.events_file is not None and not args.raise_hand:
        parser.error("--events-file 需要 --raise-hand")
    if args.raise_hand and args.events_file is None:
        args.events_file = Path(__file__).resolve().parent / "runtime" / f"hand_events_{args.band}.jsonl"
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
