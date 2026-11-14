# Wingman server

Real backend: WebSocket state machine (`docs/contract.md`) + real source fetchers + Gemini Profile/Match agents + optional ElevenLabs voice.

```bash
cd server
npm install
cp .env.example .env      # add GEMINI_API_KEY at minimum
npm run dev               # ws://<host>:8787/ws
```

Then in another terminal: `cd web && npm run dev`, and open `http://<laptop-ip>:5173/?band=A` / `?band=B` / `/room`. Add `&dev=1` to get the fake band console.

## Keys

| Key | Needed? | What happens without it |
|---|---|---|
| `GEMINI_API_KEY` | **yes** | Phone gets an error; profile falls back to raw Letterboxd/Reddit highlights with no Taste Core; match fails → no_match |
| `REDDIT_CLIENT_ID` / `SECRET` | recommended | Reddit returns 403 for anonymous requests → listed in `failed_sources` (create a "script" app at reddit.com/prefs/apps) |
| `ELEVENLABS_API_KEY` | optional | `audio_url: null` → phone uses browser speech |
| `MOCK_AI=1` | dev only | Real fetchers, canned Gemini output — for testing flow without spending tokens |

`GET /health` shows which of these are active.

## Try pieces alone

```bash
npm run try:letterboxd -- davidehrlich
npm run try:reddit -- <username>
npm run try:profile -- davidehrlich [reddit_user]   # real Profile Agent output
```

## Sources

- **Letterboxd** — public RSS (`letterboxd.com/<user>/rss/`), last ~50 diary entries with ratings, likes, review text.
- **Reddit** — public profile via app-only OAuth: top subreddits, recent posts/comments (NSFW dropped).
- **TikTok / Instagram** — no API exposes likes/saves, so users upload screenshots of their Favorites/Saved tabs; Gemini Vision reads them (faces ignored).
- **Spotify** — P1, not implemented (reported in `failed_sources`).

## Layout

```
src/index.mjs            HTTP + WS server, state machine, reconnect replay, /audio/:id.mp3, /reset, /health
src/sources/*.mjs        fetchers + *ToText() for the prompt
src/ai/gemini.mjs        Profile Agent, Match Agent, second-date idea (prompts mirror docs/prompts/)
src/ai/elevenlabs.mjs    TTS
src/ai/canned.mjs        MOCK_AI output + raw-data fallback highlights
```
