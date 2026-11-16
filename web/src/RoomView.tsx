import { useState } from 'react'
import { hardwareMode, useSocket } from './ws'
import { motionLabel, QUICK_RAISE_INSTRUCTION, STAGE_MATCH_INSTRUCTION, STAGE_MATCH_TITLE } from './hardware'
import { Mark, Plate } from './components/Plate'
import { GestureDemo } from './components/GestureDemo'
import type { Msg, RoomUpdate, SessionState } from './types'
import { overlapRows } from './overlaps'

const STAGES: { key: string; label: string; states: SessionState[] }[] = [
  { key: 'join', label: 'The real you', states: ['idle', 'profiling'] },
  { key: 'glow', label: 'The glow', states: ['matched'] },
  { key: 'yes', label: 'Both said yes', states: ['mutual'] },
  { key: 'spark', label: 'The spark', states: ['meeting_confirmed', 'whisper', 'stay_in_touch'] },
]

const HEADLINE: Partial<Record<SessionState, string>> = {
  idle: 'Two strangers. No photos, no bios.',
  profiling: 'Reading their real taste…',
  matched: 'More in common than a film list.',
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
  const { connected, send } = useSocket('room', 'A', (m: Msg) => {
    if (m.type === 'room_update') setRoom({ ...INITIAL, ...(m.data as RoomUpdate) })
  })

  const merged = room.leds.A === 'green' && room.leds.B === 'green'
  const latched = hardwareMode || room.motion_mode === 'accel-latch'
  const awaitingMatch = latched && !['matched', 'mutual', 'meeting_confirmed', 'whisper', 'stay_in_touch'].includes(room.state)
  const poseA = connected ? room.poses?.A ?? 'unknown' : 'unknown'
  const poseB = connected ? room.poses?.B ?? 'unknown' : 'unknown'
  const stageIdx = STAGES.findIndex((s) => s.states.includes(room.state))
  const stageInvitation = room.stage_demo && room.state === 'mutual'
  const stageTitle = room.stage_demo
    ? room.state === 'meeting_confirmed' ? 'MATCH'
      : room.state === 'mutual' ? STAGE_MATCH_TITLE
      : 'Looking for someone'
    : null

  const rows = overlapRows(room, 4)
  const hasOverlap = rows.length > 0

  return (
    <div className="room">
      <header className="room__top">
        <span className="brand">
          <Mark size={20} />
          Wingman
        </span>
        <span className="room__tagline">Taste first. Then you meet.</span>
        {latched && <button className="voice__link" disabled={!connected} onClick={() => send('reset')} title="Clear both profiles and begin a new session">Reset session</button>}
        <span className={`dot ${connected ? 'dot--on' : ''}`} />
      </header>
      {!connected && <div className="room__offline">Reconnecting…</div>}

      {!room.stage_demo && <ol className="room__stages">
        {STAGES.map((s, i) => (
          <li key={s.key} className={i === stageIdx ? 'is-current' : i < stageIdx ? 'is-done' : ''}>
            {latched && s.key === 'glow' ? 'A match' : s.label}
          </li>
        ))}
      </ol>}

      <div className="room__main">
        <div className="room__copy">
          <h1 className={`room__headline${stageInvitation ? ' match-invite' : ''}`}>
            {stageInvitation ? <><span>{STAGE_MATCH_TITLE}</span><span>{STAGE_MATCH_INSTRUCTION}</span></>
              : stageTitle ?? HEADLINE[room.state] ?? ''}
          </h1>
          {latched && room.state === 'matched' && <p className="lede">{QUICK_RAISE_INSTRUCTION}</p>}
          {room.state === 'mutual' ? (
            stageInvitation
              ? null
              : latched ? <p className="lede">Both actions are registered. Waiting for confirmation.</p> : <GestureDemo />
          ) : (
            hasOverlap && (
              <div className="room__overlaps">
                {rows.map((v) => (
                  <p key={v.text}>
                    <span>{v.label}</span>
                    {v.text}
                    {v.from && <small>{v.from}</small>}
                  </p>
                ))}
              </div>
            )
          )}
        </div>

        <div className={`room__pair ${merged ? 'is-merged' : ''}`}>
          <Plate mode={room.leds.A} ratio="3 / 4">
            {room.names?.A ?? 'Band A'}
            {(latched || room.state === 'mutual') && (
              <span className={`room__pose ${poseA === 'up' ? 'is-up' : ''}`}>{awaitingMatch ? 'Awaiting match' : motionLabel(poseA, latched)}</span>
            )}
          </Plate>
          <Plate mode={room.leds.B} ratio="3 / 4">
            {room.names?.B ?? 'Band B'}
            {(latched || room.state === 'mutual') && (
              <span className={`room__pose ${poseB === 'up' ? 'is-up' : ''}`}>{awaitingMatch ? 'Awaiting match' : motionLabel(poseB, latched)}</span>
            )}
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
