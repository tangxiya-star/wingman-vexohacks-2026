import test from 'node:test'
import assert from 'node:assert/strict'
import { VexoBridgeAdapter } from '../scripts/vexo-adapter.mjs'

function harness(overrides = {}) {
  const messages = [], starts = [], stops = []
  let now = 100_000
  const adapter = new VexoBridgeAdapter({
    send: (type, data) => messages.push({ type, data }), now: () => now,
    beginRound: async (round) => { starts.push(round); return { generation: `round-${starts.length}` } },
    stopRound: async (round) => { stops.push(round) }, ...overrides,
  })
  adapter.connect()
  messages.length = 0
  const snapshot = (generation = 'round-1', active = [false, false]) => ({
    mode: 'accel-latch', reset_generation: generation, server_time: now / 1000,
    bands: [62, 77].map((band_number, i) => ({
      band_number, mode: 'accel-latch', reset_generation: generation,
      connected: true, ready: true, updated_at: now / 1000,
      status: active[i] ? 'triggered' : 'waiting_motion', raised: false,
      triggered: active[i], active: active[i],
    })),
  })
  return { adapter, messages, starts, stops, snapshot,
    advance: (ms) => { now += ms },
    of: (type) => messages.filter((m) => m.type === type).map((m) => m.data) }
}

test('one deliberate action each accepts matched then confirms mutual in the same round', async () => {
  const h = harness()
  await h.adapter.handleServerState('matched')
  assert.equal(h.starts.length, 1)
  h.adapter.handleMotionSnapshot(h.snapshot('previous-round', [true, true]))
  assert.deepEqual(h.of('band_tap'), [])
  h.adapter.handleMotionSnapshot(h.snapshot())
  h.adapter.handleMotionSnapshot(h.snapshot('round-1', [true, false]))
  assert.deepEqual(h.of('band_tap'), [{ band: 'A', count: 1, source: 'quick_motion' }])
  h.adapter.handleMotionSnapshot(h.snapshot('round-1', [true, true]))
  assert.deepEqual(h.of('band_tap').map((d) => d.band), ['A', 'B'])
  assert.equal(h.of('band_pose').some((d) => d.pose === 'up'), false)

  await h.adapter.handleServerState('mutual')
  assert.equal(h.starts.length, 1, 'yes and confirmation reuse the same two actions')
  assert.deepEqual(h.of('band_pose').slice(-2).map((d) => [d.band, d.pose]), [['A', 'up'], ['B', 'up']])
  const beforeHeartbeat = h.of('band_pose').length
  h.advance(900)
  h.adapter.handleMotionSnapshot(h.snapshot('round-1', [true, true]))
  assert.equal(h.of('band_pose').length, beforeHeartbeat + 2)
  assert.equal(h.of('band_tap').length, 2)
  await h.adapter.handleServerState('meeting_confirmed')
  await h.adapter.handleServerState('whisper')
  assert.equal(h.stops.length, 0, 'approach haptics continue after the spark')
  await h.adapter.handleServerState('idle')
  assert.equal(h.stops.length, 1)
})

test('mutual from another control starts a new round and ignores its old latches', async () => {
  const h = harness()
  await h.adapter.handleServerState('matched')
  h.adapter.handleMotionSnapshot(h.snapshot('round-1', [true, false]))
  await h.adapter.handleServerState('mutual')
  assert.equal(h.starts.length, 2)
  h.messages.length = 0
  h.adapter.handleMotionSnapshot(h.snapshot('round-1', [true, true]))
  assert.equal(h.of('band_pose').some((d) => d.pose === 'up'), false)
  h.adapter.handleMotionSnapshot(h.snapshot('round-2', [false, false]))
  h.adapter.handleMotionSnapshot(h.snapshot('round-2', [true, false]))
  h.adapter.handleMotionSnapshot(h.snapshot('round-2', [true, true]))
  assert.equal(h.of('band_tap').length, 0, 'do not synthesize the simultaneous-tap fallback')
  assert.deepEqual(h.of('band_pose').slice(-2).map((d) => [d.band, d.pose]), [['A', 'up'], ['B', 'up']])
})

