// Wingman backend — WS state machine (docs/contract.md). AI runs on Mastra (src/mastra): tools + agents + workflow.
//   cp .env.example .env   (add GEMINI_API_KEY)
//   npm run dev            (port 8787)
import http from 'node:http'
import { readFileSync } from 'node:fs'
import { WebSocketServer } from 'ws'
import { buildProfile as runTasteProfile, matchPair, secondDateIdea } from './mastra/run.js'
import { hasVoice, speak } from './ai/elevenlabs.mjs'
import { voiceReady, voiceSession } from './voice/agent.mjs'
import { DEMO_FAIL, DEMO_MODE, TIMEOUTS, cachedMatch, clearDemoCache, cachedProfile, fallbackMatch, fallbackProfile, guarded, rememberMatch, rememberProfile } from './demo/safety.mjs'

const PORT = Number(process.env.PORT || 8787)
const HOST = process.env.HOST || '127.0.0.1'
const MOTION_MODE = process.env.HARDWARE_MODE === 'accel-latch' ? 'accel-latch' : 'pose'
const STAGE_DEMO = process.env.STAGE_DEMO === '1'
const STAGE_PROFILE = {
  name: 'Holly',
  traits: ['Curious about how people think', 'Drawn to easy conversation and dry humor', 'Looks for warmth, honesty, and follow-through'],
}
const MOTION_TTL_MS = 2500
const HEART_TTL_MS = 10_000
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
const FINDING = ['mutual', ...AFTER_SPARK] // both said yes: now they get a place to meet and how to spot each other
// Where two people meet once both said yes. Set per venue: MEET_SPOTS="by the bar|next to the stage|at the entrance"
const MEET_SPOTS = (process.env.MEET_SPOTS || 'by the bar|next to the big screen|by the entrance').split('|').map((s) => s.trim()).filter(Boolean)
const SHOW_MATCH = ['matched', 'mutual', ...AFTER_SPARK]

const clients = new Set() // { ws, role, band, origin }
const audio = new Map() // id -> Buffer
const ttsCache = new Map() // chat line -> mp3 (Wingman speaks its chat messages)
const other = (b) => (b === 'A' ? 'B' : 'A')

const fresh = () => ({
  state: 'idle',
  matching: false, // match agent in flight
  profiles: {}, // join payloads
  built: {}, // band -> Profile Agent output
  failed: {}, // band -> failed source ids
  confirmed: {},
  pendingConfirm: {}, // confirms that arrived before the profile finished building
  decisions: {},
  taps: {},
  gestures: {},
  raised: {}, // band -> raised (a fresh down->up) since this round's mutual began
  stay: {},
  leds: { A: 'off', B: 'off' },
  events: [],
  match: null,
  whisper: {}, // band -> { audio_url, text }
  wearing: {}, // band -> what they said they're wearing (only shown to the other phone after both said yes)
  spot: '', // where to meet, picked when both said yes
  whisperSent: false,
  timers: [],
  epoch: 0, // bumps on reset so stale async work is dropped
})
let S = fresh()
// Live heart rate per band (WHOOP via the console). Health data: only ever sent to that band's own phone.
let vitals = { A: null, B: null } // { bpm, ts }
// Live band posture describes the hardware, not the round, so it survives a reset.
let poses = { A: 'unknown', B: 'unknown' }
let poseTimes = { A: 0, B: 0 }
const sendPoses = () => {
  for (const c of clients) if (c.role === 'phone') send(c, 'band_pose', { you: poses[c.band], them: poses[other(c.band)], motion_mode: MOTION_MODE })
}
const POSES = ['up', 'down', 'unknown']

// ---------- helpers ----------
const send = (c, type, data = {}) => c.ws.readyState === 1 && c.ws.send(JSON.stringify({ type, ts: Date.now(), data }))
const phonesOf = (band) => [...clients].filter((c) => c.role === 'phone' && c.band === band)
const log = (e) => {
  S.events.unshift(e)
  S.events = S.events.slice(0, 8)
  console.log(`  · ${e}`)
}
/** Console only: who tapped, passed, hid or said no must never reach the room screen. */
const logPrivate = (e) => console.log(`  · ${e}`)
const BAND = (b) => (b === 'A' || b === 'B' ? b : null)
const later = (ms, fn) => S.timers.push(setTimeout(fn, ms))
const clearTimers = () => {
  S.timers.forEach(clearTimeout)
  S.timers = []
}
const errorTo = (band, message, retry = false) => phonesOf(band).forEach((c) => send(c, 'error', { code: 'backend', message, retry }))

