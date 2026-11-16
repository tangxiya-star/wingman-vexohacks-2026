"""Drive one explicitly selected Vexo from the dashboard's existing WHOOP state."""

import asyncio
from pathlib import Path

from heart_rate import Band, PulseDisplay, boost_band_radio, enable_temperature_animation, log
from raise_hand_runtime import RaiseHandMonitor
from temperature_animation import TemperatureAnimation


async def prepare_display(band, state):
    # Clear the prior session first. Optional gesture detection starts its motion
    # stream afterwards, on this same connection, alongside the LED animation.
    await band.configure(motion=False, audio=False, mic_level=False,
                         activity=False, battery=False, temperature=False,
                         link=False, events=True)
    await band.led_off()
    animation = TemperatureAnimation()
    await enable_temperature_animation(band, animation)
    return PulseDisplay(band, state, stale_after=state.stale_after,
                        brightness=1.0, animation=animation)


async def close_band(band, number, off_timeout=3, disconnect_timeout=5):
    try:
        if band.connected:
            await asyncio.wait_for(band.led_off(), timeout=off_timeout)
    except Exception as error:
        log(f"Vexo {number} 关灯未确认：{error}")
    finally:
        try:
            await asyncio.wait_for(band.disconnect(), timeout=disconnect_timeout)
        except Exception as error:
            log(f"Vexo {number} 断开未确认：{error}")


async def _drive_display(band, display):
    while band.connected:
        updated = await display.update_with_retry()
        await asyncio.sleep(0.2 if updated else 0.5)


async def band_worker(state, number, scan_seconds=10, retry_seconds=3, *,
                      raise_hand=False, events_path=None, interactive=True, state_path=None,
                      motion_mode="pose"):
    """Retry only this number; a missing band never interrupts the WHOOP feed."""
    if raise_hand:
        events_path = (Path(events_path) if events_path is not None else
                       Path(__file__).resolve().parent / "runtime" / f"hand_events_{number}.jsonl")
    while True:
        band = None
        monitor = None
        display_task = None
        try:
            log(f"正在连接 Vexo-HACK-{number:02d}，与页面共用同一份 WHOOP 心率。")
            band = await asyncio.wait_for(
                Band.connect(number, set_clock=False, scan_seconds=scan_seconds),
                timeout=scan_seconds + 25,
            )
            await boost_band_radio(band, number)
            display = await prepare_display(band, state)
            if raise_hand:
                monitor = RaiseHandMonitor(band, events_path, log, band_number=number,
                                           state_path=state_path, motion_mode=motion_mode)
                await monitor.start(interactive=interactive)
                log(f"Vexo {number} 动作识别与灯光共用当前蓝牙连接；事件文件：{events_path}")
            log(f"Vexo {number} 已连接：最大亮度，双敲重播蓝→青→黄→橙→红，每色 3 秒。")
            # PulseDisplay.run() belongs to the original band configuration;
            # use its update/retry behavior without that fixed device label.
            display_task = asyncio.create_task(_drive_display(band, display))
            watched = [display_task]
            if monitor is not None:
                # The SDK isolates callback exceptions. Observe the monitor's
                # failure even while an LED command is waiting for its reply.
                watched.append(monitor.failure)
            done, _ = await asyncio.wait(watched, return_when=asyncio.FIRST_COMPLETED)
            for completed in done:
                completed.result()
            log(f"Vexo {number} 蓝牙已断开，正在重连同一只手环。")
        except Exception as error:
            log(f"Vexo {number} 暂不可用：{error}；WHOOP 页面继续运行。")
        finally:
            try:
                if display_task is not None:
                    display_task.cancel()
                    await asyncio.gather(display_task, return_exceptions=True)
            finally:
                try:
                    if monitor is not None:
                        monitor.close()
                except Exception as error:
                    log(f"Vexo {number} 动作记录关闭未确认：{error}")
                finally:
                    if band is not None:
                        await close_band(band, number)
        await asyncio.sleep(retry_seconds)
