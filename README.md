# Wingman

**Your band lights up when someone in the room actually shares your values. Find each other by the light, raise your hands together, and go say hi.**

*Values first. Then you meet.*

Built at **VexoHacks @ Y Combinator, November 14, 2026** by Xiya (Holly) Tang and Will Li.

---

## Problem

Dating apps are online-first, and almost nothing makes it offline. People swipe, match, chat for a few days, and never meet.

- **Matches are decided by a photo in half a second.** Nobody can tell whether two people share values or want the same things, and those are what decide whether a relationship works.
- **Profiles are generic, so matches are generic.** Everyone writes "I love travel, food and Netflix." Questionnaires get polite answers that all sound the same. What actually describes you lives in the films you rate, the communities you post in, and what you'd say to a friend.
- **In a real room, the best person for you might be ten feet away.** What's missing is a reason to walk over, a sign they're open to it too, and a first sentence.

## What Wingman does

1. **Talk, don't fill in forms.** You talk to Wingman on your phone, a voice agent. It asks a few values questions and reads your public taste (for example Letterboxd and Reddit).
2. **It matches on four dimensions, not one.** Taste, values, what you want, and how you are with people. A match on films alone doesn't count. There is no score and no photos. You get specific reasons, each labelled with where we saw it.
3. **Your band glows.** When there's a real fit, both bands light up. Each of you taps once to say yes, and nothing happens unless both do.
4. **Find each other and raise your hands together.** Both people raise their bands at the same moment, and it's a match: the bands turn green, gold flakes burst on the phone, and Wingman whispers a personal opener.
5. **Leave quietly if it isn't there.** Double-tap your band and you're out. The other person never learns why.

Privacy by design: looks preferences never reach the matching agent and are never shown to the other person. Your heart rate is shown only on your own phone.

---

## Sponsor tracks

| Sponsor | How Wingman uses it |
|---|---|
| **Vexo** | Vexo Open bands are the whole interface in the room. They glow when there's a match, take a tap for "yes" and a double-tap to leave quietly, and detect the shared gesture: both bands raised at the same time confirm the match. Will's Mac BLE bridge (`hardware/vexo`) drives the LEDs and reads motion, and `npm run bridge:vexo` forwards each band's raised or down pose to the Wingman server. |
| **Google Gemini** | `gemini-3.8-flash` is the brain of everything. It builds each person's Taste Core, judges compatibility across the four dimensions with structured output (overlaps, reasons for each person, uncertainty), writes the second-date idea and opener, and also powers the ElevenLabs voice agent's reasoning. |
| **ElevenLabs** | The phone app is a voice. An ElevenLabs Agent (voice "Jessica", `eleven_v4_turbo`) handles onboarding by conversation and drives the phone through **client tools**: saving accounts, confirming the profile, choosing which live card to show (generative UI), recording stay-in-touch. Room events are spoken through ElevenLabs TTS. |
| **Mastra** | The matching pipeline is a Mastra workflow: source tools fetch Letterboxd and Reddit, the taste-profile agent builds the Taste Core, and the match agent returns a zod-validated `matchSchema`. A demo safety net adds timeouts, a cache of the last good results, and fallbacks. |
| **WHOOP** | Live heart rate over Bluetooth broadcast, forwarded by the bridge. It appears only on the wearer's own phone as a private card, never on the big screen or to the match. |

---

## Architecture

```
 Vexo bands ──BLE──▶ hardware/vexo (Will's Mac: LEDs, motion, MATCH dashboard :8765)
 WHOOP ─────BLE──▶        │
                          │  server/scripts/vexo-bridge.mjs  (poses + heart rate)
                          ▼
 Phones (web, ?band=A / ?band=B) ◀──WebSocket /ws──▶ server (Node, :8787) ──▶ Gemini via Mastra
 Room View (big screen)          ◀──────────────────┘        │
        ▲                                                     └──▶ ElevenLabs (agent session, TTS)
        └── ElevenLabs Agent runs in the phone's browser, calling client tools
```

The server owns the night's state machine and pushes every change to every client over one WebSocket:

`idle → profiling → matched → mutual → meeting_confirmed → whisper → stay_in_touch` (plus `hidden` and `expired`)

