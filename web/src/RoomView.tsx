import { useState } from 'react'
import { useSocket } from './ws'
import { Mark, Plate } from './components/Plate'
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
  idle: 'Two strangers. No photos, no bios.',
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

  const hasOverlap = (room.core_overlap?.length ?? 0) > 0 || (room.shared_specifics?.length ?? 0) > 0

  return (
    <div className="room">
      <header className="room__top">
        <span className="brand">
          <Mark size={20} />
          Wingman
        </span>
        <span className="room__tagline">Taste first. Then you meet.</span>
        <span className={`dot ${connected ? 'dot--on' : ''}`} />
      </header>

      <ol className="room__stages">
        {STAGES.map((s, i) => (
          <li key={s.key} className={i === stageIdx ? 'is-current' : i < stageIdx ? 'is-done' : ''}>
            {s.label}
          </li>
        ))}
      </ol>

      <div className="room__main">
        <div className="room__copy">
          <h1 className="room__headline">{HEADLINE[room.state] ?? ''}</h1>
          {room.score != null && ['matched', 'mutual', 'meeting_confirmed', 'whisper', 'stay_in_touch'].includes(room.state) && (
            <p className="room__score">{Math.round(room.score)}% match</p>
          )}
          {room.state === 'mutual' ? (
            <GestureDemo />
          ) : (
            hasOverlap && (
              <div className="room__overlaps">
                {(room.core_overlap ?? []).map((v) => (
                  <p key={v}>
                    <span>Core</span>
                    {v}
                  </p>
                ))}
                {room.type_fit && (
                  <p>
                    <span>Type</span>They're each other's type
                  </p>
                )}
                {(room.shared_specifics ?? []).map((v) => (
                  <p key={v.text}>
                    <span>{SOURCE_META[v.source]?.label}</span>
                    {v.text}
                  </p>
                ))}
              </div>
            )
          )}
        </div>

        <div className={`room__pair ${merged ? 'is-merged' : ''}`}>
          <Plate mode={room.leds.A} ratio="3 / 4">
            {room.names?.A ?? 'Band A'}
          </Plate>
          <Plate mode={room.leds.B} ratio="3 / 4">
            {room.names?.B ?? 'Band B'}
          </Plate>
        </div>
      </div>

      <footer className="room__log">
        {room.last_events.slice(0, 4).map((e, i) => (
          <span key={i}>{e}</span>
        ))}
      </footer>
    </div>
  )
}
