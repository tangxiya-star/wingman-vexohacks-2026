import { useCallback, useEffect, useRef, useState } from 'react'
import type { Band, Msg, Role } from './types'

const params = new URLSearchParams(location.search)

/** Band this phone belongs to: ?band=A or ?band=B (default A). */
export const bandParam: Band = params.get('band')?.toUpperCase() === 'B' ? 'B' : 'A'
export const devMode = params.has('dev')

/**
 * Backend address. Default: same host as this page, port 8787
 * (so a phone opening http://<laptop-ip>:5173 connects to <laptop-ip>:8787).
 * Override with ?server=192.168.1.20:8787 or ?server=xxx.ngrok.app
 */
export function serverUrl(role: Role, band: Band): string {
  const s = params.get('server') || `${location.hostname}:8787`
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const base = /^wss?:\/\//.test(s) ? s : `${proto}://${s}`
  return `${base.replace(/\/$/, '')}/ws?role=${role}&band=${band}&session=demo`
}

/** HTTP base of the backend (same host/port as the WebSocket). */
export function httpBase(): string {
  return serverUrl('phone', 'A').replace(/^ws/, 'http').replace(/\/ws\?.*$/, '')
}

/** WebSocket with auto-reconnect. Messages follow docs/contract.md: { type, ts, data }. */
export function useSocket(role: Role, band: Band, onMessage: (m: Msg) => void) {
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)
  const handler = useRef(onMessage)
  handler.current = onMessage

  useEffect(() => {
    let stopped = false
    let retry = 0
    let timer: ReturnType<typeof setTimeout> | undefined

    const connect = () => {
      const ws = new WebSocket(serverUrl(role, band))
      wsRef.current = ws
      ws.onopen = () => {
        if (wsRef.current !== ws) return
        retry = 0
        setConnected(true)
      }
      ws.onmessage = (e) => {
        if (wsRef.current !== ws) return
        try {
          handler.current(JSON.parse(e.data))
        } catch {
          /* ignore malformed */
        }
      }
      ws.onclose = () => {
        if (wsRef.current !== ws) return // a stale socket from before a band/role change
        setConnected(false)
        if (!stopped) timer = setTimeout(connect, Math.min(4000, 500 * 2 ** retry++))
      }
      ws.onerror = () => ws.close()
    }

    connect()
    return () => {
      stopped = true
      clearTimeout(timer)
      wsRef.current?.close()
    }
  }, [role, band])

  const send = useCallback((type: string, data: Record<string, unknown> = {}) => {
    const ws = wsRef.current
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type, ts: Date.now(), data }))
      return true
    }
    return false
  }, [])

  return { connected, send }
}
