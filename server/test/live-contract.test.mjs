import test from 'node:test'
import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
import { once } from 'node:events'
import WebSocket from 'ws'
import { VexoBridgeAdapter } from '../scripts/vexo-adapter.mjs'

const wait = async (predicate, message, timeout = 5000) => {
  const end = Date.now() + timeout
  while (Date.now() < end) {
    if (predicate()) return
    await new Promise((resolve) => setTimeout(resolve, 20))
  }
  assert.fail(message)
}

async function withServer(stageDemo, run) {
  // This isolated backend never calls AI providers or a real hardware bridge.
  const child = spawn(process.execPath, ['src/index.mjs'], {
    cwd: new URL('..', import.meta.url),
    env: { ...process.env, PORT: '0', HOST: '127.0.0.1', MOCK_AI: '1', DEMO_MODE: '0',
      STAGE_DEMO: stageDemo ? '1' : '0', HARDWARE_MODE: 'accel-latch',
      GEMINI_API_KEY: '', ELEVENLABS_API_KEY: '', ELEVENLABS_AGENT_ID: '' },
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  const sockets = []
  let output = ''
  let port
  child.stdout.on('data', (chunk) => {
    output += chunk
    port = Number(/Wingman server on :(\d+)/.exec(output)?.[1]) || port
  })
  child.stderr.on('data', () => {})
  try {
    await wait(() => port, 'test server did not start')
    async function connect(role, band = 'A', hardware = false) {
      const ws = new WebSocket(`ws://127.0.0.1:${port}/ws?role=${role}&band=${band}${hardware ? '&hardware=1' : ''}`)
      const messages = []
      ws.on('message', (raw) => messages.push(JSON.parse(raw)))
      sockets.push(ws)
      await once(ws, 'open')
      return { ws, messages, send: (type, data = {}) => ws.send(JSON.stringify({ type, data })),
        last: (type) => messages.filter((m) => m.type === type).at(-1)?.data }
    }
    await run(connect, `http://127.0.0.1:${port}`)
  } finally {
    for (const socket of sockets) socket.terminate()
    const exited = once(child, 'exit')
    child.kill('SIGTERM')
    await exited
  }
}

test('local server: private live vitals, expiry, quick acceptance, spark and disconnect', { timeout: 25000 }, () =>
  withServer(false, async (connect) => {
    const A = await connect('phone', 'A')
    const B = await connect('phone', 'B')
    const room = await connect('room')
    const hardware = await connect('console', 'A', true)
    await wait(() => A.last('state_changed'), 'initial state missing')
    assert.equal(A.last('state_changed').motion_mode, 'accel-latch')
    hardware.send('heart_rate', { band: 'A', bpm: 82, source: 'Apple Watch' })
    hardware.send('heart_rate', { band: 'B', bpm: 94, source: 'WHOOP' })
    await wait(() => A.last('heart_rate')?.bpm === 82 && B.last('heart_rate')?.bpm === 94, 'private vitals missing')
    assert.equal(A.last('heart_rate').source, 'Apple Watch')
    assert.equal(B.last('heart_rate').source, 'WHOOP')
    assert.equal(room.messages.some((m) => m.type === 'heart_rate'), false)
    assert.equal(A.messages.some((m) => m.type === 'heart_rate' && m.data.bpm === 94), false)

    hardware.send('band_pose', { band: 'A', pose: 'up' })
    await wait(() => A.last('band_pose')?.you === 'up', 'live motion missing')
    await wait(() => A.last('band_pose')?.you === 'unknown', 'motion did not expire', 4000)

    for (const band of ['A', 'B']) hardware.send('band_pose', { band, pose: 'down' })
    for (const [client, name] of [[A, 'Integration A'], [B, 'Integration B']]) {
      client.send('join', { name, consent: true, source_consent: true, looking_for: 'friends', sources: {} })
    }
    await wait(() => A.last('profile_ready') && B.last('profile_ready'), 'mock profiles missing')
    A.send('profile_confirm', { removed: [] })
    B.send('profile_confirm', { removed: [] })
    await wait(() => A.last('state_changed')?.state === 'matched', 'match stage missing')
    hardware.send('band_tap', { band: 'A', count: 1, source: 'quick_motion' })
    await wait(() => A.last('decision_status')?.you_said_yes === true, 'first acceptance missing')
    assert.equal(A.last('state_changed').state, 'matched')
    hardware.send('band_tap', { band: 'B', count: 1, source: 'quick_motion' })
    await wait(() => A.last('state_changed')?.state === 'mutual', 'mutual stage missing')
    hardware.send('band_pose', { band: 'A', pose: 'up' })
    await wait(() => A.last('band_pose')?.you === 'up', 'first latch missing')
    assert.equal(A.last('state_changed').state, 'mutual')
    hardware.send('band_pose', { band: 'B', pose: 'up' })
    await wait(() => A.messages.some((m) => m.type === 'state_changed' && m.data.state === 'meeting_confirmed'), 'two latches did not spark')
    assert.equal(room.messages.some((m) => m.type === 'room_update' && 'vitals' in m.data), false)

    hardware.send('heart_rate', { band: 'A', bpm: null, source: 'Apple Watch' })
    await wait(() => A.last('heart_rate')?.bpm === null, 'explicit missing heart rate was not cleared')
    assert.equal(B.last('heart_rate').bpm, 94)
    hardware.ws.close()
    await wait(() => A.last('band_pose')?.you === 'unknown' && B.last('heart_rate')?.bpm === null, 'bridge close retained live data')
  }))

test('stage demo: fixed profile, shared Finder and two fresh latches before private vitals', { timeout: 15000 }, () =>
  withServer(true, async (connect, baseUrl) => {
    const A = await connect('phone', 'A')
    const B = await connect('phone', 'B')
    const room = await connect('room')
    const hardware = await connect('console', 'A', true)
    const dev = await connect('console')
    let generation = 0
    const adapter = new VexoBridgeAdapter({
      send: hardware.send, beginRound: async () => ({ generation: String(++generation) }),
    })
    adapter.connect()
    hardware.ws.on('message', (raw) => {
      const m = JSON.parse(raw)
      if (m.type === 'state_changed') void adapter.handleServerState(m.data.state, m.data.epoch)
    })
    const stage = (client) => client.last('state_changed')?.state
    const forceMatch = (headers) => fetch(`${baseUrl}/demo/force-match`, { method: 'POST', headers })
    await wait(() => stage(A) === 'idle' && stage(B) === 'idle', 'initial stage missing')
    assert.equal(A.last('state_changed').stage_demo, true)
    assert.equal((await forceMatch()).status, 409)
    A.send('stage_finish_voice', { epoch: 0 })
    B.send('stage_confirm_profile', { epoch: 0 })
    B.send('stage_finish_voice', { epoch: 0, transcript: 'an unrelated conversation' })
    await wait(() => B.last('state_changed')?.stage_profile, 'Holly profile missing')
    const profile = B.last('state_changed').stage_profile
    assert.equal(profile.name, 'Holly')
    assert.equal(A.last('state_changed').stage_profile, undefined)
    assert.equal(generation, 0)

    B.send('stage_confirm_profile', { epoch: 0 })
    await wait(() => stage(A) === 'mutual' && stage(B) === 'mutual' && generation === 1, 'shared Finder did not arm')
    const snapshot = (activeA, activeB, gen = '1') => {
      const now = Date.now() / 1000
      return { mode: 'accel-latch', reset_generation: gen, server_time: now,
        bands: [[62, activeA], [77, activeB]].map(([band_number, active]) => ({
          band_number, active, connected: true, ready: true, raised: false, triggered: active,
          status: active ? 'triggered' : 'waiting_motion', updated_at: now, reset_generation: gen, mode: 'accel-latch',
        })) }
    }
    dev.send('band_pose', { band: 'B', pose: 'up', source: 'quick_motion' })
    adapter.handleMotionSnapshot(snapshot(true, true, 'old'))
    adapter.handleMotionSnapshot(snapshot(true, false))
    await wait(() => A.last('band_pose')?.you === 'up', 'first real bridge latch missing')
    assert.equal(stage(A), 'mutual')
    assert.equal(A.last('band_pose').them, 'down')
    adapter.handleMotionSnapshot(snapshot(true, true))
    await wait(() => stage(A) === 'meeting_confirmed' && stage(B) === 'meeting_confirmed'
      && room.last('room_update')?.state === 'meeting_confirmed', 'match did not appear on all screens')
    adapter.handleHeartSnapshot({ apple_watch_bpm: 82, bpm: 94 })
    await wait(() => A.last('heart_rate')?.bpm === 82 && B.last('heart_rate')?.bpm === 94, 'wrong wearer vitals')
    assert.equal(room.messages.some((m) => m.type === 'heart_rate'), false)

    room.send('reset')
    await wait(() => B.last('state_changed')?.epoch === 1, 'reset did not advance round')
    B.send('stage_finish_voice', { epoch: 0 })
    B.send('stage_finish_voice', { epoch: 1, transcript: 'a completely different chat' })
    await wait(() => B.last('state_changed')?.stage_profile, 'second profile missing')
    assert.deepEqual(B.last('state_changed').stage_profile, profile)
    assert.equal(generation, 1)
    assert.equal(B.messages.some((m) => m.type === 'whisper_ready'), false)

    B.send('stage_confirm_profile', { epoch: 1 })
    await wait(() => stage(A) === 'mutual' && stage(B) === 'mutual' && generation === 2, 'second invitation missing')
    assert.equal((await forceMatch({ Origin: 'https://example.com' })).status, 403)
    assert.equal(await (await forceMatch()).text(), 'ok\n')
    await wait(() => stage(A) === 'meeting_confirmed' && stage(B) === 'meeting_confirmed'
      && room.last('room_update')?.state === 'meeting_confirmed', 'manual match did not appear on all screens')
    assert.deepEqual(room.last('room_update').poses, { A: 'unknown', B: 'unknown' })
    assert.equal(await (await forceMatch()).text(), 'ok\n')
    assert.equal(B.messages.filter((m) => m.type === 'state_changed' && m.data.state === 'meeting_confirmed'
      && m.data.epoch === 1).length, 1)
  }))