test('completed stages keep this rounds fresh latch visible until reset without accepting again', async () => {
  const h = harness()
  await h.adapter.handleServerState('matched')
  h.adapter.handleMotionSnapshot(h.snapshot('round-1', [true, true]))
  await h.adapter.handleServerState('mutual')
  const acceptances = h.of('band_tap')
  for (const stage of ['meeting_confirmed', 'whisper', 'stay_in_touch']) {
    h.advance(900)
    h.adapter.handleMotionSnapshot(h.snapshot('round-1', [true, true]))
    h.messages.length = 0
    await h.adapter.handleServerState(stage)
    assert.equal(h.of('band_pose').some((d) => d.pose === 'unknown'), false)
    h.advance(900)
    h.adapter.handleMotionSnapshot(h.snapshot('round-1', [true, true]))
    assert.deepEqual(h.of('band_pose').slice(-2).map((d) => d.pose), ['up', 'up'])
    h.adapter.handleMotionSnapshot(h.snapshot('round-1', [false, true]))
    assert.deepEqual(h.of('band_pose').at(-1), {
      band: 'A', pose: 'down', source: 'quick_motion', motion_mode: 'accel-latch',
    })
    const stale = h.snapshot('round-1', [true, true])
    stale.bands[1].updated_at -= 3
    h.adapter.handleMotionSnapshot(stale)
    assert.deepEqual(h.of('band_pose').slice(-2).map((d) => d.pose), ['unknown', 'unknown'])
    h.adapter.handleMotionSnapshot(h.snapshot('round-1', [true, true]))
    assert.deepEqual(h.of('band_pose').slice(-2).map((d) => d.pose), ['up', 'up'])
    assert.deepEqual(h.of('band_tap'), [])
    assert.equal(h.stops.length, 0)
  }
  assert.equal(acceptances.length, 2)
  assert.equal(h.starts.length, 1)
  await h.adapter.handleServerState('idle')
  assert.deepEqual(h.of('band_pose').slice(-2).map((d) => d.pose), ['unknown', 'unknown'])
  assert.equal(h.stops.length, 1)
})

test('missing, stale, future, unready, unknown or wrong-generation device clears both poses', async (t) => {
  const mutations = {
    missing: (s) => { s.bands.pop() },
    duplicate: (s) => { s.bands.push({ ...s.bands[0] }) },
    stale: (s) => { s.bands[1].updated_at -= 2.01 },
    future: (s) => { s.bands[1].updated_at += 1.01 },
    cachedResponse: (s) => { s.server_time -= 3 },
    disconnected: (s) => { s.bands[1].connected = false },
    unready: (s) => { s.bands[1].ready = false },
    unknown: (s) => { s.bands[1].status = 'unknown' },
    poseMode: (s) => { s.bands[1].mode = 'pose' },
    oldGeneration: (s) => { s.bands[1].reset_generation = 'old' },
    unknownReset: (s) => { s.reset_generation = 'unavailable' },
  }
  for (const [name, mutate] of Object.entries(mutations)) await t.test(name, async () => {
    const h = harness()
    await h.adapter.handleServerState('mutual')
    h.adapter.handleMotionSnapshot(h.snapshot('round-1', [true, true]))
    const invalid = h.snapshot('round-1', [true, true])
    mutate(invalid)
    h.messages.length = 0
    h.adapter.handleMotionSnapshot(invalid)
    assert.deepEqual(h.of('band_pose').map((d) => [d.band, d.pose]), [['A', 'unknown'], ['B', 'unknown']])
    assert.deepEqual(h.of('band_tap'), [])
  })
})

