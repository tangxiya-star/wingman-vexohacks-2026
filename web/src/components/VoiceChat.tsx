import { useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ConversationProvider, useConversation } from '@elevenlabs/react'
import { Plate } from './Plate'
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

  return (
    <div className="sheet" role="dialog" aria-label="Talk to Wingman">
      <div className="sheet__top">
        <span className="eyebrow">Talk to Wingman</span>
        <button className="link" onClick={() => (live && conversation.endSession(), onClose())}>
          Close
        </button>
      </div>

      <Plate mode={live ? (conversation.isSpeaking ? 'purple_slow' : 'white') : 'off'} ratio="1 / 1">
        <p className="eyebrow">{connecting ? 'Connecting…' : live ? (conversation.isSpeaking ? 'Wingman is talking' : 'Listening…') : ended ? 'Chat ended' : 'About two minutes'}</p>
      </Plate>

      <h2 className="title">{live || userSpoke ? 'Tell me who you click with.' : 'Who do you click with?'}</h2>

      {recent.length > 0 ? (
        <ul className="voice-lines">
          {recent.map((t, i) => (
            <li key={turns.length - recent.length + i} className={t.role === 'user' ? 'is-user' : ''}>
              <span>{t.role === 'user' ? 'You' : 'Wingman'}</span>
              {t.text}
            </li>
          ))}
        </ul>
      ) : (
        <p className="lede">A short voice chat about what you're looking for, people you've clicked with, and what puts you off. Looks are fine to mention too.</p>
      )}

      {error && <p className="fineprint voice-error">{error}</p>}

      {live ? (
        <button className="btn btn--primary" onClick={finish}>
          I'm done
        </button>
      ) : userSpoke ? (
        <div className="row">
          <button className="btn btn--primary" onClick={finish}>
            Use this chat
          </button>
          <button className="btn btn--ghost" onClick={start}>
            Start over
          </button>
        </div>
      ) : (
        <button className="btn btn--primary" onClick={start} disabled={connecting}>
          {connecting ? 'Connecting…' : 'Start talking'}
        </button>
      )}

      {devMode && !live && (
        <button className="link" onClick={() => onDone({ transcript: SAMPLE })}>
          Use a sample chat (dev)
        </button>
      )}
      <p className="fineprint">Only used to understand your type for tonight. Your match never hears or reads it.</p>
    </div>
  )
}
