# Live demo runbook

## Scripted stage run

Set `STAGE_DEMO=1` and `HARDWARE_MODE=accel-latch` in `server/.env`. On each wearer link below add `&stage=1`, or set `VITE_STAGE_DEMO=1` in `web/.env` to use the stage flow on the existing hardware links. Restart services after changing their environment.

1. A / 62 starts on **Looking for someone**. B / 77 is Holly's **Start conversation** screen.
2. Holly speaks with the live Wingman agent, then clicks **End conversation**. The same prepared profile appears regardless of what was said.
3. **Confirm profile** shows **We found a match for you** and **Raise your hand** on both screens. Once the bands are ready, each person quickly raises their hand once. Both fresh triggers complete the match.
4. After **It's a match**, the wearers talk to each other while their screens show their own live heart rate and a clearly labelled simulated skin temperature. **Reset session** on the room screen returns to the opening state.

## Current Mac setup

Keep the existing BLE services running. The app adapter reuses their HTTP APIs; it does not connect to either band itself.

| Service | Address | Purpose |
|---|---|---|
| Vexo motion | `http://127.0.0.1:8765` | Fresh quick-motion latch for 62 and 77 |
| Haptic coordinator / private HR | `http://127.0.0.1:8767` | Existing Watch/WHOOP connections, heart-rate source API, optional haptic rounds |
| Wingman backend | `http://127.0.0.1:8787` | Gemini / Mastra, ElevenLabs sessions, application state |
| Wingman frontend | `http://127.0.0.1:5174` | Phone companion and room screen |

1. Follow [hardware setup](../hardware/vexo/README.md) to start the two bands in `accel-latch` mode. Keep HeartCast foregrounded on the iPhone for Apple Watch heart rate.
2. Install Node dependencies with `npm ci` in `server/` and `web/`. Put provider credentials in ignored `server/.env`; use `.env.example` as the template.
3. Run `./start-wingman.command` from the repository root. It reuses healthy services on 8787/5174 and an existing bridge. It never kills or restarts BLE processes. Keep its terminal open if it started services.
4. Open the links below. These addresses are for this Mac. A phone needs a separately configured reachable HTTPS frontend/backend for microphone access; this launcher only binds localhost.

- **A / Vexo 62 / Apple Watch:** <http://127.0.0.1:5174/?band=A&hardware=1>
- **B / Vexo 77 / WHOOP:** <http://127.0.0.1:5174/?band=B&hardware=1>
- **Room display:** <http://127.0.0.1:5174/room?hardware=1>

`GET /health` should show `gemini`, `voice_chat`, `hardware_bridge` true, and `motion_mode: "accel-latch"`. The flags indicate configuration/bridge connection; they do not guarantee a live physical sensor. Inspect the motion service for device freshness.

## Rehearsal / on stage

1. Onboard B beforehand. Use Talk to Wingman; share the actual demo participant's name and interests. Having no social accounts is fine: the conversation supplies the profile source. Confirm the generated profile.
2. Onboard A the same way. The app builds and matches the profiles with Gemini.
3. When a match appears, hold both hands still briefly so the new hardware round is ready. Each person then makes **one complete, quick raise**. The accepted motion is the tested acceleration threshold; it is not a measurement of being above the head.
4. Both acceptances produce the **It's a match** scene. The action remains registered after putting the hand down. Completed states still display live freshness; stale/disconnected devices show Unavailable.
5. Tap the heart-rate badge to view the private card. A shows Apple Watch, B shows WHOOP. Neither reading is sent to the other person, the room, or the voice agent.
6. The physical RGB retains the existing HR cadence and blue→cyan→yellow→orange→red demo (three seconds per colour). Double-tap restarts that animation; it is not the app's decline gesture.
7. **Reset session** on the room screen clears the app's profiles and starts over. For a new full session, onboard again. Avoid resetting only the 8765 motion dashboard in the middle of an app round.

The screen's purple/green is an app state. This integration does not command physical Vexo purple/green acknowledgement LEDs.

## Optional haptics

`WINGMAN_HAPTICS=1` arms the existing 8767 coordinator only when Wingman reaches matched. It does not issue an immediate invitation buzz. The coordinator confirms both actions and continues its proximity phase after Spark. WHOOP must be ready; the Watch haptic app is optional and must be independently connected for Watch vibration. HeartCast heart-rate availability does not establish Watch haptic availability.

Mac–WHOOP RSSI is a demonstration proximity proxy, not a measurement of the distance between two people. An uncertain POST is reconciled using the same event ID; it is never retried with a new ID or followed by a blind reset. If no haptic round has started and the service is unavailable, the adapter can use the plain motion reset instead.

## AI safety net

`DEMO_MODE=1` is Holly's existing presentation mode: profile and match calls have timeouts, then use last-good cache or data-derived fallback. It also forces a match if the agent rejects the pair. This is presentation behaviour, not evidence of compatibility. `MOCK_AI=1` is a separate canned-output mode; leave it unset for real Gemini calls.

The cache is ignored by Git. Do not share provider credentials, sensor logs, personal profiles, or session tokens. The remote ElevenLabs agent is reused; local prompt changes are only deployed if explicitly running `npm run voice:setup`. New hardware-mode sessions include mode guidance without heart-rate data.

## If something breaks

| Symptom | Check |
|---|---|
| Frontend unavailable | Run `./start-wingman.command`; 5173 may belong to another project, so this demo uses 5174. |
| Voice cannot start | Open on this Mac's localhost, enable the microphone yourself, check `/health` and `/voice/session`. |
| No match yet | Both participants must confirm their profiles; slow AI uses the configured timeout/fallback. |
| Unavailable bands | Check `8765/api/motion`, battery, connection and freshness. Bring the band near the Mac; wake with USB if needed. |
| No heart rate | Foreground HeartCast; check `8767/api/heart-rate`. Missing data becomes `--`, never a fabricated reading. |
| New round will not arm | Finish/stop any separately owned haptic demo, then reset the Wingman session; do not repeatedly reset hardware. |

## Verification

- `cd server && node --test test/live-contract.test.mjs scripts/haptic-round.test.mjs tests/vexo-adapter.test.mjs`
- `cd web && node --test tests/hardware.test.mjs && npm run build`
- Hardware tests: see [hardware setup](../hardware/vexo/README.md).

Automated tests use isolated backends or mocked HTTP. The final on-stage check is two real quick raises after the real match appears; do not substitute synthetic hardware events into the live session.
