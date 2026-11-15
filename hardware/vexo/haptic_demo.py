"""Local dating-demo coordinator. No haptic is sent merely by starting it.

WHOOP RSSI measures its link to this Mac, never the distance between two people.
The Watch wearer stands by the Mac for this demonstration.
"""

import argparse
import asyncio
from collections import deque
import json
import math
import os
from pathlib import Path
import secrets
import statistics
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from motion_state import RUNTIME, read_motion_states, request_motion_reset

HEART_RATE_STALE_AFTER = 15


class Proximity:
    """Median/EMA signal strength, with a stable, hysteretic cadence band."""

    LABELS = ("Far", "Medium", "Close", "Very close")
    INTERVALS = (2.5, 1.6, 1.0, 0.6)
    CUTS = (.30, .55, .80)

    def __init__(self):
        self.far, self.near = -80.0, -50.0
        self.calibrations = set()
        self.clear()

    def clear(self):
        self.samples = deque(maxlen=5)
        self.raw = self.smooth = self.updated = None
        self.band = 0
        self.candidate = None
        self.candidate_since = None

    def feed(self, rssi, now):
        if (isinstance(rssi, bool) or not isinstance(rssi, (int, float))
                or not math.isfinite(rssi) or not -110 <= rssi <= -10):
            raise ValueError("Invalid RSSI")
        if self.updated is not None and now - self.updated > 2.5:
            self.clear()
        self.raw, self.updated = rssi, now
        self.samples.append(float(rssi))
        median = statistics.median(self.samples)
        self.smooth = median if self.smooth is None else .35 * median + .65 * self.smooth
        level = self.level
        desired = sum(level >= cut for cut in self.CUTS)
        # Roughly 3 dB hysteresis with the initial 30 dB calibration span.
        margin = 3.0 / (self.near - self.far)
        if desired > self.band and level < self.CUTS[self.band] + margin:
            desired = self.band
        elif desired < self.band and level > self.CUTS[self.band - 1] - margin:
            desired = self.band
        if desired == self.band:
            self.candidate = self.candidate_since = None
        elif self.candidate != desired:
            self.candidate, self.candidate_since = desired, now
        elif now - self.candidate_since >= 1.0:
            self.band = desired
            self.candidate = self.candidate_since = None

    @property
    def level(self):
        if self.smooth is None:
            return 0.0
        return max(0.0, min(1.0, (self.smooth - self.far) / (self.near - self.far)))

    def fresh(self, now):
        return self.updated is not None and 0 <= now - self.updated <= 2.5

    def calibrate(self, point, now):
        if point not in ("far", "near") or not self.fresh(now) or len(self.samples) < 3:
            raise ValueError("Stay in this position for a few seconds until the signal stabilizes, then calibrate.")
        value = statistics.median(self.samples)
        other = "near" if point == "far" else "far"
        far, near = (value, self.near) if point == "far" else (self.far, value)
        if other in self.calibrations and near - far < 10:
            raise ValueError("The far and near readings must differ by at least 10 dB. Increase the distance and try again.")
        if near - far < 10:
            # The first measurement may lie outside the illustrative defaults.
            far, near = (value, value + 30) if point == "far" else (value - 30, value)
        self.far, self.near = far, near
        self.calibrations.add(point)
        self.band = 0
        self.candidate = self.candidate_since = None

    def snapshot(self, now):
        fresh = self.fresh(now)
        return dict(raw_rssi=self.raw if fresh else None,
                    smoothed_rssi=round(self.smooth, 1) if fresh else None,
                    level=round(self.level, 3) if fresh else None,
                    band=self.band if fresh else None,
                    label=self.LABELS[self.band] if fresh else "Waiting for a new signal",
                    interval=self.INTERVALS[self.band] if fresh else None,
                    age=None if self.updated is None else round(now - self.updated, 2),
                    far_rssi=self.far, near_rssi=self.near,
                    calibrated=len(self.calibrations) == 2)


