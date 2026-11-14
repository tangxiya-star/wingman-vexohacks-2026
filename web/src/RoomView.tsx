import { useState } from 'react'
import { useSocket } from './ws'
import { Orb } from './components/Orb'
import { GestureDemo } from './components/GestureDemo'
import type { Msg, RoomUpdate, SessionState } from './types'
import { SOURCE_META } from './sources'

const STAGES: { key: string; label: string; states: SessionState[] }[] = [
  { key: 'join', label: 'The real you', states: ['idle', 'profiling'] },
  { key: 'glow', label: 'The glow', states: ['matched'] },
  { key: 'yes', label: 'Both said yes', states: ['mutual'] },
  { key: 'spark', label: 'The spark', states: ['meeting_confirmed', 'whisper', 'stay_in_touch'] },
]

const HEADLINE: Partial<Record<SessionState, string>> = {
  idle: 'Two strangers. No bios.',
  profiling: 'Reading their real taste…',
  matched: 'Their taste matches.',
  mutual: 'They both said yes. Now find each other.',
  meeting_confirmed: 'They found each other.',
  whisper: 'They found each other.',
  stay_in_touch: 'They found each other.',
  passed: 'No match this time.',
  expired: 'No match this time.',
  no_match: 'No match this time.',
  hidden: 'Paused.',
  band_disconnected: 'Reconnecting bands…',
}

const INITIAL: RoomUpdate = { state: 'idle', leds: { A: 'off', B: 'off' }, last_events: [] }

export function RoomView() {
  const [room, setRoom] = useState<RoomUpdate>(INITIAL)
  const { connected } = useSocket('room', 'A', (m: Msg) => {
    if (m.type === 'room_update') setRoom({ ...INITIAL, ...(m.data as RoomUpdate) })
  })

  const merged = room.leds.A === 'green' && room.leds.B === 'green'
  const stageIdx = STAGES.findIndex((s) => s.states.includes(room.state))

  return (
    <div className="room">
      <header className="room__top">
        <span className="brand">WINGMAN</span>
        <span className="room__tagline">Values first. Then you meet.</span>
        <span className={`dot ${connected ? 'dot--on' : ''}`} />
      </header>

      <ol className="room__stages">
        {STAGES.map((s, i) => (
          <li key={s.key} className={i === stageIdx ? 'is-current' : i < stageIdx ? 'is-done' : ''}>
            {s.label}
          </li>
        ))}
      </ol>

      <h1 className="room__headline">{HEADLINE[room.state] ?? ''}</h1>

      <div className={`room__orbs ${merged ? 'is-merged' : ''}`}>
        <figure className="room__person room__person--a">
          <Orb mode={room.leds.A} size={220} />
          <figcaption>{room.names?.A ?? 'Band A'}</figcaption>
        </figure>

        <div className="room__middle">
          {room.state === 'mutual' && <GestureDemo compact />}
          {room.state !== 'mutual' && room.shared_specifics && room.shared_specifics.length > 0 && (
            <ul className="specifics specifics--room">
              {room.shared_specifics.map((v) => (
                <li key={v.text}>
                  <span className="specifics__icon">{SOURCE_META[v.source]?.icon ?? '✦'}</span>
                  <span>{v.text}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <figure className="room__person room__person--b">
          <Orb mode={room.leds.B} size={220} />
          <figcaption>{room.names?.B ?? 'Band B'}</figcaption>
        </figure>
      </div>

      <footer className="room__log">
        {room.last_events.slice(0, 4).map((e, i) => (
          <span key={i}>{e}</span>
        ))}
      </footer>
    </div>
  )
}
