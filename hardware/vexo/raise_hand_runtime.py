"""Receive the band's IMU stream and report derived gestures on this Mac."""

import asyncio
import json
import math
import os
import sys
from datetime import datetime, timezone

from band_config import BAND_NUMBER
from mac_events import MacEventReporter
from motion_state import (INVALID_RESET_GENERATION, MotionStatePublisher,
                          read_reset_generation, request_motion_reset)
from quick_motion import QuickMotionDetector
from trained_raise import TrainedRaiseDetector
from sustained_pose import SustainedPoseEstimator


class RaiseHandMonitor:
    def __init__(self, band, path, log, simulated=False, *, band_number=BAND_NUMBER, state_path=None,
                 motion_mode="pose"):
        if motion_mode not in ("pose", "accel-latch"):
            raise ValueError("motion_mode 必须是 pose 或 accel-latch")
        self.motion_mode = motion_mode
        if isinstance(band_number, bool) or not isinstance(band_number, int) or not 1 <= band_number <= 65535:
            raise ValueError("band_number 必须是 1 到 65535 的整数")
        if getattr(band, "number", None) not in (None, band_number):
            raise ValueError("已连接手环编号与 monitor 的 band_number 不一致")
        self.band = band
        self.band_number = band_number
        self.log = lambda message: log(f"[手环 {self.band_number}] {message}")
        self.simulated = simulated
        self.detector = TrainedRaiseDetector()
        self.pose = SustainedPoseEstimator()
        self.reporter = MacEventReporter(path, self.band_number)
        if state_path is None and path is not None:
            state_path = path.parent / f"{'sim_' if simulated else ''}motion_state_{self.band_number}.json"
        self.state_publisher = MotionStatePublisher(state_path, self.band_number)
        self.quick_motion = QuickMotionDetector()
        self._reset_dir = (self.state_publisher.path.parent if self.state_publisher.path is not None
                           else None)
        if simulated and self._reset_dir is not None:
            self._reset_dir = self._reset_dir / "sim_motion"
        self._reset_generation = read_reset_generation(self._reset_dir)
        self._reset_available = self._reset_generation != INVALID_RESET_GENERATION
        if motion_mode == "accel-latch" and self.state_publisher.path is not None:
            try:
                previous = json.loads(self.state_publisher.path.read_text(encoding="utf-8"))
                previous_generation = previous.get("reset_generation")
                if (not self._reset_available and isinstance(previous_generation, str)
                        and previous_generation and previous_generation != INVALID_RESET_GENERATION):
                    self._reset_generation = previous_generation
                if (previous.get("version") == 1 and previous.get("band_number") == band_number
                        and previous.get("mode") == motion_mode
                        and previous.get("reset_generation") == self._reset_generation
                        and previous.get("triggered") is True):
                    self.quick_motion.restore_latch()
            except (OSError, ValueError, TypeError, AttributeError):
                pass
        self.loop = asyncio.get_running_loop()
        self.failure = self.loop.create_future()
        self._input_fd = None
        self._input_buffer = ""
        self._closed = False
        self._last_phase = None
        self._samples = 0
        self._latest_angle = None
        self._peak_angle = 0.0
        self._peak_gyro = 0.0
        self._latest_gyro = None
        self._latest_magnitude = None
        self._enabled = False
        self._profile_saved = False
        profile_name = f"{'sim_' if simulated else ''}raise_calibration_{self.band_number}.json"
        self._profile_path = path.parent / profile_name if path else None
        pose_name = f"{'sim_' if simulated else ''}pose_calibration_{self.band_number}.json"
        self._pose_path = path.parent / pose_name if path else None
        self._diagnostic_dir = path.parent / "debug" if path else None
        self._trace = None
        self._trace_count = 0
        self._trace_path = None
        if self._profile_path is not None and self._profile_path.exists():
            try:
                saved = json.loads(self._profile_path.read_text(encoding="utf-8"))
                if not isinstance(saved, dict):
                    raise ValueError("校准文件不是 JSON 对象")
                if saved.get("band_number") != self.band_number or saved.get("simulated") is not simulated:
                    raise ValueError("校准文件的手环编号不一致")
                self.detector.restore_calibration(saved["profile"])
                self._enabled = self._profile_saved = True
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.log(f"未采用校准文件，需按 c 重新校准：{error}")
        self._model_revision = self.detector.model_revision
        if self._pose_path is not None and self._pose_path.exists():
            try:
                saved = json.loads(self._pose_path.read_text(encoding="utf-8"))
                if (not isinstance(saved, dict) or saved.get("band_number") != self.band_number
                        or saved.get("simulated") is not simulated):
                    raise ValueError("姿态文件的手环编号或模式不一致")
                self.pose.restore_calibration(saved["profile"])
            except (OSError, ValueError, KeyError, TypeError) as error:
                self.log(f"未采用姿态文件，需用 d/u 保存下垂和头顶姿态：{error}")
        self._pose_revision = self.pose.model_revision

    async def start(self, interactive=True):
        self.band.on("motion", self._receive)
        await self.band.set_motion(accel_range=8)
        await self.band.configure(motion=50, sensors="both")
        settings = await self.band.get_motion()
        if settings.rate != 50 or settings.sensors != "both":
            raise RuntimeError("未能启用 50 Hz 加速度和陀螺仪，抬手识别未启动。")
        self._publish_state(force=True)
        if self.motion_mode == "accel-latch":
            self.log("快速动作演示：静止准备后，用持续明显的加速度变化触发一次；不判断高度或举手姿态。")
            self.log(f"当前动作门槛：偏离 1 g 至少 {self.quick_motion.threshold_g:g} g，"
                     f"持续至少 {self.quick_motion.sustain_ms:g} ms。")
            self.log("触发后保持到面板点击「重置本轮」；reset 回车也会重置两只手环。r/x 记录诊断，s 查看状态。")
        elif self._enabled:
            self.log("已恢复此前明确校准的下垂姿势。先放下手，稳定后开始识别；重新佩戴后需按 c 校准。")
        else:
            self.log("运动接收已开启，等待明确校准：手自然下垂后输入 c 回车，保持不动约 1 秒。")
        if self.motion_mode == "pose":
            self.log("官方模板识别：c 校准，t 学习 3 次举起和放下，s 状态；r/x 开始/结束短时诊断记录。")
            if self.detector.ready:
                self.log("已恢复举手动作模板，正在识别。")
            else:
                self.log("尚未完成动作训练，暂不上报 hand_raise。")
            self.log("面板姿态独立校准：d 保存下垂、u 保存头顶，各保持不动约 1 秒；不改动已有动作模板。")
            if self.pose.ready:
                self.log("已恢复本手环的两个姿态，面板持续检测当前举手状态。")
        if interactive:
            try:
                fd = sys.stdin.fileno()
                self.loop.add_reader(fd, self._read_commands)
                self._input_fd = fd
            except (AttributeError, OSError, ValueError, NotImplementedError):
                self.log("当前终端不支持输入校准命令；重新运行可重新校准。")

    def _receive(self, sample):
        if self._closed or self.failure.done():
            return
        try:
            self._samples += 1
            if self._trace is not None:
                self._trace.write(json.dumps({key: sample.get(key) for key in
                                             ("t", "ax", "ay", "az", "gx", "gy", "gz", "n")},
                                            allow_nan=False) + "\n")
                self._trace_count += 1
                if self._trace_count % 50 == 0:
                    self._trace.flush()
                if self._trace_count >= 6000:
                    self.stop_recording()
            if self.motion_mode == "accel-latch":
                self._receive_quick_motion(sample)
                return
            event = self.detector.feed(sample) if self._enabled else None
            was_calibrating = self.pose.calibrating
            self.pose.feed(sample)
            if self.pose.model_revision != self._pose_revision:
                self._pose_revision = self.pose.model_revision
                self._save_pose_profile()
                self.log(f"姿态已保存：{self.pose.last_observation}；两个姿态就绪={self.pose.ready}。")
            elif was_calibrating and not self.pose.calibrating:
                self.log(f"姿态未保存：{self.pose.last_observation}。")
            self._publish_state()
            baseline = self.detector.baseline
            if baseline is not None and not self._profile_saved:
                self._save_profile()
            if self.detector.model_revision != self._model_revision:
                self._model_revision = self.detector.model_revision
                counts = self.detector.training_counts
                self.log(f"动作示范已记录：举起 {counts['raise']}/3，放下 {counts['lower']}/3。")
                if baseline is not None:
                    self._save_profile()
                if self.detector.ready and not self.detector.training:
                    self.log("动作模板已学会并保存；接下来用新动作检验，不再使用固定 130° 触发规则。")
            values = [sample.get(key) for key in ("ax", "ay", "az", "gx", "gy", "gz")]
            if all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
                magnitude = math.hypot(*values[:3])
                self._latest_magnitude = magnitude
                self._latest_gyro = math.hypot(*values[3:])
                if baseline is not None and magnitude > 0:
                    cosine = sum(a * b for a, b in zip(values[:3], baseline)) / magnitude
                    self._latest_angle = math.degrees(math.acos(max(-1, min(1, cosine))))
                    self._peak_angle = max(self._peak_angle, self._latest_angle)
                self._peak_gyro = max(self._peak_gyro, self._latest_gyro)
            phase = self.detector.phase
            if phase != self._last_phase:
                if phase == "armed":
                    self.log("抬手识别已准备：现在可从自然下垂快速举过头顶。")
                elif phase == "calibrating" and self._enabled:
                    self.log("正在校准下垂姿势，保持手臂不动约 1 秒。")
                self._last_phase = phase
            if event is not None:
                record = self.reporter.emit({**event, "simulated": self.simulated,
                                             "detected_by": "mac_imu_detector"})
                self.log(f"Mac 收到抬手事件 #{record['sequence']}："
                         f"{record['duration_ms']:.0f} ms，姿态变化 {record['angle_deg']:.0f}°。")
        except Exception as error:
            # The SDK isolates callback errors; propagate ours to the main task.
            self.failure.set_exception(error)

    def _publish_state(self, *, force=False, connected=None):
        connected = bool(self.band.connected) if connected is None else connected
        if self.motion_mode == "accel-latch":
            self.state_publisher.publish(
                connected=connected, ready=bool(connected and self._reset_available and self.quick_motion.ready),
                raised=False, phase=self.quick_motion.phase if connected else "disconnected",
                mode=self.motion_mode, triggered=self.quick_motion.latched,
                reset_generation=self._reset_generation, force=force)
            return
        ready = bool(connected and self.pose.ready and not self.pose.calibrating)
        self.state_publisher.publish(connected=connected, ready=ready,
                                     raised=bool(ready and self.pose.raised),
                                     phase=(f"calibrating_{self.pose.calibrating}" if self.pose.calibrating
                                            else f"pose_{self.pose.state}") if connected else "disconnected",
                                     force=force)

    def _receive_quick_motion(self, sample):
        generation = read_reset_generation(self._reset_dir)
        self._reset_available = generation != INVALID_RESET_GENERATION
        if not self._reset_available:
            # A read error is not a user reset. Keep the latch, but stop live
            # status and detection until the round file is readable again.
            self._publish_state()
            return
        if generation != self._reset_generation:
            self._reset_generation = generation
            self.quick_motion.reset()
            if self._trace is not None:
                self._trace.write(json.dumps({"kind": "motion_reset", "generation": generation}) + "\n")
                self._trace.flush()
            self.log("本轮已重置；请先静止片刻，再做快速动作。")
        event = self.quick_motion.feed(sample)
        self._publish_state()
        if self.quick_motion.phase != self._last_phase:
            previous_phase = self._last_phase
            self._last_phase = self.quick_motion.phase
            if (self._last_phase in ("settling", "cooldown", "latched")
                    or self._last_phase == "armed" and previous_phase not in ("candidate", "armed")):
                self.log(f"快速动作状态：{self.quick_motion.phase}。")
        if event is not None:
            record = self.reporter.emit({**event, "simulated": self.simulated,
                                         "motion_threshold_g": self.quick_motion.threshold_g,
                                         "motion_sustain_ms": self.quick_motion.sustain_ms,
                                         "detected_by": "mac_acceleration_detector"})
            self.log(f"Mac 收到快速动作事件 #{record['sequence']}；本轮保持已触发，等待手动重置。")

    def calibrate_pose(self, label):
        self.pose.begin_calibration(label)
        self._publish_state(force=True)
        self.log(f"正在保存{'自然下垂' if label == 'down' else '头顶'}姿态，请保持约 1 秒；原动作模板保留。")

    def _save_pose_profile(self):
        if self._pose_path is None:
            return
        self._pose_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._pose_path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"band_number": self.band_number,
                                        "simulated": self.simulated,
                                        "profile": self.pose.calibration_profile()},
                                       allow_nan=False), encoding="utf-8")
        temporary.replace(self._pose_path)

    def recalibrate(self):
        self.detector.calibrate()
        self._enabled = True
        self._profile_saved = False
        if self._profile_path is not None:
            self._profile_path.unlink(missing_ok=True)
        if self._trace is not None:
            self._trace.write('{"kind":"calibrate"}\n')
            self._trace.flush()
        self._last_phase = None
        self._latest_angle = None
        self._peak_angle = self._peak_gyro = 0.0
        self._publish_state(force=True)
        self.log("重新校准：请将手自然下垂并静止约 1 秒；原动作模板已清空，校准后用 t 重新学习。")

    def _save_profile(self):
        if self._profile_path is not None:
            self._profile_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._profile_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({"band_number": self.band_number, "simulated": self.simulated,
                                            "profile": self.detector.calibration_profile()},
                                           allow_nan=False), encoding="utf-8")
            temporary.replace(self._profile_path)
        self._profile_saved = True

    def begin_training(self):
        if not self._enabled or self.detector.baseline is None:
            self.log("先将手自然下垂，输入 c 校准完成后再输入 t。")
            return
        self.detector.begin_training()
        self._model_revision = self.detector.model_revision
        self._save_profile()
        self._publish_state(force=True)
        if self._trace is not None:
            self._trace.write('{"kind":"begin_training"}\n')
            self._trace.flush()
        self.log("开始学习你的动作：做 3 次快速举过头顶—放下，每个端点稍停约 1 秒；学习期间不输出举手事件。")

    def start_recording(self):
        self.stop_recording()
        if self._diagnostic_dir is None:
            raise ValueError("诊断记录需要本地事件目录")
        self._diagnostic_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
        self._trace_path = self._diagnostic_dir / f"{'sim_' if self.simulated else ''}motion_{self.band_number}_{stamp}.jsonl"
        self._trace = self._trace_path.open("x", encoding="utf-8")
        self._trace_count = 0
        profile = self.detector.calibration_profile()
        header = ({"kind": "restore_calibration", "profile": profile} if profile else
                  {"kind": "calibrate" if self._enabled else "disabled"})
        header["simulated"] = self.simulated
        header["band_number"] = self.band_number
        header["motion_mode"] = self.motion_mode
        if self.motion_mode == "accel-latch":
            header["reset_generation"] = self._reset_generation
            header["triggered"] = self.quick_motion.latched
        self._trace.write(json.dumps(header, allow_nan=False) + "\n")
        self._trace.flush()
        self.log(f"本地运动诊断记录已开始（最多 120 秒，不含心率）：{self._trace_path}")

    def stop_recording(self):
        if self._trace is not None:
            self._trace.close()
            self._trace = None
            self.log(f"运动诊断记录结束：{self._trace_count} 个样本，{self._trace_path}")

    def status(self):
        if self._trace is not None:
            self._trace.flush()
        if self.motion_mode == "accel-latch":
            self.log(f"快速动作状态={self.quick_motion.phase}；已触发={self.quick_motion.latched}；"
                     f"已收到 {self._samples} 个运动样本；本轮={self._reset_generation}。")
            return
        angle = "无" if self._latest_angle is None else f"{self._latest_angle:.0f}°"
        self.log(f"抬手状态 {self.detector.phase}；已收到 {self._samples} 个运动样本；"
                 f"当前相对角度 {angle}，最大角度 {self._peak_angle:.0f}°，"
                 f"最大角速度 {self._peak_gyro:.0f}°/s；"
                 f"当前 |a|={self._latest_magnitude} g、|gyro|={self._latest_gyro}°/s，"
                 f"基线={self.detector.baseline}，已启用={self._enabled}，"
                 f"模板就绪={self.detector.ready}，示范数={self.detector.training_counts}，"
                 f"最近动作={self.detector.last_observation}。")
        self.log(f"面板姿态={self.pose.state}；两个姿态就绪={self.pose.ready}；"
                 f"正在校准={self.pose.calibrating}；详情={self.pose.last_observation}。")

    def _read_commands(self):
        try:
            data = os.read(self._input_fd, 4096)
            if not data:
                self.loop.remove_reader(self._input_fd)
                self._input_fd = None
                return
            self._input_buffer += data.decode("utf-8", errors="replace")
            while "\n" in self._input_buffer:
                command, self._input_buffer = self._input_buffer.split("\n", 1)
                command = command.strip().lower()
                if self.motion_mode == "accel-latch" and command == "reset":
                    request_motion_reset(self._reset_dir)
                elif self.motion_mode == "accel-latch" and command in ("c", "calibrate", "t", "train", "d", "u", "cancel"):
                    self.log("快速动作模式不需要姿态校准或训练；使用面板重置或 reset 开启下一轮。")
                elif command in ("c", "calibrate"):
                    self.recalibrate()
                elif command in ("s", "status"):
                    self.status()
                elif command in ("t", "train"):
                    self.begin_training()
                elif command == "r":
                    self.start_recording()
                elif command == "x":
                    self.stop_recording()
                elif command == "d":
                    self.calibrate_pose("down")
                elif command == "u":
                    self.calibrate_pose("up")
                elif command == "cancel":
                    self.pose.cancel_calibration()
                    self._publish_state(force=True)
            self._input_buffer = self._input_buffer[-4096:]
        except (OSError, ValueError) as error:
            if not self.failure.done():
                self.failure.set_exception(error)

    async def run(self):
        await self.failure

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.band.off("motion", self._receive)
        if self._input_fd is not None:
            self.loop.remove_reader(self._input_fd)
            self._input_fd = None
        if not self.failure.done():
            self.failure.cancel()
        elif not self.failure.cancelled():
            self.failure.exception()
        try:
            self.reporter.close()
        finally:
            try:
                self.stop_recording()
            finally:
                self._publish_state(connected=False, force=True)