class WatchClient:
    def __init__(self, port=8766):
        self.base = f"http://127.0.0.1:{port}"

    def _request(self, path, body=None):
        headers = {"Content-Type": "application/json"}
        if body is not None:
            headers["X-Vexo-Token"] = (RUNTIME / "watch_haptics.token").read_text().strip()
        req = Request(self.base + path, data=None if body is None else json.dumps(body).encode(),
                      headers=headers, method="GET" if body is None else "POST")
        try:
            with urlopen(req, timeout=6) as response:
                return json.load(response)
        except HTTPError as error:
            return json.loads(error.read())

    async def status(self):
        return await asyncio.to_thread(self._request, "/status")

    async def buzz(self, kind, scope=None):
        return await asyncio.to_thread(self._request, "/buzz", {"kind": kind, "scope": scope})

    async def open_scope(self, scope):
        return await asyncio.to_thread(self._request, "/scope/open", {"scope": scope})

    async def cancel_scope(self, scope):
        return await asyncio.to_thread(self._request, "/scope/cancel", {"scope": scope})


class Demo:
    ACTIVE = {"preparing", "inviting", "awaiting_actions", "confirming", "approaching", "stopping"}

    def __init__(self, whoop, watch, *, directory=RUNTIME, clock=time.monotonic, apple_heart_rate=None):
        self.whoop, self.watch, self.directory, self.clock = whoop, watch, Path(directory), clock
        self.apple_heart_rate = apple_heart_rate
        self.phase, self.detail = "idle", "Waiting for both hand raises"
        self.matched = False
        self.auto_generation = None
        self.event_id = self.generation = None
        self.scope = None
        self.stop_task = None
        self.epoch = 0
        self.round_task = None
        self.phase_deadline = None
        self.paused_reason = None
        self.watch_state = {}
        self.motion = {}
        self.proximity = Proximity()
        self.last_delivery = {}
        self.history = deque(maxlen=60)
        self.running = True
        self._connecting = False
        self._seen_path = self.directory / "haptic_invitation_ids.json"
        try:
            ids = json.loads(self._seen_path.read_text())
            if not isinstance(ids, list) or any(not isinstance(v, str) for v in ids):
                raise ValueError("Invalid invitation ledger")
            self.seen = deque(ids[-512:], maxlen=512)
        except FileNotFoundError:
            self.seen = deque(maxlen=512)
        # A corrupt ledger fails startup rather than replaying a known invitation.

    def log(self, message):
        self.history.appendleft(dict(at=time.strftime("%H:%M:%S"), message=message))
        print(f"[{time.strftime('%H:%M:%S')}] {message}", flush=True)

    def snapshot(self):
        remaining = max(0, self.phase_deadline - self.clock()) if self.phase_deadline else None
        return dict(phase=self.phase, detail=self.detail, matched=self.matched, event_id=self.event_id,
                    generation=self.generation, watch=self.watch_state,
                    whoop={**self.whoop.snapshot(), "connecting": self._connecting},
                    motion=self.motion, proximity=self.proximity.snapshot(self.clock()),
                    last_delivery=self.last_delivery, remaining_seconds=round(remaining) if remaining is not None else None,
                    paused_reason=self.paused_reason, history=list(self.history))

    async def connect(self):
        if self._connecting:
            raise RuntimeError("WHOOP is already connecting.")
        if self.phase in self.ACTIVE or (self.round_task is not None and not self.round_task.done()):
            raise RuntimeError("Stop the current round before reconnecting.")
        self._connecting = True
        try:
            link = self.whoop.snapshot()
            if not link.get("ready"):
                self.proximity.clear()
                if link.get("connected"):
                    await self.whoop.disconnect()
            await self.whoop.connect()
            self.log("WHOOP identity verified and connected. No haptics sent.")
        finally:
            self._connecting = False
        return self.snapshot()

    async def keep_whoop_connected(self):
        delay = 2
        while self.running:
            idle = self.phase not in self.ACTIVE and (self.round_task is None or self.round_task.done())
            if idle and not self._connecting and not self.whoop.snapshot().get("ready"):
                try:
                    await self.connect()
                except Exception as error:
                    self.log("Could not reconnect WHOOP haptics: " + str(error))
                    delay = min(delay * 2, 20)
                else:
                    delay = 2
            await asyncio.sleep(delay)

    def _record_id(self, event_id):
        ids = deque(self.seen, maxlen=512)
        ids.append(event_id)
        self.directory.mkdir(exist_ok=True, parents=True)
        temporary = self._seen_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(list(ids)))
        temporary.replace(self._seen_path)
        self.seen = ids

    def _live_bands(self, generation=None):
        data = self.motion
        if data.get("mode") != "accel-latch":
            return None
        if generation is not None and data.get("reset_generation") != generation:
            return None
        bands = {v.get("band_number"): v for v in data.get("bands", [])}
        if set(bands) != {62, 77}:
            return None
        now = time.time()
        for value in bands.values():
            stamp = value.get("updated_at", 0)
            if not value.get("connected") or not value.get("ready") or not -1 <= now - stamp <= 2:
                return None
            if generation is not None and value.get("reset_generation") != generation:
                return None
        return bands

    async def invite(self, event_id, *, notify_before_gestures=True, detected_generation=None):
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 128:
            raise ValueError("event_id must be 1–128 characters.")
        if event_id in self.seen:
            return {"duplicate": True, "original_event_id": event_id, **self.snapshot()}
        if self.phase in self.ACTIVE or (self.round_task is not None and not self.round_task.done()):
            raise RuntimeError("Stop the current round before starting another.")
        if not self.whoop.snapshot().get("ready"):
            raise RuntimeError("Connect WHOOP haptics first.")
        if notify_before_gestures and not self.watch_state.get("watch_can_alert"):
            raise RuntimeError("Connect Apple Watch and open VexoWatch or enable notifications.")
        if not self._live_bands(detected_generation):
            raise RuntimeError("Both Vexo bands must be connected, still, and in quick-motion mode.")
        self._record_id(event_id)  # Durable deduplication precedes any side effect.
        self.epoch += 1
        self.event_id = event_id
        self.scope = secrets.token_hex(16)
        self.auto_generation = None
        self.matched = detected_generation is not None
        if self.matched:
            self.phase, self.detail = "confirming", "Both participants confirmed. Starting haptics."
        else:
            self.phase, self.detail = "preparing", "Resetting the round. Hold both bands still."
        self.last_delivery = {}
        self.paused_reason = None
        try:
            self.generation = detected_generation or request_motion_reset(self.directory)
        except OSError:
            self.phase, self.detail = "failed", "Could not start the gesture round. No notification was sent."
            raise
        self.log("Both hand raises detected. Match confirmed." if self.matched else "New round requested for both Vexo bands.")
        self.round_task = asyncio.create_task(self._run_round(self.epoch, notify_before_gestures))
        return self.snapshot()

    async def match_detected_gestures(self):
        generation = self.auto_generation
        if self.phase != "idle" or generation is None:
            return
        bands = self._live_bands(generation)
        if not bands or not all(band.get("triggered") for band in bands.values()):
            return
        self.auto_generation = None
        try:
            await self.invite(f"gesture-{generation}", notify_before_gestures=False,
                              detected_generation=generation)
        except (OSError, RuntimeError) as error:
            self.matched = True
            self.phase, self.detail = "failed", str(error)
            self.log(self.detail)

    def _check(self, epoch, require_watch=True):
        if epoch != self.epoch:
            raise asyncio.CancelledError()
        whoop = self.whoop.snapshot()
        if not whoop.get("connected"):
            raise RuntimeError("WHOOP disconnected. Round stopped.")
        if not whoop.get("ready"):
            raise RuntimeError("WHOOP haptics unavailable. Round stopped.")
        if require_watch and not self.watch_state.get("watch_connected"):
            raise RuntimeError("Apple Watch disconnected. Round stopped.")

    async def _deliver(self, epoch, kind, pattern, *, require_watch=True):
        self._check(epoch, require_watch)
        async def watch_send():
            self._check(epoch, require_watch)
            if not require_watch and not self.watch_state.get("watch_ready"):
                return {"result": "watch_inactive"}
            return await self.watch.buzz(kind, scope=self.scope)
        async def whoop_send():
            self._check(epoch, require_watch)
            return await self.whoop.buzz(pattern=pattern)
        results = await asyncio.gather(watch_send(), whoop_send(), return_exceptions=True)
        if epoch != self.epoch:
            raise asyncio.CancelledError()
        payload = {}
        for target, value in zip(("watch", "whoop"), results):
            payload[target] = {"error": str(value)} if isinstance(value, BaseException) else value
        self.last_delivery = payload
        if (isinstance(results[1], BaseException) or results[1].get("stop_confirmed") is not True
                or results[1].get("result") != "buzz_completed"):
            if not self.whoop.snapshot().get("connected"):
                raise RuntimeError("WHOOP disconnected. Round stopped.")
            raise RuntimeError("WHOOP could not confirm the haptics command. Round stopped.")
        self._check(epoch, require_watch)
        if not require_watch:
            self.paused_reason = (None if payload["watch"].get("result") == "play_called"
                                  else "Wake Apple Watch and open VexoWatch to join the next pulse.")
            return payload
        if (kind == "click" and not isinstance(results[0], BaseException)
                and (results[0].get("result") == "watch_inactive"
                     or "not ready" in results[0].get("error", ""))):
            # WHOOP may have completed this one pulse. It is never replayed.
            self.paused_reason = "Apple Watch haptics paused. Open VexoWatch to resume."
            return payload
        if isinstance(results[0], BaseException) or results[0].get("result") not in ("play_called", "notification_scheduled"):
            raise RuntimeError("Apple Watch could not confirm the haptics command. Round stopped.")
        return payload

    async def _run_round(self, epoch, notify_before_gestures):
        scope = self.scope
        require_watch = notify_before_gestures
        pulse_started = False
        try:
            try:
                opened = await self.watch.open_scope(scope)
            except (OSError, ValueError):
                opened = {}
            self._check(epoch, require_watch)
            if require_watch and opened.get("scope_status") != "opened":
                raise RuntimeError("Could not start the Apple Watch session. No notification was sent.")
            if not self.matched:
                self.phase_deadline = self.clock() + 10
                while self.clock() < self.phase_deadline:
                    self._check(epoch, require_watch)
                    if self.motion.get("reset_generation") not in (self.generation, None):
                        # Polling may still hold the pre-reset snapshot for one tick.
                        self.motion = read_motion_states(self.directory)
                    bands = self._live_bands(self.generation)
                    if bands and all(not v.get("triggered") for v in bands.values()):
                        break
                    await asyncio.sleep(.15)
                else:
                    raise RuntimeError("Both Vexo bands did not become ready. Hold them still and start a new round.")
                if notify_before_gestures:
                    self.phase, self.detail = "inviting", "Sending a match notification to both participants."
                    pulse_started = True
                    delivered = await self._deliver(epoch, "match_request", "one-second")
                    self.log("Match notification sent. Apple Watch: " + delivered["watch"]["result"] + ". WHOOP confirmed.")
                self.phase, self.detail = "awaiting_actions", "Waiting for each participant to raise their hand quickly once."
                self.phase_deadline = self.clock() + 90
                observed = set()
                while self.clock() < self.phase_deadline:
                    self._check(epoch, require_watch)
                    bands = self._live_bands(self.generation)
                    if not bands:
                        raise RuntimeError("Gesture data became unavailable or the round was reset. Round stopped.")
                    for number, band in bands.items():
                        if band.get("triggered") and number not in observed:
                            observed.add(number)
                            self.log(f"Hand raise received from Vexo {number}.")
                    if observed == {62, 77}:
                        break
                    await asyncio.sleep(.15)
                else:
                    raise RuntimeError("Timed out after 90 seconds waiting for both hand raises.")
            self.matched = True
            if self.motion.get("reset_generation") != self.generation:
                raise RuntimeError("Gestures reset for this round.")
            self.phase, self.detail = "confirming", "Both participants confirmed. Starting haptics."
            pulse_started = True
            pattern = "notification" if require_watch else "one-second"
            await self._deliver(epoch, "match_confirmed", pattern, require_watch=require_watch)
            self.log("Both gestures confirmed. Starting 60 seconds of proximity haptics.")
            self.phase, self.detail = "approaching", "Stay near the Mac while the WHOOP wearer moves closer."
            self.phase_deadline = self.clock() + 60
            next_pulse = self.clock() + self.proximity.INTERVALS[self.proximity.band]
            while self.clock() < self.phase_deadline:
                self._check(epoch, require_watch)
                if self.motion.get("reset_generation") != self.generation:
                    raise RuntimeError("Gestures reset. Proximity haptics stopped.")
                if require_watch and not self._live_bands(self.generation):
                    raise RuntimeError("A Vexo band disconnected. Proximity haptics stopped.")
                if not self.proximity.fresh(self.clock()):
                    raise RuntimeError("Bluetooth signal data expired. Proximity haptics stopped.")
                if require_watch and not self.watch_state.get("watch_ready"):
                    self.paused_reason = "Wake Apple Watch and open VexoWatch to resume proximity haptics."
                    next_pulse = self.clock() + .3
                    await asyncio.sleep(.15)
                    continue
                if require_watch:
                    self.paused_reason = None
                if self.clock() >= next_pulse:
                    started = self.clock()
                    interval = self.proximity.INTERVALS[self.proximity.band]
                    await self._deliver(epoch, "click", "notification", require_watch=require_watch)
                    # Missed periods are skipped. Completed calls never form a queue.
                    next_pulse = max(started + interval, self.clock() + .15)
                await asyncio.sleep(.1)
            self.phase, self.detail = "expired", "The 60-second proximity session ended."
            self.log(self.detail)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            if epoch == self.epoch:
                self.phase, self.detail = "failed", str(error)
                self.log(self.detail)
        finally:
            try:
                await self.watch.cancel_scope(scope)
            except Exception:
                pass
            if epoch == self.epoch:
                self.phase_deadline = None
                self.paused_reason = None
                if pulse_started:
                    try:
                        await self.whoop.stop()
                    except Exception:
                        pass

    async def stop(self):
        if self.stop_task and not self.stop_task.done():
            return await asyncio.shield(self.stop_task)
        self.phase, self.detail = "stopping", "Stopping haptics…"
        self.stop_task = asyncio.create_task(self._stop())
        return await asyncio.shield(self.stop_task)

    async def _stop(self):
        self.epoch += 1
        self.auto_generation = None
        self.phase, self.detail = "stopping", "Stopping haptics…"
        self.phase_deadline = None
        self.paused_reason = None
        if self.round_task and not self.round_task.done():
            self.round_task.cancel()
        if self.scope:
            try:
                result = await self.watch.cancel_scope(self.scope)
                if result.get("scope_status") != "cancelled":
                    self.log("Apple Watch did not confirm cancellation. Haptics scheduling stopped.")
            except Exception:
                self.log("Apple Watch is unavailable. Haptics scheduling stopped.")
        if self.round_task:
            await asyncio.gather(self.round_task, return_exceptions=True)
        try:
            await self.whoop.stop()
        except Exception as error:
            self.log("Haptics scheduling stopped. WHOOP did not confirm: " + type(error).__name__)
        self.phase, self.detail = "stopped", "Haptics stopped."
        self.log(self.detail)
        return self.snapshot()

    async def poll_status(self):
        while self.running:
            self.motion = read_motion_states(self.directory)
            try:
                self.watch_state = await self.watch.status()
            except Exception:
                self.watch_state = dict(watch_connected=False, watch_ready=False, watch_can_alert=False)
            await self.match_detected_gestures()
            await asyncio.sleep(.25)

    async def poll_rssi(self):
        while self.running:
            if self.whoop.snapshot().get("ready"):
                try:
                    rssi = await self.whoop.read_rssi()
                    self.proximity.feed(rssi, self.clock())
                except Exception:
                    pass  # Freshness expires independently; no fabricated value.
            else:
                self.proximity.clear()
            await asyncio.sleep(.5)

    async def dispatch(self, path, body):
        if path == "/api/wingman/reset":
            if body:
                raise ValueError("Reset Wingman takes no parameters.")
            if self.phase in self.ACTIVE or (self.round_task is not None and not self.round_task.done()):
                await self.stop()
            self.auto_generation = None
            request_motion_reset(self.directory)
            self.motion = read_motion_states(self.directory)
            self.matched = False
            self.phase, self.detail = "idle", "Waiting for both hand raises"
            await asyncio.to_thread(reset_wingman_session)
            return self.snapshot()
        if path == "/api/motion/reset":
            if body:
                raise ValueError("Reset gestures takes no parameters.")
            if self.phase in self.ACTIVE or (self.round_task is not None and not self.round_task.done()):
                raise RuntimeError("Stop the demo before resetting gestures.")
            self.auto_generation = request_motion_reset(self.directory)
            self.motion = read_motion_states(self.directory)
            self.matched = False
            self.phase, self.detail = "idle", "Waiting for both hand raises"
            return self.snapshot()
        if path == "/api/arm":
            return await self.invite(body.get("event_id"), notify_before_gestures=False)
        if path == "/api/invite":
            return await self.invite(body.get("event_id"))
        if path == "/api/stop":
            return await self.stop()
        if path == "/api/connect":
            return await self.connect()
        if path == "/api/calibrate":
            self.proximity.calibrate(body.get("point"), self.clock())
            self.log("Saved " + body["point"] + " signal calibration.")
            return self.snapshot()
        raise ValueError("Unknown endpoint")


