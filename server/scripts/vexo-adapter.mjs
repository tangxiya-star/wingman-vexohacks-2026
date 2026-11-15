// Existing console protocol compatibility. In hardware mode, `up` represents
// this round's confirmed quick-motion latch, never a claim about held posture.
import { randomUUID } from 'node:crypto'

const OWNERS = { A: 62, B: 77 }
const SOURCES = { A: 'Apple Watch', B: 'WHOOP' }
const COMPLETED_STAGES = new Set(['meeting_confirmed', 'whisper', 'stay_in_touch'])
const validGeneration = (v) => typeof v === 'string' && v.length > 0 && v.length <= 128 && v !== 'unavailable'

export function currentMotion(snapshot, generation, nowMs) {
  if (!snapshot || snapshot.mode !== 'accel-latch' || !validGeneration(generation)
      || snapshot.reset_generation !== generation || !Array.isArray(snapshot.bands)) return null
  const now = nowMs / 1000
  const fresh = (t) => Number.isFinite(t) && now - t <= 2 && t - now <= 1
  if (!fresh(snapshot.server_time)) return null
  const bands = {}
  for (const [owner, number] of Object.entries(OWNERS)) {
    const matches = snapshot.bands.filter((b) => b?.band_number === number)
    if (matches.length !== 1) return null
    const b = matches[0]
    if (b.mode !== 'accel-latch' || b.reset_generation !== generation
        || b.connected !== true || b.ready !== true || !fresh(b.updated_at)
        || b.raised !== false || typeof b.active !== 'boolean'
        || b.triggered !== b.active
        || b.status !== (b.active ? 'triggered' : 'waiting_motion')) return null
    bands[owner] = b
  }
  return bands
}

export class VexoBridgeAdapter {
  constructor({ send, beginRound, stopRound = async () => {}, now = Date.now, log = () => {} }) {
    Object.assign(this, { send, beginRound, stopRound, now, log })
    this.online = false
    this.stage = null
    this.round = null
    this.snapshot = null
    this.instanceId = randomUUID()
    this.counter = 0
    this.poses = {}
    this.hearts = {}
    this.stopping = Promise.resolve()
  }

  connect() {
    this.online = true
    this.stage = null
    this.poses = {}
    this.hearts = {}
    this.invalidateMotion()
    this.invalidateHeart()
  }

  disconnect() {
    this.online = false
    this.stage = null
    this.snapshot = null
    return this._dropRound('disconnected')
  }

  _pose(band, pose, force = false) {
    if (!this.online) return
    const previous = this.poses[band]
    // 300 ms polling + 750 ms heartbeat => unchanged poses <=900 ms apart.
    if (!force && previous?.pose === pose && this.now() - previous.at < 750) return
    this.send('band_pose', { band, pose, source: 'quick_motion', motion_mode: 'accel-latch' })
    this.poses[band] = { pose, at: this.now() }
  }

  invalidateMotion() {
    this.snapshot = null
    for (const band of Object.keys(OWNERS)) this._pose(band, 'unknown')
  }

  _dropRound(reason) {
    const previous = this.round
    this.round = null
    if (!previous) return this.stopping
    previous.abort.abort()
    this.stopping = this.stopping.then(() => this.stopRound({ roundId: previous.id, reason }))
      .catch(() => this.log('Hardware round stop unavailable.'))
    return this.stopping
  }

  async _startRound(stage) {
    const stopping = this._dropRound('new_round')
    const round = {
      id: `${this.instanceId}:${++this.counter}`, stage, generation: null,
      accepted: { A: false, B: false }, active: { A: false, B: false },
      abort: new AbortController(),
    }
    this.round = round
    this.invalidateMotion()
    try {
      await stopping
      if (!this.online || this.round !== round) return
      const result = await this.beginRound({ roundId: round.id, stage, signal: round.abort.signal })
      if (!this.online || this.round !== round || round.abort.signal.aborted) return
      const generation = typeof result === 'string' ? result : result?.generation
      if (!validGeneration(generation)) throw new Error('Invalid reset generation')
      round.generation = generation
      this.log('Fresh hardware round started; waiting for both bands.')
    } catch {
      if (this.round === round && this.online) {
        this.invalidateMotion()
        this.log('Hardware round unavailable. Reset the Wingman round to retry.')
      }
    }
  }

  handleServerState(stage) {
    if (!this.online || typeof stage !== 'string' || stage === this.stage) return Promise.resolve()
    const previous = this.stage
    this.stage = stage
    if (stage === 'matched') return this._startRound(stage)
    if (stage === 'mutual') {
      if (previous === 'matched' && this.round?.generation
          && this.round.accepted.A && this.round.accepted.B) {
        this._applyMotion()
        return Promise.resolve()
      }
      // Phones/dev controls reached mutual without both hardware acceptances.
      return this._startRound(stage)
    }
    // The coordinator's approach haptics continue after the spark. Keep its
    // ownership and fresh latched status until end/reset, without new accepts.
    if (COMPLETED_STAGES.has(stage)) {
      this._applyMotion()
      return Promise.resolve()
    }
    this.invalidateMotion()
    return this._dropRound(stage)
  }

  handleMotionSnapshot(snapshot) {
    this.snapshot = snapshot
    this._applyMotion()
  }

  _applyMotion() {
    if (!this.online) return
    const round = this.round
    const bands = round && currentMotion(this.snapshot, round.generation, this.now())
    if (!bands || (!['matched', 'mutual'].includes(this.stage) && !COMPLETED_STAGES.has(this.stage))) {
      for (const band of Object.keys(OWNERS)) this._pose(band, 'unknown')
      return
    }
    if (COMPLETED_STAGES.has(this.stage)) {
      for (const band of Object.keys(OWNERS)) this._pose(band, bands[band].active ? 'up' : 'down')
      return
    }
    // Both fresh current-generation acknowledgements are required before any
    // acceptance. Before mutual the server sees readiness, never a cached up.
    if (this.stage === 'matched') {
      for (const band of Object.keys(OWNERS)) this._pose(band, 'down')
    }
    for (const band of Object.keys(OWNERS)) {
      const rising = bands[band].active && !round.active[band]
      round.active[band] = bands[band].active
      if (rising && !round.accepted[band]) {
        round.accepted[band] = true
        if (this.stage === 'matched') {
          // Semantic yes adapter, not an assertion that a physical tap occurred.
          this.send('band_tap', { band, count: 1, source: 'quick_motion' })
        }
      }
    }
    if (this.stage === 'mutual' && this.round === round) {
      for (const band of Object.keys(OWNERS)) this._pose(band, bands[band].active ? 'up' : 'down')
    }
  }

  handleHeartSnapshot(snapshot) {
    for (const [band, key] of [['A', 'apple_watch_bpm'], ['B', 'bpm']]) {
      const value = snapshot?.[key]
      const bpm = Number.isFinite(value) && value >= 30 && value <= 230 ? Math.round(value) : null
      if (!this.online) continue
      // The local endpoint expires each source to null. Never substitute the
      // other wearer's reading when either source disappears.
      if (bpm !== null || this.hearts[band] !== null) {
        this.send('heart_rate', { band, bpm, source: SOURCES[band] })
      }
      this.hearts[band] = bpm
    }
  }

  invalidateHeart() { this.handleHeartSnapshot(null) }
}
