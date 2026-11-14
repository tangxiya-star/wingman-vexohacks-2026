import { useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ConversationProvider, useConversation } from '@elevenlabs/react'
import { Mark } from './Plate'
import { FluidBlob, PALETTES, type BlobMood, type BlobPalette } from './FluidBlob'
import { devMode, httpBase } from '../ws'
import type { VoiceTurn } from '../types'

const SAMPLE: VoiceTurn[] = [
  { role: 'agent', text: "Hey, I'm Wingman. What are you hoping for tonight?" },
  { role: 'user', text: "Honestly something real. I'm tired of chats that go nowhere." },
  { role: 'agent', text: 'Fair. Tell me about a time you really clicked with someone.' },
  { role: 'user', text: 'We talked for four hours about a movie neither of us liked. Same sense of humor, very dry.' },
  { role: 'agent', text: 'Love that. What puts you off instantly?' },
  { role: 'user', text: "People who are performing. And I like someone a bit spontaneous — I'm the one who plans everything." },
]

type Props = { onDone: (v: { conversation_id?: string; transcript: VoiceTurn[] }) => void; onClose: () => void }

/** "Talk to Wingman": a ~2 minute ElevenLabs voice chat about who you click with. */
export function VoiceChat(props: Props) {
  return createPortal(
    <ConversationProvider>
      <VoiceChatInner {...props} />
    </ConversationProvider>,
    document.body,
  )
}

const palette: BlobPalette = new URLSearchParams(location.search).get('blob') === 'lagoon' ? 'lagoon' : 'bloom'

function VoiceChatInner({ onDone, onClose }: Props) {
  const [turns, setTurns] = useState<VoiceTurn[]>([])
  const [error, setError] = useState('')
  const [ended, setEnded] = useState(false)
  const convId = useRef<string | undefined>(undefined)
  const turnsRef = useRef<VoiceTurn[]>([])

  const lastResponse = useRef<string | undefined>(undefined)
  const conversation = useConversation({
    onMessage: (m) => {
      const text = m.message
      if (!text) return
      const role: VoiceTurn['role'] = m.role === 'user' || m.source === 'user' ? 'user' : 'agent'
      const prev = turnsRef.current
      // streamed agent parts share a response_id — replace instead of appending
      if (role === 'agent' && m.response_id && m.response_id === lastResponse.current && prev[prev.length - 1]?.role === 'agent') {
        turnsRef.current = [...prev.slice(0, -1), { role, text }]
      } else {
        turnsRef.current = [...prev, { role, text }]
      }
      lastResponse.current = role === 'agent' ? m.response_id : undefined
      setTurns(turnsRef.current)
    },
    onConnect: () => {
      try {
        convId.current = conversation.getId()
      } catch {}
    },
    onError: (e: unknown) => setError(typeof e === 'string' ? e : ((e as Error)?.message ?? 'Voice chat error')),
    onDisconnect: () => setEnded(true),
  })

  const live = conversation.status === 'connected'
  const connecting = conversation.status === 'connecting'

  const start = async () => {
    setError('')
    setEnded(false)
    try {
      await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch {
      return setError('Wingman needs your microphone for the chat.')
    }
    try {
      const res = await fetch(`${httpBase()}/voice/session`)
      const s = await res.json()
      if (!res.ok) throw new Error(s.error || 'Voice chat unavailable')
      turnsRef.current = []
      setTurns([])
      conversation.startSession(s.signed_url ? { signedUrl: s.signed_url } : { agentId: s.agent_id })
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const finish = async () => {
    if (!convId.current) {
      try {
        convId.current = conversation.getId() || undefined
      } catch {}
    }
    if (live) conversation.endSession()
    onDone({ conversation_id: convId.current, transcript: turnsRef.current })
  }

  const recent = turns.slice(-3)
  const userSpoke = turns.some((t) => t.role === 'user')

  // Shader follows the audio: agent output while it speaks, your mic while it listens.
  const getLevel = () => {
    const fake = devMode ? (window as unknown as { __voiceLevel?: number }).__voiceLevel : undefined
    if (fake != null) return fake // dev: simulate speech without a mic
    if (!live) return 0
    return conversation.isSpeaking ? conversation.getOutputVolume() : conversation.getInputVolume()
  }

  const mood: BlobMood = !live ? (ended || userSpoke ? 'rest' : 'idle') : conversation.isSpeaking ? 'speaking' : 'listening'
  const status = connecting ? 'Connecting…' : live ? (conversation.isSpeaking ? 'Wingman is talking' : 'Listening…') : ended ? 'Chat ended' : 'Talk to Wingman'

  return (
    <div className="agent" role="dialog" aria-label="Talk to Wingman" style={{ ['--agent-bg' as string]: PALETTES[palette].bg }}>
      <div className="agent__top">
        <button className="agent__close" onClick={() => (live && conversation.endSession(), onClose())}>
          Close
        </button>
      </div>

      <div className={`fluid fluid--${mood}`}>
        <FluidBlob getLevel={getLevel} mood={mood} palette={palette} />
      </div>
      <div className="fluid__status">
        <Mark size={14} />
        <p>{status}</p>
        <p className="fluid__sub">{live ? 'one question at a time' : 'about two minutes'}</p>
      </div>

      <div className="agent__card">
        {recent.length > 0 ? (
          <ul className="agent__lines">
            {recent.map((t, i) => (
              <li key={turns.length - recent.length + i} className={t.role === 'user' ? 'is-user' : ''}>
                <span>{t.role === 'user' ? 'You' : 'Wingman'}</span>
                {t.text}
              </li>
            ))}
          </ul>
        ) : (
          <div className="agent__intro">
            <p className="agent__heading">Who do you click with?</p>
            <p className="agent__hint">What you're hoping for, people you've clicked with, what puts you off. Looks are fine to mention.</p>
          </div>
        )}

        {error && <p className="agent__error">{error}</p>}

        <div className="agent__actions">
          {live ? (
            <button className="pill pill--solid" onClick={finish}>
              I'm done
            </button>
          ) : userSpoke ? (
            <>
              <button className="pill pill--solid" onClick={finish}>
                Use this chat
              </button>
              <button className="pill" onClick={start}>
                Start over
              </button>
            </>
          ) : (
            <button className="pill pill--solid" onClick={start} disabled={connecting}>
              {connecting ? 'Connecting…' : 'Start talking'}
            </button>
          )}
          {devMode && !live && (
            <button className="agent__link" onClick={() => onDone({ transcript: SAMPLE })}>
              Use a sample chat (dev)
            </button>
          )}
        </div>
      </div>

      <p className="agent__fine">Only used to understand your type for tonight. Your match never hears or reads it.</p>
    </div>
  )
}
