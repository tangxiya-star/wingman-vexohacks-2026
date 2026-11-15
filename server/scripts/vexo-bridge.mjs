// Local HTTP -> Wingman WebSocket protocol. No BLE connection is made.
// npm run bridge:vexo. Importing this module starts nothing.
import { resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import WebSocket from 'ws'
import { VexoBridgeAdapter } from './vexo-adapter.mjs'
import { createHardwareRoundController } from './haptic-round.mjs'

export function createVexoBridge({ env = process.env, fetchImpl = fetch, WebSocketImpl = WebSocket,
  roundController, log = console.log, now = Date.now } = {}) {
  const vexoUrl = (env.VEXO_URL || 'http://127.0.0.1:8765').replace(/\/$/, '')
  const hapticUrl = (env.HAPTIC_URL || 'http://127.0.0.1:8767').replace(/\/$/, '')
  const heartUrl = (env.HEART_URL || hapticUrl).replace(/\/$/, '')
  const wingman = new URL(env.WINGMAN_URL || 'ws://127.0.0.1:8787')
  if (wingman.protocol === 'http:') wingman.protocol = 'ws:'
  if (wingman.protocol === 'https:') wingman.protocol = 'wss:'
  if (!['ws:', 'wss:'].includes(wingman.protocol)) throw new Error('WINGMAN_URL must use ws/wss/http/https')
  if (!wingman.pathname.replace(/\/$/, '').endsWith('/ws')) wingman.pathname = wingman.pathname.replace(/\/$/, '') + '/ws'
  for (const [key, value] of Object.entries({ role: 'console', band: 'A', session: 'demo', hardware: '1' })) wingman.searchParams.set(key, value)
  const hardware = roundController || createHardwareRoundController({
    vexoUrl, hapticUrl, enableHaptics: (env.WINGMAN_HAPTICS || env.VEXO_HAPTICS) === '1', fetchImpl, log,
  })
  let ws = null
  let running = false
  let connection = 0
  const timers = new Set()
  const later = (fn, ms) => {
    if (!running) return
    const timer = setTimeout(() => { timers.delete(timer); fn() }, ms)
    timers.add(timer)
  }
  const send = (type, data) => {
    if (ws?.readyState === 1) ws.send(JSON.stringify({ type, ts: now(), data }))
  }
  const adapter = new VexoBridgeAdapter({ send, beginRound: hardware.beginRound,
    stopRound: hardware.stopRound, now, log })
  async function poll(path, base, receive, invalidate, interval) {
    const revision = connection
    if (adapter.online) {
      try {
        const response = await fetchImpl(base + path, { cache: 'no-store', signal: AbortSignal.timeout(1500) })
        if (!response.ok) throw new Error('Local HTTP unavailable')
        const body = await response.json()
        if (running && connection === revision && adapter.online) receive(body)
      } catch {
        if (running && connection === revision && adapter.online) invalidate()
      }
    }
    later(() => poll(path, base, receive, invalidate, interval), interval)
  }
  function connect() {
    if (!running) return
    const socket = new WebSocketImpl(wingman)
    ws = socket
    socket.on('open', () => {
      if (socket !== ws || !running) return
      connection++
      adapter.connect()
      log('Wingman connected: 62 → A / Apple Watch; 77 → B / WHOOP.')
    })
    socket.on('message', (raw) => {
      if (socket !== ws || !running) return
      try {
        const message = JSON.parse(raw)
        if (message?.type === 'state_changed') void adapter.handleServerState(message.data?.state)
      } catch { /* Invalid server messages never become hardware actions. */ }
    })
    socket.on('close', () => {
      if (socket !== ws) return
      connection++
      void adapter.disconnect()
      if (running) log('Wingman disconnected; current hardware round closed.')
      later(connect, 1500)
    })
    socket.on('error', () => {})
  }
  return {
    adapter,
    start() {
      if (running) return
      running = true
      connect()
      void poll('/api/motion', vexoUrl, (s) => adapter.handleMotionSnapshot(s), () => adapter.invalidateMotion(), 300)
      void poll('/api/heart-rate', heartUrl, (s) => adapter.handleHeartSnapshot(s), () => adapter.invalidateHeart(), 1000)
    },
    async stop() {
      running = false
      connection++
      for (const timer of timers) clearTimeout(timer)
      timers.clear()
      adapter.invalidateMotion()
      adapter.invalidateHeart()
      await adapter.disconnect()
      ws?.close()
    },
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const bridge = createVexoBridge()
  bridge.start()
  for (const signal of ['SIGINT', 'SIGTERM']) process.once(signal, () => { void bridge.stop() })
}
