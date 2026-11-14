import { useState } from 'react'
import { bandParam, useSocket } from './ws'
import type {
  ContactExchanged,
  MatchFound,
  Msg,
  ProfileReady,
  SessionState,
  SourceId,
  StateChanged,
  WhisperReady,
} from './types'
import { Join } from './screens/Join'
import { ProfileReview } from './screens/ProfileReview'
import { BandsOffline, Find, Glow, Hidden, NoMatch, Spark, StayInTouch, Waiting } from './screens/Screens'

const AFTER_SPARK: SessionState[] = ['meeting_confirmed', 'whisper', 'stay_in_touch']

export function PhoneApp() {
  const band = bandParam
  const [state, setState] = useState<SessionState>('idle')
  const [joined, setJoined] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [profile, setProfile] = useState<ProfileReady | null>(null)
  const [connectedSources, setConnectedSources] = useState<SourceId[]>([])
  const [theirName, setTheirName] = useState<string>()
  const [match, setMatch] = useState<MatchFound | null>(null)
  const [saidYes, setSaidYes] = useState(false)
  const [whisper, setWhisper] = useState<WhisperReady | null>(null)
  const [contact, setContact] = useState<ContactExchanged | null>(null)
  const [stayStep, setStayStep] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const resetLocal = () => {
    setMatch(null)
    setSaidYes(false)
    setWhisper(null)
    setContact(null)
    setStayStep(false)
    setTheirName(undefined)
  }

  const { connected, send } = useSocket('phone', band, (m: Msg) => {
    switch (m.type) {
      case 'state_changed': {
        const d = m.data as StateChanged
        if (d.state === 'idle') resetLocal()
        if (typeof d.you_joined === 'boolean') setJoined(d.you_joined)
        if (typeof d.you_confirmed === 'boolean') setConfirmed(d.you_confirmed)
        if (d.you_joined === false) setProfile(null)
        if (d.their_name) setTheirName(d.their_name)
        setState(d.state)
        break
      }
      case 'profile_ready':
        setProfile(m.data as ProfileReady)
        break
      case 'match_found':
        setMatch(m.data as MatchFound)
        break
      case 'decision_status':
        setSaidYes(!!m.data?.you_said_yes)
        break
      case 'whisper_ready':
        setWhisper(m.data as WhisperReady)
        break
      case 'contact_exchanged':
        setContact(m.data as ContactExchanged)
        break
      case 'error':
        setError(m.data?.message ?? 'Something went wrong')
        setTimeout(() => setError(null), 5000)
        break
    }
  })

  let screen: JSX.Element
  if (state === 'hidden') screen = <Hidden />
  else if (state === 'band_disconnected') screen = <BandsOffline />
  else if (state === 'passed' || state === 'expired' || state === 'no_match') screen = <NoMatch />
  else if (state === 'matched') screen = <Glow match={match} saidYes={saidYes} />
  else if (state === 'mutual') screen = <Find />
  else if (AFTER_SPARK.includes(state))
    screen = stayStep ? (
      <StayInTouch
        theirName={theirName}
        contact={contact}
        bothAnswered={state === 'stay_in_touch'}
        onAnswer={(yes, c) => send('stay_in_touch', { band, yes, ...(c ? { contact: c } : {}) })}
      />
    ) : (
      <Spark theirName={theirName} whisper={whisper} onContinue={() => setStayStep(true)} />
    )
  else if (joined && !confirmed)
    screen = (
      <ProfileReview
        profile={profile}
        connectedSources={connectedSources}
        onConfirm={(removed) => {
          if (send('profile_confirm', { band, removed })) setConfirmed(true)
        }}
      />
    )
  else if (joined) screen = <Waiting />
  else
    screen = (
      <Join
        band={band}
        onSubmit={(p) => {
          if (send('join', { ...p })) {
            setConnectedSources(Object.keys(p.sources) as SourceId[])
            setProfile(null)
            setJoined(true)
          }
          else setError('Not connected yet — try again in a second.')
        }}
      />
    )

  const canHide = joined && state !== 'hidden'

  return (
    <div className="app">
      <header className="topbar">
        <span className="brand">WINGMAN</span>
        <span className="topbar__right">
          <span className={`dot ${connected ? 'dot--on' : ''}`} title={connected ? 'Connected' : 'Reconnecting'} />
          <span className="band-tag">Band {band}</span>
          {canHide && (
            <button className="link" onClick={() => send('hide', { band })}>
              Hide
            </button>
          )}
        </span>
      </header>
      {!connected && <div className="banner">Reconnecting…</div>}
      {error && <div className="banner banner--error">{error}</div>}
      {screen}
    </div>
  )
}
