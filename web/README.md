# Wingman — web (Holly)

Phone companion pages + big-screen Room View. Talks to the backend over WebSocket per [docs/contract.md](../docs/contract.md).

## Run

```bash
cd web
npm install
npm run dev:mock     # mock backend on :8787 + Vite on :5173
```

Use `npm run dev` alone when Will's real backend is running.

## Pages

| URL | What |
|---|---|
| `http://localhost:5173/?band=A` | Phone page for the person wearing band A |
| `http://localhost:5173/?band=B` | Phone page for band B |
| `http://localhost:5173/room` | Big-screen Room View for judges |

Add `&dev=1` (or `?dev=1`) to any page to get the **fake band console**: tap / double tap / gesture for each band, fill a test profile, reset. It sends exactly the events Will's console will send.

## Pointing at a different backend

The page connects to `<same host>:8787` by default, so a phone opening `http://<laptop-ip>:5173` talks to that laptop.

- Will's laptop: `?server=192.168.x.x:8787`
- ngrok / cloudflared: `?server=xxx.ngrok.app` (uses `wss://` automatically on https pages)

## Mock backend

`mock/server.mjs` implements the contract's state machine with canned AI output (no API keys). `POST http://localhost:8787/reset` resets it. Will can use it as a reference for message shapes.

## Changing the match gesture

The gesture is TBD. Edit `src/config/gesture.json` (name, instruction, hint). The placeholder animation lives in `src/components/GestureDemo.tsx`.
