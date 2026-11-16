# Wingman

**We're killing the dating app. An AI that actually understands you from your social media lights up your band when someone in the room truly clicks with you. Love starts offline again.**

> **Current live demo (62 / 77):** start with [`start-wingman.command`](start-wingman.command).
> The frontend runs on **127.0.0.1:5174** and the AI backend on **127.0.0.1:8787**.
> In this hardware integration each wearer makes one quick raise after the match appears;
> the action stays latched until reset. It does not measure hand height or require a held pose.
> A is Vexo 62 / Apple Watch; B is Vexo 77 / WHOOP. The bands keep their heart-rate LED cadence
> and double-tap temperature animation; purple/green in the app are screen states, not LED acknowledgements.
> See the [live demo runbook](docs/demo.md) for the current wiring and verification.


Built at **VexoHacks @ Y Combinator, November 14, 2026** by Xiya (Holly) Tang and Will Li.

## Demo video

<!-- TODO: add the demo link (YouTube / Loom) and docs/media/demo-thumbnail.jpg -->
> 🎬 **[Watch the demo (TODO: add link)](#)**

---

## Problem

Modern dating happens almost entirely online, and very little of it turns into real dates. Most matches never leave the chat. When people do meet, it's often awkward, because the person across the table isn't someone they actually click with. Apps match on surface things like photos, height and job, not on what's underneath: values, humor, and how you see the world.

## What Wingman does

1. **Talk to it.** A voice agent on your phone gets to know you and reads your social media (Letterboxd, Reddit, TikTok / Instagram saves). Say **"find my person"** when you're ready.
2. **It matches on what lasts.** Taste, values, what you want, and humor. No photos, no swiping, no scores, just specific reasons you share.
3. **Your band glows.** Both people tap once to say yes. Only if both do, you get a meeting spot and what they're wearing.
4. **Raise your bands together.** It's a match: both bands turn green, and Wingman gives you a first line built from what you have in common.

Double-tap to leave quietly; the other person never knows why. Looks preferences never reach the matching agent, and your heart rate only shows on your own phone.

### The flow, on real hardware

<!-- TODO: put the photos in docs/media/ with these names, then delete the placeholder text. -->

| 1. Talk to Wingman | 2. Your match, with reasons | 3. Both bands glow |
|---|---|---|
| ![Voice onboarding](docs/media/01-talk.jpg)<br>_TODO_ | ![Match reasons](docs/media/02-reasons.jpg)<br>_TODO_ | ![Bands glowing](docs/media/03-glow.jpg)<br>_TODO_ |
| **4. Raise together** | **5. It's a match** | **6. Go say hi** |
| ![Raising bands](docs/media/04-raise.jpg)<br>_TODO_ | ![Bands green](docs/media/05-match.jpg)<br>_TODO_ | ![Talking](docs/media/06-meet.jpg)<br>_TODO_ |

---

## Sponsor tracks

| Sponsor | How we use it |
|---|---|
| **Vexo** | The bands are the interface in the room: glow on a match, tap to say yes, double-tap to leave, and both raised at once confirms the match. |
| **Google Gemini** | `gemini-3.8-flash` builds each person's Taste Core, judges the match across four dimensions, writes the opener, and powers the voice agent. |
| **ElevenLabs** | The phone app is a voice agent that drives the screen through client tools, plus TTS for room events. |
| **Mastra** | The matching pipeline: source tools, a taste-profile agent, and a match agent with zod-validated output. |
| **WHOOP** | Live heart rate, shown privately to the wearer only. |

## How it's built

```
Vexo bands + WHOOP ──BLE──▶ hardware/vexo (Mac bridge) ──▶ server/scripts/vexo-bridge.mjs
                                                                   │
Phones (web) ◀──── WebSocket ────▶ server (Node) ──▶ Gemini via Mastra
Big screen  ◀──────────────────────┘          └──▶ ElevenLabs
```

- **`server/`**: Node WebSocket server and the night's state machine; Mastra agents in `src/mastra/`; the voice agent's prompt and tools in `src/voice/agent.mjs`.
- **`web/`**: React + Vite. The phone app is `src/voice/VoiceApp.tsx`; the big screen is `/room`.
- **`hardware/vexo/`**: Python BLE control, raise-hand detection, MATCH dashboard. See its [README](hardware/vexo/README.md).

## Run it

```bash
cd server && cp .env.example .env   # add GEMINI_API_KEY, ELEVENLABS_API_KEY
npm install && npm run voice:setup && npm run dev   # :8787
```

```bash
cd web && npm install && npm run dev   # :5173 → ?band=A / ?band=B, big screen at /room
```

No keys: `MOCK_AI=1`. No bands: add `?dev=1`. With bands: start Will's dashboard, then `npm run bridge:vexo`. More in [docs/demo.md](docs/demo.md) and [docs/contract.md](docs/contract.md).
