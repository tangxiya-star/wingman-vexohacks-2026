// Wingman mock backend — stands in for Will's /server until it's ready.
// Implements the state machine + events in docs/contract.md with canned AI output.
//   npm run mock            (port 8787)
//   POST http://localhost:8787/reset
import http from 'node:http'
import { readFileSync } from 'node:fs'
import { WebSocketServer } from 'ws'

const PORT = Number(process.env.PORT || 8787)
const GESTURE = JSON.parse(readFileSync(new URL('../src/config/gesture.json', import.meta.url))).id
const SYNC_MS = 1000
const DECISION_TIMEOUT_MS = 120_000
const AFTER_SPARK = ['meeting_confirmed', 'whisper', 'stay_in_touch']

const clients = new Set() // { ws, role, band }
const other = (b) => (b === 'A' ? 'B' : 'A')

const fresh = () => ({
  state: 'idle',
  profiles: {},
  decisions: {},
  taps: {},
  gestures: {},
  stay: {},
  leds: { A: 'off', B: 'off' },
  events: [],
  match: null,
  whisperSent: false,
  timers: [],
})
let S = fresh()

// ---------- helpers ----------
const send = (c, type, data = {}) => c.ws.readyState === 1 && c.ws.send(JSON.stringify({ type, ts: Date.now(), data }))
const phonesOf = (band) => [...clients].filter((c) => c.role === 'phone' && c.band === band)
const log = (e) => {
  S.events.unshift(e)
  S.events = S.events.slice(0, 8)
  console.log(`  · ${e}`)
}
const later = (ms, fn) => S.timers.push(setTimeout(fn, ms))
const clearTimers = () => {
  S.timers.forEach(clearTimeout)
  S.timers = []
}

function stateFor(c) {
  const d = { state: S.state }
  if (S.state === 'mutual') d.match_gesture = GESTURE
  if (c.role === 'phone') {
    d.you_joined = !!S.profiles[c.band]
    if (AFTER_SPARK.includes(S.state)) d.their_name = S.profiles[other(c.band)]?.name
  }
  return d
}

function roomUpdate() {
  const showValues = S.match && ['matched', 'mutual', ...AFTER_SPARK].includes(S.state)
  return {
    state: S.state,
    leds: S.leds,
    last_events: S.events,
    shared_values: showValues ? S.match.shared_values : [],
    match_gesture: S.state === 'mutual' ? GESTURE : undefined,
    names: { A: S.profiles.A?.name, B: S.profiles.B?.name },
  }
}

function broadcast() {
  for (const c of clients) {
    if (c.role === 'room') send(c, 'room_update', roomUpdate())
    else send(c, 'state_changed', stateFor(c))
  }
}

function led(mode) {
  S.leds = { A: mode, B: mode }
  for (const c of clients) if (c.role === 'console') send(c, 'set_led', { band: 'both', mode })
}

function setState(state, ledMode) {
  S.state = state
  if (ledMode) led(ledMode)
  log(`state → ${state}`)
  broadcast()
}

// pass, timeout and hide all look the same to the other person
function endQuietly(state) {
  clearTimers()
  setState(state, 'off')
}

// ---------- canned AI ----------
function makeMatch() {
  const A = S.profiles.A
  const B = S.profiles.B
  return {
    shared_values: ['Family comes first', 'Weekends outdoors over nightlife', 'Looking for something real'],
    reasons: {
      A: `${B.name} puts family first, lives for weekends outside, and wants something real — just like you.`,
      B: `${A.name} is happiest outdoors, family comes first, and is looking for something real.`,
    },
    evidence: {
      A: [`${B.name}: “${B.matters_most}”`, `${B.name}: “${B.weekend}”`],
      B: [`${A.name}: “${A.matters_most}”`, `${A.name}: “${A.weekend}”`],
    },
    openers: {
      A: `Ask ${B.name} what a perfect weekend looks like — you two might already have plans in common.`,
      B: `Ask ${A.name} about the best trip they've ever taken.`,
    },
  }
}

function sendMatch(c) {
  const b = c.band
  send(c, 'match_found', {
    shared_values: S.match.shared_values,
    reason: S.match.reasons[b],
    evidence: S.match.evidence[b],
    opener: S.match.openers[b],
  })
}

function sendWhisper(c) {
  send(c, 'whisper_ready', { band: c.band, audio_url: null, text: S.match.openers[c.band] })
}

// ---------- flow ----------
function onJoin(d) {
  const band = d?.band === 'B' ? 'B' : d?.band === 'A' ? 'A' : null
  if (!band || !d.consent || !d.name) return
  S.profiles[band] = d
  log(`${band} joined (${d.name})`)
  if (S.profiles.A && S.profiles.B && ['idle', 'profiling'].includes(S.state)) {
    setState('profiling', 'white')
    later(1500, startMatch)
  } else if (S.state === 'idle') setState('profiling')
  else broadcast()
}

function startMatch() {
  S.match = makeMatch()
  S.decisions = {}
  S.state = 'matched'
  led('purple_slow')
  log('match found')
  broadcast()
  for (const c of clients) if (c.role === 'phone') sendMatch(c)
  later(DECISION_TIMEOUT_MS, () => S.state === 'matched' && endQuietly('expired'))
}

