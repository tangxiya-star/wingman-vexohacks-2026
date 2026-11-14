# Demo runbook

**On stage:** Holly talks to Wingman (voice). Wingman asks for her accounts, she types a username when one is hard to say, and she talks about who she likes. Her Taste Core is read back, then the match runs. After that, Will's bands take over: glow → tap → same gesture → green.

The other person (band B) is onboarded **before** going on stage, so only Holly's part is live.

## Safety net (already on: `DEMO_MODE=1` in `server/.env`)

| If this happens | What the server does |
|---|---|
| Gemini is slow | Every call has a timeout: profile 40 s, match 25 s, date idea 8 s |
| The Gemini profile fails | Uses the last good profile for that first name; otherwise builds one from what they said |
| The Gemini match fails | Uses the last good match for that pair; otherwise builds one from real overlaps |
| Gemini says "not compatible" | Matches them anyway (demo only) |

Good results are saved in `server/.demo-cache.json` (not in git). The cache is only read **when Gemini fails or times out**; a healthy run always calls Gemini live. **This is why the rehearsal below matters:** it fills the cache with the exact names used on stage, so a failure still ends in their real match.

## The day before / an hour before

0. **Start clean.** `curl -X POST localhost:8787/demo/clear-cache` drops results from earlier test names.
1. **Rehearse with the real names.** Run the full flow once with the same first names you'll use on stage (cache key = first name). Afterwards, check that `server/.demo-cache.json` contains both names and the pair.
2. **Rehearse failures.** Start the server with `DEMO_FAIL=match` (or `profile` / `all`) and run the flow again. It should still end with a match.
   ```bash
   cd server && DEMO_FAIL=match npm run dev
   ```
3. **Network.** Phones must reach the laptop. Venue Wi-Fi often blocks this, so use the laptop's or a phone's hotspot. Or expose the server and open the phone with `?server=<host>`.
4. **Mic.** Open the phone page in Chrome or Safari once and allow the microphone.
5. **Health check:** `curl localhost:8787/health` should show `gemini: true`, `voice_chat: true`, `demo_mode: true`.

## Bands and heart rate (Will's hardware)

1. Start Will's dashboard as in [hardware/vexo/README.md](../hardware/vexo/README.md) (`start_whoop_dashboard.command`, port 8765). Calibrate both bands (down, then raised).
2. In another terminal: `cd server && npm run bridge:vexo`. It forwards the WHOOP heart rate (to band A's phone only) and each band's raised / down pose to Wingman.
   - Band numbers: `VEXO_BAND_A=62 VEXO_BAND_B=77` (defaults). WHOOP wearer: `WHOOP_BAND=A`.
   - Backend on another machine: `WINGMAN_URL=ws://<ip>:8787`.
3. During the match, both bands raised at the same time = it's a match.

## On stage

1. `curl -X POST localhost:8787/reset`
2. Band B: onboard just before (voice, or the console's **fill** button).
3. Holly's phone: `http://<laptop>:5173/?band=A`. Tap the mic and talk.
   - Say the name you rehearsed with.
   - If a username is hard to say: "can I type it?"
4. While the Taste Core builds (about 20 s), Wingman keeps chatting. Then it reads the core back and you confirm.
5. The match runs (about 15 s; if Gemini fails it falls back to the cache after the timeout, or immediately on an error). Then the bands.

## If something breaks live

| Problem | Do this |
|---|---|
| Voice won't start (mic, network, ElevenLabs) | On the console laptop, open `?dev=1` and press **fill** for A. It joins as Holly with real Letterboxd data and uses the cached profile. |
| Stuck waiting | The timeouts kick in after 40 s and 25 s. You can keep talking to Wingman meanwhile. |
| Bands not responding | The dev console (`?dev=1`) has, per band, **tap**, **2×tap**, **gesture** and **fill**, plus **both gesture**, **both tap**, **B stays** and **reset**. They send the same events as the bands. |
| Total mess | `POST /reset` (or **reset**), then press **fill** on both bands. The match runs again; if Gemini is down it uses the cached pair. |