test('HTTP failure clears a previous live pose and never replays an acceptance', async () => {
  const h = harness()
  await h.adapter.handleServerState('mutual')
  h.adapter.handleMotionSnapshot(h.snapshot('round-1', [true, true]))
  h.messages.length = 0
  h.adapter.invalidateMotion()
  assert.deepEqual(h.of('band_pose').map((d) => d.pose), ['unknown', 'unknown'])
  h.adapter.handleMotionSnapshot(h.snapshot('round-1', [true, true]))
  assert.deepEqual(h.of('band_tap'), [])
})

test('a reset response from an old stage cannot arm the new stage', async () => {
  const pending = []
  const h = harness({ beginRound: (args) => new Promise((resolve) => pending.push({ args, resolve })) })
  const oldRound = h.adapter.handleServerState('matched')
  await new Promise(setImmediate)
  await h.adapter.handleServerState('expired')
  const newRound = h.adapter.handleServerState('matched')
  await new Promise(setImmediate)
  assert.equal(pending[0].args.signal.aborted, true)
  pending[1].resolve({ generation: 'new' })
  await newRound
  pending[0].resolve({ generation: 'old' })
  await oldRound
  h.adapter.handleMotionSnapshot(h.snapshot('old', [true, true]))
  assert.deepEqual(h.of('band_tap'), [])
  h.adapter.handleMotionSnapshot(h.snapshot('new', [true, true]))
  assert.deepEqual(h.of('band_tap').map((d) => d.band), ['A', 'B'])
})

test('failed reset cannot accept motion or leak up from the previous round', async () => {
  const h = harness({ beginRound: async () => { throw new Error('HTTP failure') } })
  await h.adapter.handleServerState('matched')
  h.adapter.handleMotionSnapshot(h.snapshot('round-1', [true, true]))
  assert.deepEqual(h.of('band_tap'), [])
  assert.equal(h.of('band_pose').some((d) => d.pose === 'up'), false)
})

test('WebSocket reconnect requires a fresh hardware round even when server remains mutual', async () => {
  const h = harness()
  await h.adapter.handleServerState('mutual')
  h.adapter.handleMotionSnapshot(h.snapshot('round-1', [true, true]))
  await h.adapter.disconnect()
  h.adapter.connect()
  await h.adapter.handleServerState('mutual')
  h.messages.length = 0
  h.adapter.handleMotionSnapshot(h.snapshot('round-1', [true, true]))
  assert.equal(h.of('band_pose').some((d) => d.pose === 'up'), false)
  h.adapter.handleMotionSnapshot(h.snapshot('round-2', [true, true]))
  assert.deepEqual(h.of('band_pose').slice(-2).map((d) => d.pose), ['up', 'up'])
  assert.equal(h.starts.length, 2)
})

test('stale cached latch cannot confirm mutual before a fresh HTTP snapshot', async () => {
  const h = harness()
  await h.adapter.handleServerState('matched')
  h.adapter.handleMotionSnapshot(h.snapshot('round-1', [true, true]))
  h.advance(2100)
  await h.adapter.handleServerState('mutual')
  assert.equal(h.of('band_pose').some((d) => d.pose === 'up'), false)
  h.adapter.handleMotionSnapshot(h.snapshot('round-1', [true, true]))
  assert.deepEqual(h.of('band_pose').slice(-2).map((d) => d.pose), ['up', 'up'])
})