function onTap(band, count, ts) {
  log(`tap ${band} ×${count}`)
  if (S.state === 'matched') {
    if (count === 2) return endQuietly('passed')
    S.decisions[band] = true
    phonesOf(band).forEach((c) => send(c, 'decision_status', { you_said_yes: true }))
    if (S.decisions.A && S.decisions.B) {
      clearTimers()
      S.taps = {}
      S.gestures = {}
      setState('mutual', 'purple_fast')
    } else broadcast()
    return
  }
  if (S.state === 'mutual') {
    if (count === 2) return endQuietly('passed')
    S.taps[band] = ts
    const o = S.taps[other(band)]
    if (o && Math.abs(ts - o) <= SYNC_MS) spark('tap fallback')
  }
}

function onGesture(band, gesture, ts) {
  if (S.state !== 'mutual') return
  log(`gesture ${band}: ${gesture}`)
  S.gestures[band] = { gesture, ts }
  const o = S.gestures[other(band)]
  if (o && o.gesture === gesture && Math.abs(ts - o.ts) <= SYNC_MS) spark(`same gesture (${gesture})`)
}

function spark(via) {
  S.taps = {}
  S.gestures = {}
  S.stay = {}
  log(`✦ spark via ${via}`)
  setState('meeting_confirmed', 'green')
  later(800, () => {
    S.state = 'whisper'
    S.whisperSent = true
    log('whisper ready')
    broadcast()
    for (const c of clients) if (c.role === 'phone') sendWhisper(c)
  })
}

function onStay(d) {
  const band = d?.band === 'B' ? 'B' : 'A'
  if (!AFTER_SPARK.includes(S.state)) return
  S.stay[band] = { yes: !!d.yes, contact: d.contact || '' }
  log(`stay in touch ${band}: ${d.yes ? 'yes' : 'no'}`)
  if (!(S.stay.A && S.stay.B)) return
  if (S.stay.A.yes && S.stay.B.yes) {
    const idea = 'You both love being outdoors — try a sunset walk at Lands End this weekend.'
    for (const b of ['A', 'B'])
      phonesOf(b).forEach((c) =>
        send(c, 'contact_exchanged', { name: S.profiles[other(b)].name, contact: S.stay[other(b)].contact, second_date_idea: idea }),
      )
  }
  setState('stay_in_touch')
}

function reset() {
  clearTimers()
  S = fresh()
  led('off')
  log('reset')
  broadcast()
}

// ---------- server ----------
const server = http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*')
  if (req.method === 'POST' && req.url === '/reset') {
    reset()
    res.end('ok\n')
    return
  }
  res.setHeader('Content-Type', 'text/plain')
  res.end(`Wingman mock server — state: ${S.state}\n`)
})

const wss = new WebSocketServer({ server, path: '/ws' })

wss.on('connection', (ws, req) => {
  const q = new URL(req.url, 'http://x').searchParams
  const role = ['phone', 'console', 'room'].includes(q.get('role')) ? q.get('role') : 'phone'
  const band = q.get('band') === 'B' ? 'B' : 'A'
  const c = { ws, role, band }
  clients.add(c)
  console.log(`+ ${role}${role === 'phone' ? ` ${band}` : ''} connected (${clients.size})`)

  // catch the newcomer up on the current session
  if (role === 'room') send(c, 'room_update', roomUpdate())
  else send(c, 'state_changed', stateFor(c))
  if (role === 'console') send(c, 'set_led', { band: 'both', mode: S.leds.A })
  if (role === 'phone' && S.match && ['matched', 'mutual', ...AFTER_SPARK].includes(S.state)) {
    sendMatch(c)
    if (S.decisions[band]) send(c, 'decision_status', { you_said_yes: true })
    if (S.whisperSent) sendWhisper(c)
  }

  ws.on('message', (raw) => {
    let m
    try {
      m = JSON.parse(raw)
    } catch {
      return
    }
    const d = m.data || {}
    const ts = Date.now() // mock: server receive time
    switch (m.type) {
      case 'join':
        return onJoin(d)
      case 'band_tap':
        return onTap(d.band === 'B' ? 'B' : 'A', d.count === 2 ? 2 : 1, ts)
      case 'band_gesture':
        return onGesture(d.band === 'B' ? 'B' : 'A', d.gesture, ts)
      case 'stay_in_touch':
      case 'wearer_stay_in_touch':
        return onStay(d)
      case 'hide':
        log(`${d.band || band} hid`)
        return endQuietly('hidden')
      case 'transcript':
        return log(`transcript ${d.band}: ${String(d.text).slice(0, 40)}`)
      case 'band_connected':
      case 'band_disconnected':
        return log(`${m.type} ${d.band}`)
      case 'reset':
        return reset()
    }
  })

  ws.on('close', () => {
    clients.delete(c)
    console.log(`- ${role} disconnected (${clients.size})`)
  })
})

server.listen(PORT, () => {
  console.log(`Wingman mock server on :${PORT}  (ws path /ws, POST /reset)`)
})
