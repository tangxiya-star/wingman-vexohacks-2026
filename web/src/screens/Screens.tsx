import { useState } from 'react'
import { Orb } from '../components/Orb'
import { GestureDemo, gesture } from '../components/GestureDemo'
import type { ContactExchanged, MatchFound, WhisperReady } from '../types'
import { SOURCE_META } from '../sources'

export function Waiting() {
  return (
    <main className="screen screen--center">
      <Orb mode="white" />
      <h2 className="title">You're in.</h2>
      <p className="lede">We're looking for someone here who actually gets your taste.</p>
      <p className="fineprint">Keep your band on. It will glow when there's a match.</p>
    </main>
  )
}

export function Glow({ match, saidYes }: { match: MatchFound | null; saidYes: boolean }) {
  return (
    <main className="screen screen--center">
      <Orb mode="purple_slow" />
      <p className="eyebrow">Your band is glowing ✦</p>
      <h2 className="title">Someone here gets your taste.</h2>

      {match && (
        <section className="card">
          <ul className="specifics">
            {(match.core_overlap ?? []).map((v) => (
              <li key={v} className="specifics__core">
                <span className="specifics__icon">✦</span>
                <span>{v}</span>
              </li>
            ))}
            {match.type_fit && (
              <li className="specifics__core">
                <span className="specifics__icon">✦</span>
                <span>You're each other's type</span>
              </li>
            )}
            {match.shared_specifics.map((v) => (
              <li key={v.text}>
                <span className="specifics__icon">{SOURCE_META[v.source]?.icon ?? '✦'}</span>
                <span>{v.text}</span>
              </li>
            ))}
            {match.shared_values.map((v) => (
              <li key={v}>
                <span className="specifics__icon">✦</span>
                <span>{v}</span>
              </li>
            ))}
          </ul>
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
        </section>
      )}

      {saidYes ? (
        <p className="status">You said yes. Waiting for them…</p>
      ) : (
        <div className="instructions">
          <div>
            <strong>Tap once</strong>
            <span>I'd like to meet</span>
          </div>
          <div>
            <strong>Double tap</strong>
            <span>Pass</span>
          </div>
        </div>
      )}
    </main>
  )
}

export function Find() {
  return (
    <main className="screen screen--center">
      <Orb mode="purple_fast" size={120} />
      <p className="eyebrow">✦ You both said yes ✦</p>
      <h2 className="title">Look around for the other purple light.</h2>
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
    <main className="screen screen--center screen--spark">
      <Orb mode="green" />
      <p className="eyebrow eyebrow--green">✦ You found each other ✦</p>
      <h2 className="title">{theirName ? `Meet ${theirName}.` : 'You met.'}</h2>

      <button className="btn btn--play" onClick={play} disabled={!whisper}>
        {whisper ? '▶  Hear your opener' : 'Preparing your opener…'}
      </button>
      {played && whisper && <p className="opener">“{whisper.text}”</p>}

      <button className="btn btn--ghost" onClick={onContinue}>
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
      <main className="screen screen--center">
        <Orb mode="green" size={96} />
        <h2 className="title">You're connected.</h2>
        <section className="card">
          <p className="eyebrow">{contact.name}</p>
          <p className="contact">{contact.contact || '—'}</p>
          <p className="reason">{contact.second_date_idea}</p>
        </section>
      </main>
    )
  }

  if (step === 'sent' || bothAnswered) {
    return (
      <main className="screen screen--center">
        <Orb mode="off" size={96} />
        <h2 className="title">{bothAnswered ? 'Thanks for meeting!' : 'Got it.'}</h2>
        {!bothAnswered && <p className="lede">Waiting for their answer…</p>}
      </main>
    )
  }

  return (
    <main className="screen screen--center">
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

/** Same copy for passed / expired / no_match — never reveal a pass. */
export function NoMatch() {
  return (
    <main className="screen screen--center">
      <Orb mode="off" />
      <h2 className="title">No match right now.</h2>
      <p className="lede">We'll keep looking.</p>
    </main>
  )
}

export function Hidden() {
  return (
    <main className="screen screen--center">
      <Orb mode="off" />
      <h2 className="title">You're hidden.</h2>
      <p className="lede">You won't be matched with anyone.</p>
      <p className="fineprint">Ask the host to reset if you'd like to rejoin.</p>
    </main>
  )
}

export function BandsOffline() {
  return (
    <main className="screen screen--center">
      <Orb mode="off" />
      <h2 className="title">Reconnecting the bands…</h2>
      <p className="lede">Hang tight — this usually takes a few seconds.</p>
    </main>
  )
}