test('completed reconnect restores same-epoch display only, with no acceptance or haptic restart', async () => {
  const h = harness()
  await h.adapter.handleServerState('matched', 7)
  h.adapter.handleMotionSnapshot(h.snapshot('round-1', [true, true]))
  await h.adapter.handleServerState('mutual', 7)
  await h.adapter.handleServerState('whisper', 7)
  await h.adapter.disconnect()
  assert.equal(h.stops.length, 1)
  h.adapter.connect()
  await h.adapter.handleServerState('whisper', 7)
  h.messages.length = 0
  h.adapter.handleMotionSnapshot(h.snapshot('round-1', [true, true]))
  assert.deepEqual(h.of('band_pose').map((d) => d.pose), ['up', 'up'])
  assert.deepEqual(h.of('band_tap'), [])
  assert.equal(h.starts.length, 1)
  assert.equal(h.stops.length, 1)

  h.adapter.handleMotionSnapshot(h.snapshot('other-round', [true, true]))
  assert.deepEqual(h.of('band_pose').slice(-2).map((d) => d.pose), ['unknown', 'unknown'])
  h.adapter.handleMotionSnapshot(h.snapshot('round-1', [true, true]))
  assert.deepEqual(h.of('band_pose').slice(-2).map((d) => d.pose), ['up', 'up'])
  h.advance(2100)
  await h.adapter.handleServerState('stay_in_touch', 7)
  assert.deepEqual(h.of('band_pose').slice(-2).map((d) => d.pose), ['unknown', 'unknown'])
  await h.adapter.handleServerState('idle', 8)
  assert.equal(h.adapter.completedIdentity, null)
  assert.equal(h.stops.length, 1, 'restored display is not an owned haptic round')
})

test('a changed/missing epoch or ended session cannot restore a completed latch', async (t) => {
  for (const [stage, epoch] of [['whisper', 8], ['whisper', undefined], ['idle', 7], ['expired', 7]]) {
    await t.test(`${stage}/${epoch}`, async () => {
      const h = harness()
      await h.adapter.handleServerState('matched', 7)
      h.adapter.handleMotionSnapshot(h.snapshot('round-1', [true, true]))
      await h.adapter.handleServerState('mutual', 7)
      await h.adapter.handleServerState('meeting_confirmed', 7)
      await h.adapter.disconnect()
      h.adapter.connect()
      await h.adapter.handleServerState(stage, epoch)
      h.messages.length = 0
      h.adapter.handleMotionSnapshot(h.snapshot('round-1', [true, true]))
      assert.equal(h.of('band_pose').some((d) => d.pose === 'up'), false)
      assert.deepEqual(h.of('band_tap'), [])
      assert.equal(h.starts.length, 1)
      assert.equal(h.stops.length, 1)
    })
  }
})

test('a reconnect waits for the old owned haptic round to stop before starting another', async () => {
  let finishStop
  const h = harness({ stopRound: () => new Promise((resolve) => { finishStop = resolve }) })
  await h.adapter.handleServerState('matched')
  const stopping = h.adapter.disconnect()
  h.adapter.connect()
  const restarting = h.adapter.handleServerState('matched')
  await new Promise(setImmediate)
  assert.equal(h.starts.length, 1)
  finishStop()
  await stopping
  await restarting
  assert.equal(h.starts.length, 2)
})

test('heart rates retain their owners and clear independently when sources expire', () => {
  const h = harness()
  h.adapter.handleHeartSnapshot({ apple_watch_bpm: 72, bpm: 91 })
  assert.deepEqual(h.of('heart_rate'), [
    { band: 'A', bpm: 72, source: 'Apple Watch' }, { band: 'B', bpm: 91, source: 'WHOOP' },
  ])
  h.messages.length = 0
  h.adapter.handleHeartSnapshot({ apple_watch_bpm: null, bpm: 93 })
  assert.deepEqual(h.of('heart_rate'), [
    { band: 'A', bpm: null, source: 'Apple Watch' }, { band: 'B', bpm: 93, source: 'WHOOP' },
  ])
  h.messages.length = 0
  h.adapter.invalidateHeart()
  assert.deepEqual(h.of('heart_rate'), [{ band: 'B', bpm: null, source: 'WHOOP' }])
  h.messages.length = 0
  h.adapter.handleHeartSnapshot({ apple_watch_bpm: '90', bpm: NaN })
  assert.deepEqual(h.of('heart_rate'), [])
})
