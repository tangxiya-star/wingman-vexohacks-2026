import test from 'node:test'
import assert from 'node:assert/strict'
import { createHardwareRoundController } from './haptic-round.mjs'

const TOKEN = 'mock-session-token'
const state = (extra = {}) => ({ phase: 'idle', whoop: { ready: true }, ...extra })
const owned = (extra = {}) => state({ phase: 'awaiting_actions', event_id: 'wingman:r1', generation: 'g1', ...extra })
function harness(handler, options = {}) {
  const calls = [], logs = []
  const controller = createHardwareRoundController({ enableHaptics: true,
    log: (message) => logs.push(message), fetchImpl: async (url, init) => {
      const call = { origin: new URL(url).origin, path: new URL(url).pathname, ...init }
      calls.push(call)
      const body = await handler(call, calls)
      return { ok: true, status: 200, json: async () => body }
    }, ...options })
  return { ...controller, calls, logs }
}
const posts = (h) => h.calls.filter((call) => call.method === 'POST')

test('default plain mode resets once with the required Origin and reuses its generation', async () => {
  const h = harness(() => ({ generation: 'g1', reset_generation: 'g1' }), { enableHaptics: false })
  const [one, two] = await Promise.all([h.beginRound({ roundId: 'r1' }), h.beginRound({ roundId: 'r1' })])
  assert.deepEqual(one, { generation: 'g1' })
  assert.deepEqual(two, one)
  assert.equal(h.calls.length, 1)
  assert.equal(h.calls[0].origin, 'http://127.0.0.1:8765')
  assert.equal(h.calls[0].headers.Origin, 'http://127.0.0.1:8765')
  assert.equal(h.calls[0].body, '{}')
  await h.stopRound({ roundId: 'r1', reason: 'reset' })
  assert.equal(h.calls.length, 1)
})

test('haptic mode arms one stable invitation and keeps the token out of results/logs', async () => {
  let armed = false
  const h = harness((call) => {
    if (call.path === '/api/state') return armed ? owned() : state()
    if (call.path === '/api/session') return { token: TOKEN }
    armed = true
    return owned()
  })
  assert.deepEqual(await h.beginRound({ roundId: 'r1', stage: 'matched' }), { generation: 'g1' })
  await h.beginRound({ roundId: 'r1', stage: 'mutual' })
  assert.equal(posts(h).length, 1)
  assert.equal(posts(h)[0].path, '/api/arm')
  assert.equal(posts(h)[0].headers['X-Vexo-Token'], TOKEN)
  assert.deepEqual(JSON.parse(posts(h)[0].body), { event_id: 'wingman:r1' })
  assert.ok(!JSON.stringify(h.logs).includes(TOKEN))
})

test('unavailable coordinator or WHOOP falls back only before any haptic POST', async () => {
  for (const unavailable of ['offline', 'not-ready', 'session']) {
    const h = harness((call) => {
      if (call.origin.endsWith(':8765')) return { reset_generation: 'plain' }
      if (unavailable === 'offline' || call.path === '/api/session') throw new Error('offline')
      return state({ whoop: { ready: unavailable !== 'not-ready' } })
    })
    assert.deepEqual(await h.beginRound({ roundId: unavailable }), { generation: 'plain' })
    assert.equal(posts(h).length, 1)
    assert.equal(posts(h)[0].path, '/api/motion/reset')
    assert.equal(h.logs.length, 1)
  }
})

test('uncertain arm reconciles by exact event ID without retry or fallback', async () => {
  let stateReads = 0
  const h = harness((call) => {
    if (call.path === '/api/state') return ++stateReads === 1 ? state() : owned()
    if (call.path === '/api/session') return { token: TOKEN }
    throw new Error('connection lost after sending')
  })
  assert.deepEqual(await h.beginRound({ roundId: 'r1' }), { generation: 'g1' })
  await h.beginRound({ roundId: 'r1' })
  assert.deepEqual(posts(h).map((call) => call.path), ['/api/arm'])
})

test('unreconciled arm fails closed and a duplicate begin cannot send again', async () => {
  let stateReads = 0
  const h = harness((call) => {
    if (call.path === '/api/state') return ++stateReads === 1 ? state() : owned({ event_id: 'someone-else' })
    if (call.path === '/api/session') return { token: TOKEN }
    throw new Error('timeout')
  })
  await assert.rejects(h.beginRound({ roundId: 'r1' }), /no retry or fallback/)
  await assert.rejects(h.beginRound({ roundId: 'r1' }), /no retry or fallback/)
  assert.deepEqual(posts(h).map((call) => call.path), ['/api/arm'])
})

test('existing owned round is reused while another active round is not reset', async () => {
  const existing = harness(() => owned({ whoop: { ready: false } }))
  assert.deepEqual(await existing.beginRound({ roundId: 'r1' }), { generation: 'g1' })
  assert.equal(posts(existing).length, 0)
  const other = harness(() => owned({ event_id: 'other' }))
  await assert.rejects(other.beginRound({ roundId: 'r1' }), /Another hardware round/)
  assert.equal(posts(other).length, 0)
})

