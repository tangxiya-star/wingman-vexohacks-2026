# Wingman

*Values first. Then you meet.*

Two bands glow when two people's values match. Find each other by the light, make the same gesture together, and both turn green. No swiping, no photos.

Built at **VexoHacks @ Y Combinator — November 14, 2026** by Xiya (Holly) Tang and Will Li.

**Stack:** Vexo Open band · **Gemini** (`gemini-3.8-flash`: the voice agent's brain and every Mastra agent) · ElevenLabs (voice in and out) · Mastra (agents + workflow)

## The phone app is a voice

There are no screens to fill in. You tap the mic and talk to Wingman, like a voice assistant: ElevenLabs does the listening and speaking, Gemini does the thinking. The agent runs the night through **client tools** that the phone executes:

| Tool | What happens on the phone |
|---|---|
| `set_name`, `add_account` | Saves your name / Letterboxd · Reddit · TikTok · Instagram handle (shown as small chips) |
| `ask_to_type` | Opens a small box when a username is hard to say; what you type is just sent to the agent |
| `ask_for_screenshots` | Highlights the photo button for TikTok / Instagram screenshots |
| `finish_onboarding` | Sends `join`; the Mastra workflow builds your Taste Core, which the agent then reads back to you |
| `confirm_profile` | Sends `profile_confirm` with any lines you asked to drop |
| `stay_in_touch` | After you meet, records yes/no and your contact |

Room events (band glowing, both said yes, you found each other, contacts swapped) are spoken through `POST /tts`. After changing the prompt or tools in `server/src/voice/agent.mjs`, run `npm run voice:setup` to push them to the agent. Dev: `?dev=1&text` runs the real agent in text mode (no mic); `?classic=1` shows the old screen-based UI.

## Docs

- [PRD.md](PRD.md) — full product & execution plan (v5: dating, two bands, shared gesture)
- [docs/demo.md](docs/demo.md) — demo runbook: rehearsal, safety net (timeouts, cache, fallbacks), what to do if something breaks
- [docs/contract.md](docs/contract.md) — WebSocket / state contract between frontend and backend
- [docs/prd-holly-frontend.md](docs/prd-holly-frontend.md) — Holly: mobile web experience + demo
- [docs/prd-will-backend.md](docs/prd-will-backend.md) — Will: band, backend, AI integrations