def reset_wingman_session():
    request = Request("http://127.0.0.1:8787/reset", method="POST")
    try:
        with urlopen(request, timeout=4) as response:
            if response.read(32).strip() == b"ok":
                return
    except OSError:
        pass
    raise RuntimeError("Could not confirm the reset. Check that the local Wingman service is running.")


def read_whoop_bpm():
    try:
        with urlopen("http://127.0.0.1:8765/api/state", timeout=1) as response:
            reading = json.load(response)
    except (OSError, ValueError):
        return None
    if not isinstance(reading, dict):
        return None
    bpm = reading.get("bpm")
    if reading.get("status") == "live" and type(bpm) is int and bpm > 0:
        return bpm
    return None


def make_server(demo, loop, token, port):
    static = Path(__file__).parent / "haptics-dashboard"
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def allowed_host(self):
            return self.headers.get("Host") in (f"localhost:{port}", f"127.0.0.1:{port}")

        def respond(self, status, body, mime="application/json"):
            payload = json.dumps(body, ensure_ascii=False, allow_nan=False).encode() if mime == "application/json" else body
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; object-src 'none'")
            self.end_headers()
            try:
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            if not self.allowed_host():
                return self.respond(403, {"error": "localhost only"})
            path = urlsplit(self.path).path
            if path == "/api/session":
                return self.respond(200, {"token": token})
            if path == "/api/heart-rate":
                async def read_apple_bpm():
                    if demo.apple_heart_rate is not None:
                        return demo.apple_heart_rate.current_bpm(HEART_RATE_STALE_AFTER)

                future = asyncio.run_coroutine_threadsafe(read_apple_bpm(), loop)
                return self.respond(200, {"apple_watch_bpm": future.result(2), "bpm": read_whoop_bpm()})
            if path == "/api/state":
                async def read():
                    return demo.snapshot()
                future = asyncio.run_coroutine_threadsafe(read(), loop)
                return self.respond(200, future.result(3))
            route = {"/": ("index.html", "text/html; charset=utf-8"),
                     "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                     "/style.css": ("style.css", "text/css; charset=utf-8")}.get(path)
            if route:
                return self.respond(200, (static / route[0]).read_bytes(), route[1])
            return self.respond(404, {"error": "not_found"})

        def do_POST(self):
            if not self.allowed_host() or not secrets.compare_digest(self.headers.get("X-Vexo-Token", ""), token):
                return self.respond(403, {"error": "unauthorized"})
            if self.headers.get_content_type() != "application/json":
                return self.respond(415, {"error": "JSON required"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 1 <= size <= 2048:
                    raise ValueError("Invalid body size")
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError("JSON object required")
                future = asyncio.run_coroutine_threadsafe(demo.dispatch(urlsplit(self.path).path, body), loop)
                result = future.result(45)
                self.respond(200, result)
            except ValueError as error:
                self.respond(400, {"error": str(error)})
            except RuntimeError as error:
                self.respond(409, {"error": str(error)})
            except Exception as error:
                # A timed-out client request is never retried automatically.
                self.respond(503, {"error": str(error) or type(error).__name__})

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


async def run(port, heartcast_source=None, *, whoop_source, whoop_serial):
    from bleak import BleakScanner
    from heart_rate import HeartRateState, connected_heart_rate_device, receive_heart_rate
    from whoop_haptic_link import WhoopHapticLink

    async def find_whoop(address, *, timeout):
        device = await connected_heart_rate_device(address)
        if device is not None:
            return device
        return await BleakScanner.find_device_by_address(address, timeout=timeout)

    demo = Demo(WhoopHapticLink(source=whoop_source, serial=whoop_serial, finder=find_whoop),
                WatchClient(), apple_heart_rate=HeartRateState())
    token = secrets.token_urlsafe(32)
    # Acquire the local service port before touching shared state: a duplicate
    # launch must not reset the active demo or replace its authentication token.
    server = make_server(demo, asyncio.get_running_loop(), token, port)
    # A process restart creates a fresh gesture round, so a pair latched by an
    # older process cannot cause a vibration on startup.
    try:
        demo.auto_generation = request_motion_reset(demo.directory)
        RUNTIME.mkdir(exist_ok=True)
        fd = os.open(RUNTIME / "haptic_demo.token", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as output:
            output.write(token)
        (RUNTIME / "haptic_demo.token").chmod(0o600)
    except BaseException:
        server.server_close()
        raise
    threading.Thread(target=server.serve_forever, daemon=True).start()
    tasks = [
        asyncio.create_task(demo.poll_status()),
        asyncio.create_task(demo.poll_rssi()),
        asyncio.create_task(demo.keep_whoop_connected()),
    ]
    if heartcast_source:
        tasks.append(asyncio.create_task(receive_heart_rate(
            None, demo.apple_heart_rate, 6, address=heartcast_source, reuse_connected=True)))
    else:
        demo.log("HeartCast is not configured. Apple Watch heart rate is unavailable.")
    demo.log(f"Haptics dashboard: http://127.0.0.1:{port}/. Startup does not send haptics.")
    try:
        await asyncio.Event().wait()
    finally:
        demo.running = False
        for task in tasks:
            task.cancel()
        await demo.stop()
        await asyncio.gather(*tasks, return_exceptions=True)
        await demo.whoop.disconnect()
        server.shutdown()
        server.server_close()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--heartcast-source", default=os.environ.get("HEARTCAST_SOURCE_ID") or None,
                        help="Verified Apple Watch HeartCast Bluetooth identifier. Omit to skip this source.")
    parser.add_argument("--whoop-source", default=os.environ.get("WHOOP_SOURCE_ID") or None,
                        help="Your WHOOP Bluetooth identifier (WHOOP_SOURCE_ID).")
    parser.add_argument("--whoop-serial", default=os.environ.get("WHOOP_SERIAL") or None,
                        help="Expected WHOOP serial number, verified before haptics commands are allowed.")
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be 1..65535")
    if not args.whoop_source or not args.whoop_source.strip():
        parser.error("--whoop-source or WHOOP_SOURCE_ID is required")
    if not args.whoop_serial or not args.whoop_serial.strip():
        parser.error("--whoop-serial or WHOOP_SERIAL is required")
    return args


if __name__ == "__main__":
    args = parse_args()
    try:
        asyncio.run(run(args.port, args.heartcast_source,
                        whoop_source=args.whoop_source, whoop_serial=args.whoop_serial))
    except KeyboardInterrupt:
        pass
