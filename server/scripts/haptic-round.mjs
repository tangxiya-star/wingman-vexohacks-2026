// Local HTTP orchestration only: existing services retain ownership of all BLE links.
// A POST with an uncertain outcome is reconciled, never repeated or followed by a reset.

const ACTIVE = new Set(['preparing', 'inviting', 'awaiting_actions', 'confirming', 'approaching', 'stopping'])
const RUNNING = new Set(['preparing', 'inviting', 'awaiting_actions', 'confirming', 'approaching'])

function localOrigin(value) {
  const url = new URL(value)
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
    || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new TypeError('Hardware service URLs must be local HTTP origins')
  }
  return url.origin
}

function abortError() {
  return new DOMException('Hardware round cancelled', 'AbortError')
}

function checkAbort(signal) {
  if (signal?.aborted) throw abortError()
}

function generationOf(data) {
  const generation = data?.generation ?? data?.reset_generation
  if (typeof generation !== 'string' || !generation || generation.length > 128 || generation === 'unavailable'
    || (data?.generation !== undefined && data?.reset_generation !== undefined
      && data.generation !== data.reset_generation)) return null
  return generation
}

function runningGeneration(data, eventId) {
  // The coordinator keeps IDs/generations after completion and in its dedupe ledger.
  // Those receipts cannot make a new adapter round ready; stopping is terminal for begin.
  return data?.event_id === eventId && RUNNING.has(data?.phase) ? generationOf(data) : null
}

function eventIdFor(roundId) {
  if (typeof roundId !== 'string' || !roundId || roundId.length > 120) {
    throw new TypeError('roundId must contain 1–120 characters')
  }
  return `wingman:${roundId}`
}

