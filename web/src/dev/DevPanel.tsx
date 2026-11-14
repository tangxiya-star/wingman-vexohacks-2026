import { useEffect, useRef, useState } from 'react'
import { useSocket } from '../ws'
import gesture from '../config/gesture.json'
import type { Band, LedMode, Msg } from '../types'

/**
 * Dev-only (?dev=1): pretends to be Will's band console.
 * Sends the same events the real console will send (docs/contract.md §3),
 * so the whole flow can be tested without bands.
 */
export function DevPanel() {
  const [open, setOpen] = useState(true)
  const [leds, setLeds] = useState<Record<Band, LedMode>>({ A: 'off', B: 'off' })
  const { connected, send } = useSocket('console', 'A', (m: Msg) => {
    if (m.type === 'set_led') {
      const { band, mode } = m.data as { band: Band | 'both'; mode: LedMode }
      setLeds((l) => (band === 'both' ? { A: mode, B: mode } : { ...l, [band]: mode }))
    }
  })

  const tap = (band: Band, count: 1 | 2) => send('band_tap', { band, count })
  const gest = (band: Band) => send('band_gesture', { band, gesture: gesture.id, confidence: 1 })
  const pose = (band: Band, p: 'up' | 'down') => send('band_pose', { band, pose: p })

  // pretend WHOOP: a heart rate for band A once a second, drifting; "spike" bumps it like a nervous moment
  const [hrOn, setHrOn] = useState(false)
  const bpm = useRef(78)
  const spikeLeft = useRef(0)
  useEffect(() => {
    if (!hrOn) return
    const t = setInterval(() => {
      const target = spikeLeft.current-- > 0 ? 112 : 80
      bpm.current += (target - bpm.current) * 0.25 + (Math.random() - 0.5) * 3
      send('heart_rate', { band: 'A', bpm: Math.round(bpm.current) })
    }, 1000)
    return () => clearInterval(t)
  }, [hrOn, send])

  // joins with test usernames and immediately confirms the profile
  const fillProfile = (band: Band) => {
    send('join', {
      band,
      name: band === 'A' ? 'Holly' : 'Sam',
      looking_for: 'serious',
      dealbreaker: 'Dishonesty',
      consent: true,
      source_consent: true,
      sources: {
        letterboxd: { username: band === 'A' ? 'davidehrlich' : 'karsten' },
        reddit: { username: band === 'A' ? 'holly_climbs' : 'sam_sends' },
      },
    })
    setTimeout(() => send('profile_confirm', { band, removed: [] }), 1600)
  }

  if (!open)
    return (
      <button className="dev dev--closed" onClick={() => setOpen(true)}>
        dev
      </button>
    )

  return (
    <aside className="dev">
      <div className="dev__head">
        <strong>Fake band console</strong>
        <span className={`dot ${connected ? 'dot--on' : ''}`} />
        <button className="link" onClick={() => setOpen(false)}>
          ×
        </button>
      </div>
      <fieldset className="dev__body" disabled={!connected} title={connected ? undefined : 'Not connected to the server'}>
      {(['A', 'B'] as Band[]).map((b) => (
        <div className="dev__row" key={b}>
          <span className={`dev__led dev__led--${leds[b]}`} title={leds[b]} />
          <span>{b}</span>
          <button onClick={() => tap(b, 1)}>tap</button>
          <button onClick={() => tap(b, 2)}>2×tap</button>
          <button onClick={() => gest(b)}>gesture</button>
          <button onClick={() => fillProfile(b)}>fill</button>
          <button onClick={() => pose(b, 'up')}>raise</button>
          <button onClick={() => pose(b, 'down')}>lower</button>
        </div>
      ))}
      <div className="dev__row">
        <button
          onClick={() => {
            gest('A')
            setTimeout(() => gest('B'), 300)
          }}
        >
          both gesture
        </button>
        <button
          onClick={() => {
            tap('A', 1)
            setTimeout(() => tap('B', 1), 200)
          }}
        >
          both tap
        </button>
        <button onClick={() => send('stay_in_touch', { band: 'B', yes: true, contact: '@sam' })}>B stays</button>
        <button onClick={() => send('reset')}>reset</button>
      </div>
      <div className="dev__row">
        <button onClick={() => setHrOn((v) => !v)}>{hrOn ? 'stop' : 'start'} A heart</button>
        <button onClick={() => (spikeLeft.current = 20)} disabled={!hrOn}>
          spike
        </button>
      </div>
      </fieldset>
    </aside>
  )
}
