// Wingman backend — WS state machine (docs/contract.md). AI runs on Mastra (src/mastra): tools + agents + workflow.
//   cp .env.example .env   (add GEMINI_API_KEY)
//   npm run dev            (port 8787)
import http from 'node:http'
import { readFileSync } from 'node:fs'
import { WebSocketServer } from 'ws'
import { buildProfile as runTasteProfile, matchPair, secondDateIdea } from './mastra/run.js'
import { hasVoice, speak } from './ai/elevenlabs.mjs'
import { voiceReady, voiceSession } from './voice/agent.mjs'
import { DEMO_FAIL, DEMO_MODE, TIMEOUTS, cachedMatch, cachedProfile, fallbackMatch, fallbackProfile, guarded, rememberMatch, rememberProfile } from './demo/safety.mjs'

const PORT = Number(process.env.PORT || 8787)
const MOCK_AI = !!process.env.MOCK_AI
const GESTURE = (() => {
  try {
    return JSON.parse(readFileSync(new URL('../../web/src/config/gesture.json', import.meta.url))).id
  } catch {
    return 'placeholder'
  }
})()
const SYNC_MS = 1000
const DECISION_TIMEOUT_MS = 120_000
const AFTER_SPARK = ['meeting_confirmed', 'whisper', 'stay_in_touch']
const SHOW_MATCH = ['matched', 'mutual', ...AFTER_SPARK]

const clients = new Set() // { ws, role, band, origin }
const audio = new Map() // id -> Buffer
const ttsCache = new Map() // chat line -> mp3 (Wingman speaks its chat messages)
const other = (b) => (b === 'A' ? 'B' : 'A')

