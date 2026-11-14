import { useState } from 'react'
import { Plate } from '../components/Plate'
import { GestureDemo, gesture } from '../components/GestureDemo'
import type { ContactExchanged, MatchFound, WhisperReady } from '../types'
import { SOURCE_META } from '../sources'

export function Waiting() {
  return (
    <main className="screen">
      <Plate mode="white" />
      <h2 className="title">You're in.</h2>
      <div className="cols">
        <p>We're looking for someone in this room who actually gets your taste.</p>
        <p>Keep your band on. It lights up when there's someone worth meeting.</p>
      </div>
    </main>
  )
}

/** Core overlap + specifics as one numbered list. */
export function Overlaps({ match, they = false }: { match: Pick<MatchFound, 'core_overlap' | 'type_fit' | 'shared_specifics' | 'shared_values'>; they?: boolean }) {
  return (
    <ul className="numbered">
      {(match.core_overlap ?? []).map((v) => (
        <li key={v}>
          <p className="numbered__text">{v}</p>
        </li>
      ))}
      {match.type_fit && (
        <li>
          <p className="numbered__text">{they ? "They're each other's type." : "You're each other's type."}</p>
        </li>
      )}
      {match.shared_specifics.map((v) => (
        <li key={v.text}>
          <p className="numbered__text">
            <span className="numbered__src">{SOURCE_META[v.source]?.label}</span>
            {v.text}
          </p>
        </li>
      ))}
      {match.shared_values.map((v) => (
        <li key={v}>
          <p className="numbered__text">{v}</p>
        </li>
      ))}
    </ul>
  )
}

export function Glow({ match, saidYes }: { match: MatchFound | null; saidYes: boolean }) {
  return (
    <main className="screen">
      <Plate mode="purple_slow" ratio="5 / 4">
        <p className="eyebrow">Your band is glowing</p>
      </Plate>
      <h2 className="title">Someone here gets your taste.</h2>

      {match && (
        <>
          <Overlaps match={match} />
          <p className="reason">{match.reason}</p>
          {match.evidence.length > 0 && (
            <details className="evidence">
              <summary>Why we think so</summary>
              <ul>
                {match.evidence.map((e) => (
                  <li key={e}>{e}</li>
                ))}
              </ul>
            </details>
          )}
        </>
      )}

      {saidYes ? (
        <p className="status">You said yes. Waiting for them…</p>
      ) : (
        <div className="cols">
          <p>
            <strong>Tap once</strong>I'd like to meet
          </p>
          <p>
            <strong>Double tap</strong>Pass — they'll never know
          </p>
        </div>
      )}
    </main>
  )
}

export function Find() {
  return (
    <main className="screen">
      <Plate mode="purple_fast" ratio="5 / 4">
        <p className="eyebrow">You both said yes</p>
      </Plate>
      <h2 className="title">Look around for the other light.</h2>
      <GestureDemo />
      <p className="lede">{gesture.instruction}</p>
      <p className="fineprint">{gesture.hint}</p>
    </main>
  )
}

function speak(text: string) {
  if (!('speechSynthesis' in window)) return
  const u = new SpeechSynthesisUtterance(text)
  u.rate = 0.95
  window.speechSynthesis.cancel()
  window.speechSynthesis.speak(u)
}

export function Spark({
  theirName,
  whisper,
  onContinue,
}: {
  theirName?: string
  whisper: WhisperReady | null
  onContinue: () => void
}) {
  const [played, setPlayed] = useState(false)

  const play = () => {
    if (!whisper) return
    setPlayed(true)
    if (whisper.audio_url) {
      new Audio(whisper.audio_url).play().catch(() => speak(whisper.text))
    } else {
      speak(whisper.text)
    }
  }

  return (
    <main className="screen">
      <Plate mode="green" ratio="4 / 5" mark={false}>
        <p className="eyebrow">You found each other</p>
        <h2 className="title">{theirName ? `Meet ${theirName}.` : 'You met.'}</h2>
      </Plate>

      <button className="btn btn--play" onClick={play} disabled={!whisper}>
        <span>{whisper ? 'Hear your opener' : 'Preparing your opener…'}</span>
        <span className="btn__icon">▶</span>
      </button>
      {played && whisper && <p className="opener">“{whisper.text}”</p>}

      <button className="link" onClick={onContinue}>
        Continue
      </button>
    </main>
  )
}

export function StayInTouch({
  theirName,
  contact,
  bothAnswered,
  onAnswer,
}: {
  theirName?: string
  contact: ContactExchanged | null
  bothAnswered: boolean
  onAnswer: (yes: boolean, contact?: string) => void
}) {
  const [step, setStep] = useState<'ask' | 'contact' | 'sent'>('ask')
  const [value, setValue] = useState('')

  if (contact) {
    return (
      <main className="screen">
        <Plate mode="green" ratio="16 / 9" />
        <p className="eyebrow">{contact.name}</p>
        <p className="contact">{contact.contact || '—'}</p>
        <div className="cols">
          <p>
            <strong>Next time</strong>
            {contact.second_date_idea}
          </p>
          <p>
            <strong>You're connected</strong>
            Only the two of you can see this.
          </p>
        </div>
      </main>
    )
  }

  if (step === 'sent' || bothAnswered) {
    return (
      <main className="screen">
        <Plate mode="off" ratio="16 / 9" />
        <h2 className="title">{bothAnswered ? 'Thanks for meeting.' : 'Got it.'}</h2>
        {!bothAnswered && <p className="lede">Waiting for their answer…</p>}
      </main>
    )
  }

  return (
    <main className="screen">
      <p className="eyebrow">{theirName ? `You met ${theirName}` : 'You met'}</p>
      <h2 className="title">Want to stay in touch?</h2>
      <p className="fineprint">We only share contacts if you both say yes. Nobody learns who said no.</p>

      {step === 'ask' ? (
        <div className="row">
          <button className="btn btn--primary" onClick={() => setStep('contact')}>
            Yes
          </button>
          <button
            className="btn btn--ghost"
            onClick={() => {
              onAnswer(false)
              setStep('sent')
            }}
          >
            No thanks
          </button>
        </div>
      ) : (
        <form
          className="form"
          onSubmit={(e) => {
            e.preventDefault()
            if (!value.trim()) return
            onAnswer(true, value.trim())
            setStep('sent')
          }}
        >
          <label className="field">
            <span>Instagram or phone</span>
            <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="@holly" autoFocus />
          </label>
          <button className="btn btn--primary" type="submit" disabled={!value.trim()}>
            Share if they say yes
          </button>
        </form>
      )}
    </main>
  )
}

function Quiet({ title, lede, fine }: { title: string; lede: string; fine?: string }) {
  return (
    <main className="screen">
      <Plate mode="off" ratio="16 / 9" />
      <h2 className="title">{title}</h2>
      <p className="lede">{lede}</p>
      {fine && <p className="fineprint">{fine}</p>}
    </main>
  )
}

/** Same copy for passed / expired / no_match — never reveal a pass. */
export const NoMatch = () => <Quiet title="No match right now." lede="We'll keep looking." />
export const Hidden = () => <Quiet title="You're hidden." lede="You won't be matched with anyone." fine="Ask the host to reset if you'd like to rejoin." />
export const BandsOffline = () => <Quiet title="Reconnecting the bands…" lede="Hang tight — this usually takes a few seconds." />
