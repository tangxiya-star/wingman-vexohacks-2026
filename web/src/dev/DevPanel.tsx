import { useState } from 'react'
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
        letterboxd: { username: band === 'A' ? 'hollyt' : 'samwatches' },
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
      {(['A', 'B'] as Band[]).map((b) => (
        <div className="dev__row" key={b}>
          <span className={`dev__led dev__led--${leds[b]}`} title={leds[b]} />
          <span>{b}</span>
          <button onClick={() => tap(b, 1)}>tap</button>
          <button onClick={() => tap(b, 2)}>2×tap</button>
          <button onClick={() => gest(b)}>gesture</button>
          <button onClick={() => fillProfile(b)}>fill</button>
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
    </aside>
  )
}