const fresh = () => ({
  state: 'idle',
  profiles: {}, // join payloads
  built: {}, // band -> Profile Agent output
  failed: {}, // band -> failed source ids
  confirmed: {},
  pendingConfirm: {}, // confirms that arrived before the profile finished building
  decisions: {},
  taps: {},
  gestures: {},
  stay: {},
  leds: { A: 'off', B: 'off' },
  events: [],
  match: null,
  whisper: {}, // band -> { audio_url, text }
  whisperSent: false,
  timers: [],
  epoch: 0, // bumps on reset so stale async work is dropped
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
const errorTo = (band, message, retry = false) => phonesOf(band).forEach((c) => send(c, 'error', { code: 'backend', message, retry }))

function stateFor(c) {
  const d = { state: S.state }
  if (S.state === 'mutual') d.match_gesture = GESTURE
  if (c.role === 'phone') {
    d.you_joined = !!S.profiles[c.band]
    d.you_confirmed = !!S.confirmed[c.band]
    if (AFTER_SPARK.includes(S.state)) d.their_name = S.profiles[other(c.band)]?.name
  }
  return d
}

function roomUpdate() {
  const m = S.match && SHOW_MATCH.includes(S.state) ? S.match : null
  return {
    state: S.state,
    leds: S.leds,
    last_events: S.events,
    core_overlap: m?.core_overlap ?? [],
    score: m?.score ?? null,
    type_fit: m ? m.type_fit.a_fits_b && m.type_fit.b_fits_a : false,
    shared_specifics: m?.shared_specifics ?? [],
    shared_values: m?.shared_values ?? [],
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

function endQuietly(state) {
  clearTimers()
  setState(state, 'off')
}

function sendProfile(c) {
  const b = c.band
  if (!S.built[b]) return
  send(c, 'profile_ready', { core: S.built[b].core, highlights: S.built[b].highlights, says_vs_shows: S.built[b].says_vs_shows ?? null, failed_sources: S.failed[b] || [] })
}

function sendMatch(c) {
  const b = c.band
  const m = S.match
  send(c, 'match_found', {
    score: m.score ?? null,
    core_overlap: m.core_overlap,
    type_fit: m.type_fit.a_fits_b && m.type_fit.b_fits_a,
    shared_specifics: m.shared_specifics,
    shared_values: m.shared_values,
    reason: m.reasons_for_each[b],
    evidence: m.evidence,
    opener: m.opener_for_each[b],
  })
}

function sendWhisper(c) {
  const w = S.whisper[c.band]
  if (!w) return
  const audio_url = w.audioId ? `${c.origin}/audio/${w.audioId}.mp3` : null
  send(c, 'whisper_ready', { band: c.band, audio_url, text: w.text })
}

// ---------- AI pipeline ----------
async function buildProfile(band, epoch) {
  const p = S.profiles[band]
  const t0 = Date.now()
  let res
  try {
    res = await guarded('profile', runTasteProfile(p), TIMEOUTS.profile)
  } catch (e) {
    log(`${band} taste-profile workflow failed: ${e.message}`)
    res = { profile: null, failed: [], error: e.message }
  }
  if (epoch !== S.epoch || !S.profiles[band]) return
  if (res.profile?.core?.length && !res.error) rememberProfile(p.name, res.profile)
  else {
    // AI failed or returned nothing: last good profile for this person (demo), else one built from their real data
    const cached = DEMO_MODE && cachedProfile(p.name)
    log(`${band} taste-profile fallback: ${cached ? 'cached profile' : 'built from their data'}`)
    res = { ...res, profile: cached || fallbackProfile(p, res.profile), error: DEMO_MODE ? undefined : res.error }
  }
  const { profile, failed, error } = res
  log(`${band} taste-profile: ${profile.core.length} core, ${profile.highlights.length} highlights${failed.length ? `, failed: ${failed.join(',')}` : ''} (${Date.now() - t0}ms)`)
  if (error) {
    log(`${band} ${error}`)
    errorTo(band, error, !profile.highlights.length)
  }
  S.built[band] = profile
  S.failed[band] = failed
  phonesOf(band).forEach(sendProfile)
  if (S.pendingConfirm[band]) onConfirm(S.pendingConfirm[band])
}

async function startMatch(epoch) {
  const A = { name: S.profiles.A.name, profile: S.built.A, join: S.profiles.A }
  const B = { name: S.profiles.B.name, profile: S.built.B, join: S.profiles.B }
  let m
  try {
    const t0 = Date.now()
    m = await guarded('match', matchPair(A, B), TIMEOUTS.match)
    log(`match agent: compatible=${m.compatible} (${Date.now() - t0}ms)`)
    if (m.compatible) rememberMatch(A.name, B.name, m)
  } catch (e) {
    log(`match agent failed: ${e.message}`)
    if (!DEMO_MODE) {
      for (const b of ['A', 'B']) errorTo(b, `AI match failed: ${e.message}`)
      if (epoch === S.epoch) setState('no_match', 'off')
      return
    }
    const cached = cachedMatch(A.name, B.name)
    m = cached || fallbackMatch(A, B)
    log(`match fallback: ${cached ? 'cached match' : 'built from shared data'}`)
  }
  if (epoch !== S.epoch) return
  if (!m.compatible && DEMO_MODE) {
    log('DEMO_MODE: agent said not compatible, matching anyway')
    m.compatible = true
  }
  if (!m.compatible) return setState('no_match', 'off')
  S.match = m
  S.decisions = {}
  S.state = 'matched'
  led('purple_slow')
  log('match found')
  broadcast()
  for (const c of clients) if (c.role === 'phone') sendMatch(c)
  later(DECISION_TIMEOUT_MS, () => S.state === 'matched' && endQuietly('expired'))
}

// Openers are no longer spoken to the wearer (product decision); the text stays in the match for the room view.
function prepareWhispers() {
  prepareWhispersSync()
}

// ---------- flow ----------
function onJoin(d) {
  const band = d?.band === 'B' ? 'B' : d?.band === 'A' ? 'A' : null
  if (!band || !d.consent || !d.source_consent || !d.name) return
  S.profiles[band] = d
  S.confirmed[band] = false
  delete S.built[band]
  delete S.pendingConfirm[band]
  log(`${band} joined (${d.name}) · sources: ${Object.keys(d.sources || {}).join(', ')}`)
  if (S.state === 'idle') setState('profiling')
  else broadcast()
  buildProfile(band, S.epoch)
}

function onConfirm(d) {
  const band = d?.band === 'B' ? 'B' : 'A'
  if (!S.built[band]) return void (S.pendingConfirm[band] = d)
  delete S.pendingConfirm[band]
  const removed = new Set(d.removed || [])
  S.built[band].core = S.built[band].core.filter((x) => !removed.has(x.id))
  S.built[band].highlights = S.built[band].highlights.filter((x) => !removed.has(x.id))
  S.confirmed[band] = true
  log(`${band} confirmed profile${removed.size ? ` (removed ${removed.size})` : ''}`)
  if (S.confirmed.A && S.confirmed.B && ['idle', 'profiling'].includes(S.state)) {
    setState('profiling', 'white')
    startMatch(S.epoch)
  } else broadcast()
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
      prepareWhispers()
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
  const epoch = S.epoch
  const deliver = () => {
    if (epoch !== S.epoch) return
    if (!S.whisper.A) prepareWhispersSync()
    S.state = 'whisper'
    S.whisperSent = true
    log('whisper ready')
    broadcast()
    for (const c of clients) if (c.role === 'phone') sendWhisper(c)
  }
  later(500, () => deliver())
}

function prepareWhispersSync() {
  for (const b of ['A', 'B']) S.whisper[b] = { text: S.match.opener_for_each[b], audioId: null }
}

async function onStay(d) {
  const band = d?.band === 'B' ? 'B' : 'A'
  if (!AFTER_SPARK.includes(S.state)) return
  S.stay[band] = { yes: !!d.yes, contact: d.contact || '' }
  log(`stay in touch ${band}: ${d.yes ? 'yes' : 'no'}`)
  if (!(S.stay.A && S.stay.B)) return
  const epoch = S.epoch
  if (S.stay.A.yes && S.stay.B.yes) {
    let idea = 'Pick one thing you both love and go do it this weekend.'
    if (!MOCK_AI) {
      try {
        idea = (await guarded('idea', secondDateIdea(S.match), TIMEOUTS.idea)) || idea
      } catch (e) {
        log(`second date idea failed: ${e.message}`)
      }
    }
    if (epoch !== S.epoch) return
    for (const b of ['A', 'B'])
      phonesOf(b).forEach((c) =>
        send(c, 'contact_exchanged', { name: S.profiles[other(b)].name, contact: S.stay[other(b)].contact, second_date_idea: idea }),
      )
  }
  setState('stay_in_touch')
}

function reset() {
  clearTimers()
  const epoch = S.epoch + 1
  S = fresh()
  S.epoch = epoch
  audio.clear()
  led('off')
  log('reset')
  broadcast()
}

// ---------- server ----------
const server = http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*')
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type')
  if (req.method === 'OPTIONS') return res.end()
  if (req.method === 'POST' && req.url === '/reset') {
    reset()
    return res.end('ok\n')
  }
  const m = /^\/audio\/([0-9a-f-]+)\.mp3$/.exec(req.url || '')
  if (m && audio.has(m[1])) {
    res.setHeader('Content-Type', 'audio/mpeg')
    return res.end(audio.get(m[1]))
  }
  if (req.method === 'POST' && req.url === '/tts') {
    if (!hasVoice()) return void ((res.statusCode = 503), res.end())
    let body = ''
    req.on('data', (c) => (body += c))
    req.on('end', async () => {
      try {
        const text = String(JSON.parse(body || '{}').text || '').trim().slice(0, 400)
        if (!text) return void ((res.statusCode = 400), res.end())
        let buf = ttsCache.get(text)
        if (!buf) {
          buf = await speak(text)
          if (ttsCache.size > 200) ttsCache.delete(ttsCache.keys().next().value)
          ttsCache.set(text, buf)
        }
        res.setHeader('Content-Type', 'audio/mpeg')
        res.end(buf)
      } catch (e) {
        res.statusCode = 502
        res.end(String(e.message))
      }
    })
    return
  }
  if (req.method === 'GET' && req.url === '/voice/session') {
    res.setHeader('Content-Type', 'application/json')
    if (!voiceReady()) {
      res.statusCode = 503
      return res.end(JSON.stringify({ error: 'Voice chat is not set up (ELEVENLABS_API_KEY + ELEVENLABS_AGENT_ID).' }))
    }
    voiceSession()
      .then((s) => res.end(JSON.stringify(s)))
      .catch((e) => ((res.statusCode = 502), res.end(JSON.stringify({ error: e.message }))))
    return
  }
  if (req.url === '/health') {
    res.setHeader('Content-Type', 'application/json')
    return res.end(
      JSON.stringify({
        state: S.state,
        mock_ai: MOCK_AI,
        demo_mode: DEMO_MODE,
        demo_fail: DEMO_FAIL || null,
        agents: 'mastra',
        gemini: !!process.env.GEMINI_API_KEY,
        model: process.env.GEMINI_MODEL || 'gemini-3.8-flash',
        elevenlabs: hasVoice(),
        voice_chat: voiceReady(),
        reddit_oauth: !!(process.env.REDDIT_CLIENT_ID && process.env.REDDIT_CLIENT_SECRET),
      }),
    )
  }
  res.setHeader('Content-Type', 'text/plain')
  res.end(`Wingman server — state: ${S.state}\n`)
})

const wss = new WebSocketServer({ server, path: '/ws', maxPayload: 20 * 1024 * 1024 })

wss.on('connection', (ws, req) => {
  const q = new URL(req.url, 'http://x').searchParams
  const role = ['phone', 'console', 'room'].includes(q.get('role')) ? q.get('role') : 'phone'
  const band = q.get('band') === 'B' ? 'B' : 'A'
  const proto = req.headers['x-forwarded-proto'] === 'https' ? 'https' : 'http'
  const c = { ws, role, band, origin: `${proto}://${req.headers.host}` }
  clients.add(c)
  console.log(`+ ${role}${role === 'phone' ? ` ${band}` : ''} connected (${clients.size})`)

  if (role === 'room') send(c, 'room_update', roomUpdate())
  else send(c, 'state_changed', stateFor(c))
  if (role === 'console') send(c, 'set_led', { band: 'both', mode: S.leds.A })
  if (role === 'phone' && S.built[band] && !S.confirmed[band]) sendProfile(c)
  if (role === 'phone' && S.match && SHOW_MATCH.includes(S.state)) {
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
    const ts = Date.now() // single server clock for sync checks
    switch (m.type) {
      case 'join':
        return onJoin(d)
      case 'profile_confirm':
        return onConfirm(d)
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
        if (S.profiles[d.band]) S.profiles[d.band].transcript = String(d.text || '').slice(0, 2000)
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
  console.log(`Wingman server on :${PORT}`)
  console.log(`  agents: Mastra · ${MOCK_AI ? 'MOCK_AI (canned output)' : process.env.GEMINI_API_KEY ? `google/${process.env.GEMINI_MODEL || 'gemini-3.8-flash'}` : 'MISSING GEMINI_API_KEY'}`)
  console.log(`  demo mode: ${DEMO_MODE ? `ON (timeouts profile ${TIMEOUTS.profile / 1000}s · match ${TIMEOUTS.match / 1000}s, cache + fallbacks, always match)` : 'off'}${DEMO_FAIL ? ` · rehearsing failure: ${DEMO_FAIL}` : ''}`)
  console.log(`  elevenlabs: ${hasVoice() ? 'on' : 'off (browser speech)'} · voice chat: ${voiceReady() ? 'on' : 'off'}`)
  console.log(`  reddit oauth: ${process.env.REDDIT_CLIENT_ID ? 'on' : 'off (anonymous requests are usually blocked)'}`)
})
