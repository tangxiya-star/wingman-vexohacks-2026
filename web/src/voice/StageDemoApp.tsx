import { useEffect, useRef, useState } from 'react'
import { ConversationProvider, useConversation } from '@elevenlabs/react'
import { FluidBlob } from '../components/FluidBlob'
import { Mark } from '../components/Plate'
import { SparkBurst } from '../components/SparkBurst'
import { appendHeart, freshHeart, STAGE_MATCH_INSTRUCTION, STAGE_MATCH_TITLE, type HeartSample } from '../hardware'
import type { HeartRate, SessionState } from '../types'
import { bandParam, httpBase, useSocket } from '../ws'
import { HeartCard } from './LiveCards'

type StageState = {
  state: SessionState
  epoch: number
  stage_demo?: boolean
  stage_profile?: { name: string; traits: string[] }
}

const deferredTool = () => 'The demo uses a prepared profile. Keep chatting naturally and let Holly end the conversation on screen. The app handles the next steps.'
const clientTools = {
  set_name: deferredTool,
  add_account: deferredTool,
  ask_to_type: deferredTool,
  ask_for_screenshots: deferredTool,
  finish_onboarding: deferredTool,
  confirm_profile: deferredTool,
  show_card: deferredTool,
  stay_in_touch: deferredTool,
}

export function StageDemoApp() {
  return <ConversationProvider><StageDemo /></ConversationProvider>
}

function StageDemo() {
  const band = bandParam
  const [room, setRoom] = useState<StageState>()
  const [heart, setHeart] = useState<HeartSample[]>([])
  const [starting, setStarting] = useState(false)
  const [finishedEpoch, setFinishedEpoch] = useState<number>()
  const [error, setError] = useState('')
  const [, refreshClock] = useState(0)
  const voiceEpoch = useRef<number>()
  const headline = useRef<HTMLHeadingElement>(null)
  const { connected, send } = useSocket('phone', band, (m) => {
    if (m.type === 'state_changed') setRoom(m.data as StageState)
    if (m.type === 'heart_rate') setHeart((previous) => appendHeart(previous, m.data as HeartRate))
  })
  const conversation = useConversation({
    clientTools,
    onError: (e) => setError(typeof e === 'string' ? e : 'Voice connection failed. Try again.'),
    onDisconnect: ({ reason }) => {
      if (reason === 'agent' && voiceEpoch.current !== undefined) setFinishedEpoch(voiceEpoch.current)
    },
  })
  const live = conversation.status === 'connected'
  const finding = room?.state === 'mutual'
  const matched = room?.state === 'meeting_confirmed'

  useEffect(() => {
    if (connected && room?.stage_demo && room.state === 'idle' && finishedEpoch === room.epoch) {
      send('stage_finish_voice', { epoch: room.epoch })
    }
  }, [connected, finishedEpoch, room, send])

  useEffect(() => {
    if (connected) return
    setHeart([])
  }, [connected])

  useEffect(() => {
    if (!connected) return
    const timer = setInterval(() => refreshClock((n) => n + 1), 1000)
    return () => clearInterval(timer)
  }, [connected])

  async function startVoice() {
    if (!room || starting || live) return
    setStarting(true)
    setError('')
    voiceEpoch.current = room.epoch
    try {
      const response = await fetch(`${httpBase()}/voice/session`, { signal: AbortSignal.timeout(10000) })
      if (!response.ok) throw new Error('Unable to start Wingman voice.')
      const session = await response.json()
      await conversation.startSession({
        ...(session.signed_url ? { signedUrl: session.signed_url } : { agentId: session.agent_id }),
        dynamicVariables: {
          mode: 'chat',
          user_name: 'Holly',
          context: 'This is a live stage demo. Have a short, relaxed chat with Holly about anything she brings up. Let Holly end the conversation from the screen whenever she wants. No usernames, photos, profile questions, health readings or tool calls are needed.',
          first_message: "Hey Holly, I'm Wingman. How's your night going?",
        },
      })
    } catch {
      setError('Could not start voice. Check microphone access and try again.')
    } finally {
      setStarting(false)
    }
  }

  function finishVoice() {
    setError('')
    setFinishedEpoch(voiceEpoch.current)
    conversation.endSession()
  }

  const review = room?.stage_profile
  const latestHeart = heart[heart.length - 1]
  const bpm = connected && freshHeart(latestHeart) ? latestHeart.bpm : null
  const waitingForProfile = finishedEpoch !== undefined && finishedEpoch === room?.epoch
  const title = matched ? "It's a match"
    : finding ? STAGE_MATCH_TITLE
    : review ? 'Your profile'
    : band === 'A' ? 'Looking for someone'
    : 'Talk to Wingman'
  const getLevel = () => live
    ? conversation.isSpeaking ? conversation.getOutputVolume() : conversation.getInputVolume()
    : 0

  return (
    <main className={`voice stage-demo ${matched ? 'stage-demo--matched' : ''}`}>
      <header className="voice__top">
        <span className="brand"><Mark size={20} />Wingman</span>
        <span className="voice__meta">
          {!matched && <span className="voice__hr" aria-label={bpm === null ? 'Heart rate unavailable' : `Heart rate ${bpm} BPM`}>♥ {bpm ?? '—'} BPM</span>}
          <span>Band {band} · {band === 'A' ? '62' : '77'}</span>
        </span>
      </header>
      {!matched && (
        <div className="voice__fluid fluid stage-demo__blob">
          <FluidBlob getLevel={getLevel} mood={live ? (conversation.isSpeaking ? 'speaking' : 'listening') : 'idle'}
            palette={finding ? 'lagoon' : 'bloom'} />
        </div>
      )}
      <section className="stage-demo__content">
        <h1 ref={headline}>{title}</h1>
        {matched ? (
          <div className="stage-demo__vitals">
            <HeartCard samples={heart} />
            <section className="moment live" aria-label="Simulated skin temperature">
              <p className="moment__eyebrow">Skin temperature · simulated</p>
              <p className="live__bpm">{band === 'A' ? '33.4' : '33.1'}<small>°C</small></p>
            </section>
            <SparkBurst originEl={() => headline.current} />
          </div>
        ) : finding ? (
          <p>{STAGE_MATCH_INSTRUCTION}</p>
        ) : room && review ? (
          <section className="moment stage-demo__profile">
            <p className="moment__eyebrow">Prepared demo profile</p>
            <h2>{review.name}</h2>
            <ul>{review.traits.map((trait) => <li key={trait}>{trait}</li>)}</ul>
            <button className="stage-demo__action" disabled={!connected}
              onClick={() => send('stage_confirm_profile', { epoch: room.epoch })}>Confirm profile</button>
          </section>
        ) : band === 'B' && (
          <>
            <button className="stage-demo__action" disabled={starting || waitingForProfile || (!live && (!connected || !room?.stage_demo))}
              onClick={live ? finishVoice : startVoice}>
              {waitingForProfile ? 'Opening profile…' : starting ? 'Connecting voice…' : live ? 'End conversation' : 'Start conversation'}
            </button>
            {live && !waitingForProfile && <p role="status">{conversation.isSpeaking ? 'Wingman is speaking' : 'Wingman is listening'}</p>}
          </>
        )}
        {!connected && <p role="status">Reconnecting to Wingman…</p>}
        {connected && room && !room.stage_demo && <p role="alert">Stage mode is disabled on the server.</p>}
        {error && !review && !matched && !finding && <p role="alert">{error}</p>}
      </section>
    </main>
  )
}