test('a consumed owned ID in a terminal or stopping phase cannot start or reset a round', async () => {
  for (const phase of ['stopping', 'stopped', 'expired', 'failed', 'idle', undefined]) {
    const h = harness(() => owned({ phase }))
    await assert.rejects(h.beginRound({ roundId: 'r1' }), /not active/)
    await assert.rejects(h.beginRound({ roundId: 'r1' }), /not active/)
    assert.equal(posts(h).length, 0)
  }
})

test('an owned ID with no valid generation fails closed before any POST', async () => {
  const h = harness(() => owned({ generation: null }))
  await assert.rejects(h.beginRound({ roundId: 'r1' }), /not active/)
  assert.equal(posts(h).length, 0)
})

test('arm responses and uncertain outcomes never reconcile to a completed or stopping round', async () => {
  for (const phase of ['stopping', 'stopped', 'expired', 'failed']) {
    for (const uncertain of [false, true]) {
      let reads = 0
      const h = harness((call) => {
        if (call.path === '/api/state') return ++reads === 1 ? state() : owned({ phase })
        if (call.path === '/api/session') return { token: TOKEN }
        if (uncertain) throw new Error('response lost')
        return owned({ phase, duplicate: true, original_event_id: 'wingman:r1' })
      })
      await assert.rejects(h.beginRound({ roundId: 'r1' }), /no retry or fallback/)
      await assert.rejects(h.beginRound({ roundId: 'r1' }), /no retry or fallback/)
      assert.deepEqual(posts(h).map((call) => call.path), ['/api/arm'])
    }
  }
})

test('a live round may advance while its arm response is lost', async () => {
  for (const phase of ['preparing', 'inviting', 'awaiting_actions', 'confirming', 'approaching']) {
    let reads = 0
    const h = harness((call) => {
      if (call.path === '/api/state') return ++reads === 1 ? state() : owned({ phase })
      if (call.path === '/api/session') return { token: TOKEN }
      throw new Error('response lost')
    })
    assert.deepEqual(await h.beginRound({ roundId: 'r1' }), { generation: 'g1' })
    assert.deepEqual(posts(h).map((call) => call.path), ['/api/arm'])
  }
})

test('stopping a successful round invalidates its cached begin result', async () => {
  const h = harness(() => ({ generation: 'g1' }), { enableHaptics: false })
  await h.beginRound({ roundId: 'r1' })
  await h.stopRound({ roundId: 'r1', reason: 'reset' })
  assert.throws(() => h.beginRound({ roundId: 'r1' }), { name: 'AbortError' })
  assert.equal(posts(h).length, 1)
})

test('a cached successful begin rechecks haptic phase and generation without another command', async () => {
  for (const changed of [{ phase: 'expired' }, { generation: 'different' }, { event_id: 'other' }]) {
    let current = owned()
    const h = harness(() => current)
    assert.deepEqual(await h.beginRound({ roundId: 'r1' }), { generation: 'g1' })
    current = owned(changed)
    await assert.rejects(h.beginRound({ roundId: 'r1' }), /not active/)
    assert.equal(posts(h).length, 0)
  }
})

test('stop checks current ownership and never stops another round', async () => {
  for (const eventId of ['wingman:r1', 'someone-else']) {
    const h = harness((call) => call.path === '/api/session' ? { token: TOKEN }
      : call.path === '/api/state' ? owned({ event_id: eventId }) : owned({ phase: 'stopped' }))
    const result = await h.stopRound({ roundId: 'r1', reason: 'disconnect' })
    assert.equal(result.stopped, eventId === 'wingman:r1')
    assert.deepEqual(posts(h).map((call) => call.path), eventId === 'wingman:r1' ? ['/api/stop'] : [])
  }
})

test('cancellation before begin makes no HTTP request', async () => {
  const h = harness(() => { throw new Error('must not fetch') })
  const cancellation = new AbortController()
  cancellation.abort()
  assert.throws(() => h.beginRound({ roundId: 'r1', signal: cancellation.signal }), { name: 'AbortError' })
  assert.equal(h.calls.length, 0)
})

test('stop during uncertain in-flight arm waits for reconciliation then stops only that round', async () => {
  let armStarted
  const started = new Promise((resolve) => { armStarted = resolve })
  let armed = false
  const h = harness(async (call) => {
    if (call.path === '/api/session') return { token: TOKEN }
    if (call.path === '/api/state') return armed ? owned() : state()
    if (call.path === '/api/arm') {
      armed = true
      armStarted()
      return new Promise((_, reject) => call.signal.addEventListener('abort', () => reject(new Error('aborted')), { once: true }))
    }
    if (call.path === '/api/stop') return owned({ phase: 'stopped' })
    throw new Error('unexpected call')
  })
  const beginning = h.beginRound({ roundId: 'r1' })
  const rejection = assert.rejects(beginning, { name: 'AbortError' })
  await started
  assert.deepEqual(await h.stopRound({ roundId: 'r1', reason: 'reset' }), { stopped: true })
  await rejection
  assert.deepEqual(posts(h).map((call) => call.path), ['/api/arm', '/api/stop'])
  await h.stopRound({ roundId: 'r1', reason: 'reset' })
  assert.equal(posts(h).length, 2)
})

test('service addresses cannot route commands or tokens to remote hosts', () => {
  for (const hapticUrl of ['https://example.com', 'http://user:pass@localhost:8767', 'http://localhost:8767/extra']) {
    assert.throws(() => createHardwareRoundController({ hapticUrl }), /local HTTP origins/)
  }
})
