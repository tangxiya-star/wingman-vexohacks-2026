// Bridges Will's Vexo/WHOOP dashboard (hardware/vexo, http://localhost:8765) into the Wingman server.
// It polls the dashboard's own JSON and forwards it as the console messages in docs/contract.md:
//   /api/state  -> heart_rate { band, bpm }          (about once a second, only while live)
//   /api/motion -> band_pose  { band, pose }         (only when a band's pose changes)
// Nothing changes on Will's side; run his dashboard as usual, then `npm run bridge:vexo`.
//
//   VEXO_URL=http://localhost:8765   WINGMAN_URL=ws://localhost:8787
//   VEXO_BAND_A=62  VEXO_BAND_B=77   WHOOP_BAND=A  (whose wrist the WHOOP is on)
import WebSocket from 'ws'

const VEXO = (process.env.VEXO_URL || 'http://localhost:8765').replace(/\/$/, '')
const WINGMAN = (process.env.WINGMAN_URL || 'ws://localhost:8787').replace(/\/$/, '')
const BANDS = { [Number(process.env.VEXO_BAND_A || 62)]: 'A', [Number(process.env.VEXO_BAND_B || 77)]: 'B' }
const WHOOP_BAND = process.env.WHOOP_BAND === 'B' ? 'B' : 'A'

let ws = null
let open = false
const lastPose = { A: null, B: null }
const send = (type, data) => open && ws.send(JSON.stringify({ type, ts: Date.now(), data }))

function connect() {
  ws = new WebSocket(`${WINGMAN}/ws?role=console&band=A&session=demo`)
  ws.on('open', () => {
    open = true
    lastPose.A = lastPose.B = null // re-announce poses after a reconnect
    console.log(`→ connected to Wingman ${WINGMAN}`)
  })
  ws.on('close', () => {
    if (open) console.log('× Wingman disconnected, retrying…')
    open = false
    setTimeout(connect, 1500)
  })
  ws.on('error', () => {})
}

async function getJson(path, ms) {
  const res = await fetch(VEXO + path, { cache: 'no-store', signal: AbortSignal.timeout(ms) })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

let vexoUp = null
const vexoStatus = (up) => {
  if (up !== vexoUp) console.log(up ? `← reading Vexo dashboard ${VEXO}` : `× Vexo dashboard not answering at ${VEXO}`)
  vexoUp = up
}

async function pollHeart() {
  try {
    const s = await getJson('/api/state', 2000)
    vexoStatus(true)
    if (s.status === 'live' && Number.isFinite(s.bpm)) send('heart_rate', { band: WHOOP_BAND, bpm: Math.round(s.bpm) })
  } catch {
    vexoStatus(false)
  }
  setTimeout(pollHeart, 1000)
}

// same freshness rules as Will's dashboard: only a connected, calibrated band with a recent reading counts
function poseOf(b, now) {
  if (!b || b.connected !== true || b.ready !== true) return 'unknown'
  if (!Number.isFinite(b.updated_at) || now - b.updated_at > 2 || b.updated_at > now + 1) return 'unknown'
  if (b.status === 'raised' && b.raised === true) return 'up'
  if (b.status === 'lowered' && b.raised === false) return 'down'
  return 'unknown'
}

async function pollMotion() {
  try {
    const m = await getJson('/api/motion', 1500)
    vexoStatus(true)
    if (Array.isArray(m.bands) && Number.isFinite(m.server_time)) {
      for (const b of m.bands) {
        const band = BANDS[b?.band_number]
        if (!band) continue
        const pose = poseOf(b, m.server_time)
        if (pose !== lastPose[band] && open) {
          lastPose[band] = pose
          send('band_pose', { band, pose })
          console.log(`  band ${b.band_number} (${band}): ${pose}`)
        }
      }
    }
  } catch {
    vexoStatus(false)
  }
  setTimeout(pollMotion, 300)
}

console.log(`Vexo bridge: bands ${Object.entries(BANDS).map(([n, b]) => `${n}→${b}`).join(', ')} · WHOOP on ${WHOOP_BAND}`)
connect()
pollHeart()
pollMotion()
