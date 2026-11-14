import { useState } from 'react'
import type { Band, JoinPayload } from '../types'

const LOOKING_FOR: { value: JoinPayload['looking_for']; label: string }[] = [
  { value: 'serious', label: 'Something serious' },
  { value: 'open', label: 'Open to see' },
  { value: 'friends', label: 'New friends' },
]

export function Join({ band, onSubmit }: { band: Band; onSubmit: (p: JoinPayload) => void }) {
  const [name, setName] = useState('')
  const [weekend, setWeekend] = useState('')
  const [matters, setMatters] = useState('')
  const [lookingFor, setLookingFor] = useState<JoinPayload['looking_for'] | ''>('')
  const [dealbreaker, setDealbreaker] = useState('')
  const [consent, setConsent] = useState(false)

  const valid =
    name.trim() && weekend.trim() && matters.trim() && lookingFor && dealbreaker.trim() && consent

  return (
    <main className="screen screen--join">
      <h1 className="display">
        No photos.
        <br />
        <em>Just you.</em>
      </h1>
      <p className="lede">Four questions. We match on what actually matters.</p>

      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault()
          if (!valid) return
          onSubmit({
            band,
            name: name.trim(),
            weekend: weekend.trim(),
            matters_most: matters.trim(),
            looking_for: lookingFor as JoinPayload['looking_for'],
            dealbreaker: dealbreaker.trim(),
            consent: true,
          })
        }}
      >
        <label className="field">
          <span>Your first name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="given-name" placeholder="Holly" />
        </label>

        <label className="field">
          <span>A perfect weekend looks like…</span>
          <input value={weekend} onChange={(e) => setWeekend(e.target.value)} placeholder="A long hike, then dinner with friends" />
        </label>

        <label className="field">
          <span>What matters most to you right now</span>
          <input value={matters} onChange={(e) => setMatters(e.target.value)} placeholder="My family, and building something real" />
        </label>

        <fieldset className="field">
          <span>I'm looking for</span>
          <div className="segmented" role="radiogroup">
            {LOOKING_FOR.map((o) => (
              <button
                type="button"
                role="radio"
                aria-checked={lookingFor === o.value}
                key={o.value}
                className={lookingFor === o.value ? 'is-on' : ''}
                onClick={() => setLookingFor(o.value)}
              >
                {o.label}
              </button>
            ))}
          </div>
        </fieldset>

        <label className="field">
          <span>One thing I can't compromise on</span>
          <input value={dealbreaker} onChange={(e) => setDealbreaker(e.target.value)} placeholder="Honesty" />
        </label>

        <label className="consent">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          <span>I agree to be matched at this event.</span>
        </label>

        <p className="fineprint">Your band only starts looking for someone when you both say yes.</p>

        <button className="btn btn--primary" type="submit" disabled={!valid}>
          Join
        </button>
      </form>
    </main>
  )
}