export function createHardwareRoundController({
  vexoUrl = 'http://127.0.0.1:8765', hapticUrl = 'http://127.0.0.1:8767',
  enableHaptics = false, fetchImpl = globalThis.fetch, log = () => {},
} = {}) {
  const vexo = localOrigin(vexoUrl)
  const haptics = localOrigin(hapticUrl)
  const rounds = new Map()

  async function request(origin, path, { body, token, signal, timeout = 3000 } = {}) {
    checkAbort(signal)
    const controller = new AbortController()
    const onAbort = () => controller.abort(abortError())
    signal?.addEventListener('abort', onAbort, { once: true })
    const timer = setTimeout(() => controller.abort(new Error('Local hardware request timed out')), timeout)
    let rejectAbort
    const aborted = new Promise((_, reject) => { rejectAbort = reject })
    const abortRequest = () => rejectAbort(controller.signal.reason ?? abortError())
    controller.signal.addEventListener('abort', abortRequest, { once: true })
    const headers = {}
    if (body !== undefined) {
      headers['Content-Type'] = 'application/json'
      if (token) headers['X-Vexo-Token'] = token
      if (origin === vexo) headers.Origin = vexo
    }
    try {
      // The race bounds injected transports too; fetch receives the same cancellation.
      return await Promise.race([aborted, (async () => {
        const response = await fetchImpl(`${origin}${path}`, {
          method: body === undefined ? 'GET' : 'POST', headers,
          body: body === undefined ? undefined : JSON.stringify(body),
          cache: 'no-store', signal: controller.signal,
        })
        if (!response.ok) throw new Error(`Local hardware HTTP ${response.status}`)
        return await response.json()
      })()])
    } finally {
      clearTimeout(timer)
      signal?.removeEventListener('abort', onAbort)
      controller.signal.removeEventListener('abort', abortRequest)
    }
  }

  async function sessionToken(signal) {
    const data = await request(haptics, '/api/session', { signal })
    if (typeof data?.token !== 'string' || !data.token) throw new Error('Haptic session unavailable')
    return data.token // Kept only inside this call chain; never logged or returned.
  }

  async function plainReset(record, signal) {
    checkAbort(signal)
    record.mode = 'plain'
    const data = await request(vexo, '/api/motion/reset', { body: {}, signal, timeout: 5000 })
    const generation = generationOf(data)
    if (!generation) throw new Error('Local motion reset could not be confirmed')
    return Object.freeze({ generation })
  }

  async function begin(record, signal) {
    checkAbort(signal)
    if (!enableHaptics) return plainReset(record, signal)
    let status
    let token
    try {
      status = await request(haptics, '/api/state', { signal })
    } catch {
      checkAbort(signal)
      log('Haptics unavailable before starting; using local motion reset.')
      return plainReset(record, signal)
    }
    if (status?.event_id === record.eventId) {
      record.mode = 'haptic'
      const priorGeneration = runningGeneration(status, record.eventId)
      if (!priorGeneration) throw new Error('Owned hardware round is not active; no reset or arm was sent')
      return Object.freeze({ generation: priorGeneration })
    }
    if (ACTIVE.has(status?.phase)) throw new Error('Another hardware round is active; no reset was sent')
    if (status?.whoop?.ready !== true) {
      log('WHOOP haptics not ready; using local motion reset.')
      return plainReset(record, signal)
    }
    try {
      token = await sessionToken(signal)
    } catch {
      checkAbort(signal)
      log('Haptic session unavailable before starting; using local motion reset.')
      return plainReset(record, signal)
    }
    checkAbort(signal)
    record.mode = 'haptic'
    record.armAttempted = true
    try {
      const result = await request(haptics, '/api/arm', {
        body: { event_id: record.eventId }, token, signal, timeout: 12000,
      })
      const generation = runningGeneration(result, record.eventId)
      if (!generation) throw new Error('Haptic arm response did not identify this round')
      checkAbort(signal)
      return Object.freeze({ generation })
    } catch {
      // The POST may have reached the coordinator even if this caller was cancelled.
      // Reconciliation is read-only and independently bounded; never fall back here.
      let reconciled
      try { reconciled = await request(haptics, '/api/state') } catch { /* unresolved */ }
      const generation = runningGeneration(reconciled, record.eventId)
      checkAbort(signal)
      if (generation) {
        log('Haptic round confirmed from coordinator state; no command was repeated.')
        return Object.freeze({ generation })
      }
      throw new Error('Haptic round outcome unavailable; no retry or fallback reset was sent')
    }
  }

  function beginRound({ roundId, stage, signal } = {}) {
    const eventId = eventIdFor(roundId)
    checkAbort(signal)
    const existing = rounds.get(roundId)
    if (existing) {
      checkAbort(existing.signal)
      const joined = signal ? AbortSignal.any([signal, existing.signal]) : existing.signal
      return existing.promise.then(async (result) => {
        checkAbort(joined)
        if (existing.mode === 'haptic') {
          // Dedupe commands, not readiness: a successful round may have ended since
          // the first begin call. Only read its current state; never reset/re-arm it.
          const current = await request(haptics, '/api/state', { signal: joined })
          if (runningGeneration(current, eventId) !== result.generation) {
            throw new Error('Owned hardware round is not active; no reset or arm was sent')
          }
        }
        return result
      })
    }
    const cancellation = new AbortController()
    const joined = signal ? AbortSignal.any([signal, cancellation.signal]) : cancellation.signal
    const record = { eventId, stage, cancellation, signal: joined, mode: null, armAttempted: false, stopPromise: null }
    rounds.set(roundId, record)
    // Cache successes and failures alike: repeated begin calls never create a second reset/arm.
    record.promise = begin(record, joined)
    return record.promise
  }

  function stopRound({ roundId, reason } = {}) {
    const eventId = eventIdFor(roundId)
    const record = rounds.get(roundId)
    if (record?.stopPromise) return record.stopPromise
    record?.cancellation.abort()
    const stop = async () => {
      // Resolve cancellation/reconciliation before checking ownership, so a late arm
      // cannot slip past an earlier stop request. The bridge calls this on end/reset/
      // disconnect, but deliberately not on mutual → spark (approach continues).
      if (record?.promise) await record.promise.catch(() => {})
      if (!enableHaptics || record?.mode === 'plain') return { stopped: false }
      const token = await sessionToken()
      const current = await request(haptics, '/api/state')
      if (current?.event_id !== eventId) return { stopped: false }
      if (!ACTIVE.has(current.phase)) return { stopped: false }
      await request(haptics, '/api/stop', { body: {}, token, timeout: 25000 })
      log('Stopped the owned hardware round.')
      return { stopped: true }
    }
    const promise = stop()
    if (record) record.stopPromise = promise
    return promise
  }

  return { beginRound, stopRound }
}