function stateFor(c) {
  const d = { state: S.state, motion_mode: MOTION_MODE, epoch: S.epoch, mock_ai: MOCK_AI }
  if (STAGE_DEMO) {
    d.stage_demo = true
    if (c.role === 'phone' && c.band === 'B' && S.state === 'profiling') d.stage_profile = STAGE_PROFILE
  }
  if (S.state === 'mutual') d.match_gesture = GESTURE
  if (FINDING.includes(S.state) && S.spot) d.meet_spot = S.spot
  if (c.role === 'phone') {
    // what the other person said they're wearing: only after both said yes, only to the other phone, never to the AI
    if (FINDING.includes(S.state) && S.wearing[other(c.band)]) d.their_wearing = S.wearing[other(c.band)]
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
    stage_demo: STAGE_DEMO,
    motion_mode: MOTION_MODE,
    mock_ai: MOCK_AI,
    leds: S.leds,
    last_events: S.events,
    overlaps: m?.overlaps ?? [],
    core_overlap: m?.core_overlap ?? [],
    type_fit: m ? m.type_fit.a_fits_b && m.type_fit.b_fits_a : false,
    shared_specifics: m?.shared_specifics ?? [],
    shared_values: m?.shared_values ?? [],
    match_gesture: S.state === 'mutual' ? GESTURE : undefined,
    meet_spot: FINDING.includes(S.state) ? S.spot : undefined,
    poses, // band posture is part of the match moment; heart rate is never on the room screen
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
    overlaps: m.overlaps ?? [],
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
  if (epoch !== S.epoch || S.profiles[band] !== p) return // a newer join for this band replaced this one
  if (res.profile?.core?.length && !res.error) rememberProfile(p.name, res.profile)
  else {
    // AI failed or returned nothing: last good profile for this person (demo), else one built from their real data
    const cached = DEMO_MODE && cachedProfile(p.name)
    log(`${band} taste-profile fallback: ${cached ? 'cached profile' : 'built from their data'}`)
    res = { ...res, profile: cached || (DEMO_MODE || !res.profile ? fallbackProfile(p, res.profile) : res.profile), error: DEMO_MODE ? undefined : res.error }
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
  if (S.pendingConfirm[band]) onConfirm(S.pendingConfirm[band], band)
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
      if (epoch === S.epoch && S.state === 'profiling') setState('no_match', 'off') // not over a hide
      return
    }
    const cached = cachedMatch(A.name, B.name)
    m = cached || fallbackMatch(A, B)
    log(`match fallback: ${cached ? 'cached match' : 'built from shared data'}`)
  }
  if (epoch !== S.epoch || S.state !== 'profiling') return // reset, hidden, or ended while the agent was thinking
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
function onJoin(d, band) {
  if (!band || !d.consent || !d.source_consent || typeof d.name !== 'string' || !d.name.trim()) return
  if (!['serious', 'open', 'friends'].includes(d.looking_for)) d.looking_for = 'open'
  if (typeof d.dealbreaker !== 'string') d.dealbreaker = ''
  if (!d.sources || typeof d.sources !== 'object') d.sources = {}
  // kept apart from the profile so it never reaches the taste or match agents
  const wearing = typeof d.wearing === 'string' ? d.wearing.trim().slice(0, 80) : ''
  delete d.wearing
  if (wearing) S.wearing[band] = wearing
  else delete S.wearing[band]
  S.profiles[band] = d
  S.confirmed[band] = false
  delete S.built[band]
  delete S.pendingConfirm[band]
  log(`${band} joined (${d.name}) · sources: ${Object.keys(d.sources || {}).join(', ')}${wearing ? ' · outfit given' : ''}`)
  if (S.state === 'idle') setState('profiling')
  else broadcast()
  buildProfile(band, S.epoch)
}

function onConfirm(d, band) {
  if (!band || !S.profiles[band]) return
  if (S.confirmed[band]) return // duplicate confirm (agent called the tool twice, phone resent)
  if (!S.built[band]) return void (S.pendingConfirm[band] = d)
  delete S.pendingConfirm[band]
  const removed = new Set(Array.isArray(d.removed) ? d.removed.map(String) : [])
  S.built[band].core = S.built[band].core.filter((x) => !removed.has(x.id))
  S.built[band].highlights = S.built[band].highlights.filter((x) => !removed.has(x.id))
  S.confirmed[band] = true
  log(`${band} confirmed profile${removed.size ? ` (removed ${removed.size})` : ''}`)
  if (S.confirmed.A && S.confirmed.B && ['idle', 'profiling'].includes(S.state) && !S.matching) {
    S.matching = true
    setState('profiling', 'white')
    const s = S // a reset swaps S; only clear this round's flag
    startMatch(S.epoch).finally(() => (s.matching = false))
  } else broadcast()
}

function onTap(band, count, ts, source) {
  logPrivate(source === 'quick_motion' ? `quick-motion acceptance ${band}` : `tap ${band} ×${count}`)
  if (S.state === 'matched') {
    if (count === 2) return endQuietly('expired') // a pass looks exactly like a timeout
    S.decisions[band] = true
    phonesOf(band).forEach((c) => send(c, 'decision_status', { you_said_yes: true }))
    if (S.decisions.A && S.decisions.B) {
      clearTimers()
      S.taps = {}
      S.gestures = {}
      S.raised = {}
      S.spot = MEET_SPOTS[Math.floor(Math.random() * MEET_SPOTS.length)] || ''
      setState('mutual', 'purple_fast')
      prepareWhispers()
    } else broadcast()
    return
  }
  if (S.state === 'mutual') {
    if (count === 2) return endQuietly('expired')
    S.taps[band] = ts
    const o = S.taps[other(band)]
    if (o && Math.abs(ts - o) <= SYNC_MS) spark('tap fallback')
  }
}

function onGesture(band, gesture, ts) {
  if (S.state !== 'mutual') return
  logPrivate(`gesture ${band}: ${gesture}`)
  S.gestures[band] = { gesture, ts }
  const o = S.gestures[other(band)]
  if (o && o.gesture === gesture && Math.abs(ts - o.ts) <= SYNC_MS) spark(`same gesture (${gesture})`)
}

function onHeartRate(band, bpm, ts, source) {
  if (bpm === null) {
    const hadValue = vitals[band] !== null
    vitals[band] = null
    if (hadValue) for (const c of phonesOf(band)) send(c, 'heart_rate', { bpm: null, at: ts, source })
    return
  }
  const v = Math.round(Number(bpm))
  if (!(v >= 30 && v <= 230)) return
  const last = vitals[band]
  const label = source === 'Apple Watch' || source === 'WHOOP' ? source : undefined
  vitals[band] = { bpm: v, ts, source: label }
  if (last && ts - last.ts < 900 && last.bpm === v) return // keep it to about one update a second
  for (const c of phonesOf(band)) send(c, 'heart_rate', { bpm: v, at: ts, source: label })
}

function onPose(band, pose, ts) {
  if (!POSES.includes(pose)) return
  poseTimes[band] = ts
  if (poses[band] === pose) return
  poses = { ...poses, [band]: pose }
  sendPoses()
  for (const c of clients) if (c.role === 'room') send(c, 'room_update', roomUpdate())
  // only a deliberate raise during mutual counts (a wrist still up from tapping "yes" doesn't)
  if (S.state === 'mutual' && pose === 'up') S.raised[band] = true
  // posture is a held state: the moment both bands are raised and up at the same time, it's the spark
  if (S.state === 'mutual' && S.raised.A && S.raised.B && poses.A === 'up' && poses.B === 'up') {
    logPrivate('both bands raised')
    spark('both bands raised')
  }
}

function spark(via) {
  S.taps = {}
  S.gestures = {}
  S.stay = {}
  log(`✦ spark via ${via}`)
  setState('meeting_confirmed', 'green')
  if (STAGE_DEMO) return
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

async function onStay(d, band) {
  if (!band || !AFTER_SPARK.includes(S.state) || S.stay[band]) return
  S.stay[band] = { yes: d.yes === true, contact: typeof d.contact === 'string' ? d.contact.slice(0, 80) : '' }
  logPrivate(`stay in touch ${band}: ${d.yes ? 'yes' : 'no'}`)
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
    if (epoch !== S.epoch || !AFTER_SPARK.includes(S.state)) return // reset or hidden while the idea was coming
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
  vitals = { A: null, B: null } // a new round may be a new wearer
  if (STAGE_DEMO) poses = { A: 'unknown', B: 'unknown' }
  led('off')
  log('reset')
  broadcast()
  sendPoses()
}

// A bridge process or HTTP source can disappear without a final status packet.
// Expire each signal independently; heart data never goes to the room screen.
setInterval(() => {
  const now = Date.now()
  for (const band of ['A', 'B']) {
    if (poses[band] !== 'unknown' && now - poseTimes[band] > MOTION_TTL_MS) onPose(band, 'unknown', now)
    if (vitals[band] && now - vitals[band].ts > HEART_TTL_MS) onHeartRate(band, null, now, vitals[band].source)
  }
}, 500).unref()

// ---------- server ----------
const server = http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*')
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type')
  if (req.method === 'OPTIONS') return res.end()
  if (req.method === 'POST' && req.url === '/demo/clear-cache') {
    clearDemoCache()
    return res.end('demo cache cleared\n')
  }
  if (req.method === 'POST' && req.url === '/reset') {
    reset()
    return res.end('ok\n')
  }
  if (req.method === 'POST' && req.url === '/demo/force-match') {
    // The authenticated hardware dashboard calls this over loopback.
    const localHost = `127.0.0.1:${server.address().port}`
    if (req.socket.remoteAddress !== '127.0.0.1' || req.headers.host !== localHost || req.headers.origin) {
      return res.writeHead(403).end('Local dashboard only.\n')
    }
    if (!STAGE_DEMO) return res.writeHead(409).end('Force Match is available in stage demo mode.\n')
    if (S.state === 'meeting_confirmed') return res.end('ok\n')
    if (S.state !== 'mutual') return res.writeHead(409).end('Open the match invitation before using Force Match.\n')
    spark('dashboard override')
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
    req.on('error', () => res.destroy())
    req.on('data', (c) => {
      body += c
      if (body.length > 4096) {
        res.statusCode = 413
        res.end()
        req.destroy()
      }
    })
    req.on('end', async () => {
      try {
        const text = String(JSON.parse(body || '{}').text || '').trim().slice(0, 600)
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
        stage_demo: STAGE_DEMO,
        demo_fail: DEMO_FAIL || null,
        agents: 'mastra',
        gemini: !!process.env.GEMINI_API_KEY,
        model: process.env.GEMINI_MODEL || 'gemini-3.8-flash',
        elevenlabs: hasVoice(),
        voice_chat: voiceReady(),
        reddit_oauth: !!(process.env.REDDIT_CLIENT_ID && process.env.REDDIT_CLIENT_SECRET),
        motion_mode: MOTION_MODE,
        hardware_bridge: [...clients].some((c) => c.hardware),
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
  const c = { ws, role, band, hardware: role === 'console' && q.get('hardware') === '1', origin: `${proto}://${req.headers.host}` }
  clients.add(c)
  console.log(`+ ${role}${role === 'phone' ? ` ${band}` : ''} connected (${clients.size})`)

  if (role === 'room') send(c, 'room_update', roomUpdate())
  else send(c, 'state_changed', stateFor(c))
  if (role === 'console') send(c, 'set_led', { band: 'both', mode: S.leds.A })
  if (role === 'phone' && vitals[band] && Date.now() - vitals[band].ts < HEART_TTL_MS) send(c, 'heart_rate', { bpm: vitals[band].bpm, at: vitals[band].ts, source: vitals[band].source })
  if (role === 'phone') send(c, 'band_pose', { you: poses[band], them: poses[other(band)], motion_mode: MOTION_MODE })
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
    const d = m?.data && typeof m.data === 'object' ? m.data : {}
    const ts = Date.now() // single server clock for sync checks
    // a phone always acts as its own band; the console (dev panel / band bridge) names the band
    const who = role === 'phone' ? band : BAND(d.band)
    try {
      if (STAGE_DEMO) {
        if (m?.type === 'stage_finish_voice' && role === 'phone' && band === 'B' && d.epoch === S.epoch && S.state === 'idle') {
          setState('profiling')
          return
        }
        if (m?.type === 'stage_confirm_profile' && role === 'phone' && band === 'B' && d.epoch === S.epoch && S.state === 'profiling') {
          // Finder starts a fresh hardware round directly. The bridge arms it
          // and reports each latch once the new generation is ready.
          poses = { A: 'unknown', B: 'unknown' }
          setState('mutual', 'purple_fast')
          sendPoses()
          return
        }
        if (m?.type === 'reset' && role === 'room') return reset()
        if (!c.hardware || !who) return
        if (m?.type === 'heart_rate') return onHeartRate(who, d.bpm, ts, d.source)
        if (m?.type === 'band_pose' && d.source === 'quick_motion' && MOTION_MODE === 'accel-latch') {
          return onPose(who, d.pose, ts)
        }
        return
      }
      switch (m?.type) {
        case 'join':
          return onJoin(d, who)
        case 'profile_confirm':
          return onConfirm(d, who)
        case 'band_tap':
          if (role === 'console' && who) onTap(who, d.count === 2 ? 2 : 1, ts, d.source)
          return
        case 'band_gesture':
          if (role === 'console' && who) onGesture(who, d.gesture, ts)
          return
        case 'stay_in_touch':
        case 'wearer_stay_in_touch':
          return void onStay(d, who).catch((e) => console.error('stay failed', e))
        case 'hide':
          logPrivate(`${who} hid`)
          return endQuietly('hidden')
        case 'heart_rate':
          if (role === 'console' && who) onHeartRate(who, d.bpm, ts, d.source)
          return
        case 'band_pose':
          if (role === 'console' && who) onPose(who, d.pose, ts)
          return
        case 'transcript':
          if (who && S.profiles[who]) S.profiles[who].transcript = String(d.text || '').slice(0, 2000)
          return
        case 'band_connected':
        case 'band_disconnected':
          return log(`${m.type} ${who ?? ''}`)
        case 'reset':
          return reset()
      }
    } catch (e) {
      console.error(`message ${m?.type} failed:`, e) // never let one bad message take the server down
    }
  })

  ws.on('close', () => {
    clients.delete(c)
    if (c.hardware && ![...clients].some((peer) => peer.hardware)) {
      for (const b of ['A', 'B']) {
        onPose(b, 'unknown', Date.now())
        onHeartRate(b, null, Date.now(), vitals[b]?.source)
      }
    }
    console.log(`- ${role} disconnected (${clients.size})`)
  })
})

server.listen(PORT, HOST, () => {
  console.log(`Wingman server on :${server.address().port}`)
  console.log(`  agents: Mastra · ${MOCK_AI ? 'MOCK_AI (canned output)' : process.env.GEMINI_API_KEY ? `google/${process.env.GEMINI_MODEL || 'gemini-3.8-flash'}` : 'MISSING GEMINI_API_KEY'}`)
  console.log(`  demo mode: ${DEMO_MODE ? `ON (timeouts profile ${TIMEOUTS.profile / 1000}s · match ${TIMEOUTS.match / 1000}s, cache + fallbacks, always match)` : 'off'}${DEMO_FAIL ? ` · rehearsing failure: ${DEMO_FAIL}` : ''}`)
  console.log(`  elevenlabs: ${hasVoice() ? 'on' : 'off (browser speech)'} · voice chat: ${voiceReady() ? 'on' : 'off'}`)
  console.log(`  reddit oauth: ${process.env.REDDIT_CLIENT_ID ? 'on' : 'off (anonymous requests are usually blocked)'}`)
})