Message formats are defined in [docs/contract.md](docs/contract.md).

### Backend: `server/`

| Path | What it does |
|---|---|
| `src/index.mjs` | HTTP + WebSocket server and the state machine: joins, taps, poses, heart rate, spark, whisper, stay in touch. HTTP: `/voice/session`, `/tts`, `/demo/clear-cache`, `/health` |
| `src/mastra/` | Mastra setup: `agents/` (taste profile, match), `workflows/taste-profile.js`, `tools/sources.js`, `schemas.js` (zod `matchSchema` with `overlaps`), `run.js` (calls the agents) |
| `src/ai/prompts.mjs` | System prompts, including the four-dimension matching rules |
| `src/ai/elevenlabs.mjs` | TTS (Jessica, `eleven_v4_turbo`) |
| `src/ai/canned.mjs` | Canned results for `MOCK_AI=1` |
| `src/voice/agent.mjs` | The ElevenLabs agent's prompt and client tools; `setup.mjs` pushes them (`npm run voice:setup`) |
| `src/sources/` | Letterboxd (RSS) and Reddit fetchers |
| `src/demo/safety.mjs` | Timeouts, last-good cache, multi-dimension fallback match |
| `scripts/vexo-bridge.mjs` | Polls Will's dashboard and forwards `band_pose` and `heart_rate` as the console |

### Frontend: `web/` (React + Vite + TypeScript)

| Path | What it does |
|---|---|
| `src/voice/VoiceApp.tsx` | The phone app: the voice agent, its client tools, the match moment, the "It's a match" scene, live cards |
| `src/voice/LiveCards.tsx` | Generative UI cards the agent can show: `HeartCard` (private heart rate), `BandsCard` (raise together) |
| `src/voice/speech.ts` | Plays room events through `/tts` |
| `src/components/FluidBlob.tsx` | The WebGL shape that is the agent's face; its colours glide with the state |
| `src/components/SparkBurst.tsx` | Gold-flake burst on the match |
| `src/RoomView.tsx` | Big-screen view of the room: both bands, overlaps, raised or waiting |
| `src/overlaps.ts` | Turns match overlaps into rows by dimension (Taste, Values, Wants, Style) |
| `src/ws.ts` | WebSocket client with auto-reconnect; `?server=` picks the backend |
| `src/types.ts` | Message types shared with the contract |
| `src/dev/DevPanel.tsx` | `?dev=1`: simulate taps, raises and heart rate without hardware |
| `src/PhoneApp.tsx`, `src/screens/` | The older screen-based UI (`?classic`) |

### Hardware: `hardware/vexo/`

Python BLE control for bands 62 and 77, raise-hand detection, the two-band MATCH dashboard, WHOOP heart rate, and Watch / WHOOP haptics. It has its own setup guide: [hardware/vexo/README.md](hardware/vexo/README.md).

---

## Run it

Requirements: Node 20+, and keys for Gemini and ElevenLabs.

```bash
cd server && cp .env.example .env    # fill in GEMINI_API_KEY, ELEVENLABS_API_KEY
npm install && npm run voice:setup   # creates or updates the ElevenLabs agent and saves its ID to .env
npm run dev                          # :8787
```

```bash
cd web && npm install && npm run dev # :5173
```

- Phones: open `http://<laptop-ip>:5173/?band=A` and `?band=B`. Phone microphones need HTTPS, so for real phones use a tunnel and add `?server=<backend-host>`.
- Big screen: open `http://<laptop-ip>:5173/room`.
- No keys: start the server with `MOCK_AI=1`. No bands: add `?dev=1` for the dev panel.
- With the bands: start Will's dashboard (`hardware/vexo/start_whoop_dashboard.command`, port 8765), then `cd server && npm run bridge:vexo`.
- Before a demo: `curl -X POST localhost:8787/demo/clear-cache`.

The full rehearsal checklist and what to do when something breaks are in [docs/demo.md](docs/demo.md).

## Docs

- [PRD.md](PRD.md): product and execution plan
- [docs/contract.md](docs/contract.md): WebSocket and state contract
- [docs/demo.md](docs/demo.md): demo runbook
- [hardware/vexo/README.md](hardware/vexo/README.md): hardware setup
