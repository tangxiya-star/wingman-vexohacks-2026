import { useState } from 'react'
import type { Band, JoinPayload, Sources } from '../types'
import { SOURCE_META, compressImage } from '../sources'

const LOOKING_FOR: { value: JoinPayload['looking_for']; label: string }[] = [
  { value: 'serious', label: 'Something serious' },
  { value: 'open', label: 'Open to see' },
  { value: 'friends', label: 'New friends' },
]

const MAX_SHOTS = 4

function UsernameCard({
  id,
  hint,
  value,
  onChange,
  prefix,
}: {
  id: 'letterboxd' | 'reddit'
  hint: string
  value: string
  onChange: (v: string) => void
  prefix: string
}) {
  const meta = SOURCE_META[id]
  const on = value.trim().length > 0
  return (
    <div className={`source ${on ? 'is-on' : ''}`}>
      <div className="source__head">
        <span className="source__icon">{meta.icon}</span>
        <span className="source__label">{meta.label}</span>
        {on && <span className="source__check">✓</span>}
      </div>
      <label className="source__input">
        <span>{prefix}</span>
        <input
          value={value}
          onChange={(e) => onChange(e.target.value.replace(/^@|^u\//, ''))}
          placeholder="username"
          autoCapitalize="none"
          autoCorrect="off"
          spellCheck={false}
          aria-label={`${meta.label} username`}
        />
      </label>
      <p className="source__hint">{hint}</p>
    </div>
  )
}

function ScreenshotCard({
  id,
  hint,
  shots,
  onChange,
}: {
  id: 'tiktok' | 'instagram'
  hint: string
  shots: string[]
  onChange: (s: string[]) => void
}) {
  const meta = SOURCE_META[id]
  const [busy, setBusy] = useState(false)
  const on = shots.length > 0

  const add = async (files: FileList | null) => {
    if (!files?.length) return
    setBusy(true)
    try {
      const room = MAX_SHOTS - shots.length
      const picked = Array.from(files).filter((f) => f.type.startsWith('image/')).slice(0, room)
      const encoded = await Promise.all(picked.map((f) => compressImage(f)))
      onChange([...shots, ...encoded])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={`source ${on ? 'is-on' : ''}`}>
      <div className="source__head">
        <span className="source__icon">{meta.icon}</span>
        <span className="source__label">{meta.label}</span>
        {on && <span className="source__check">✓</span>}
      </div>
      <div className="shots">
        {shots.map((src, i) => (
          <button
            type="button"
            className="shot"
            key={i}
            onClick={() => onChange(shots.filter((_, j) => j !== i))}
            aria-label="Remove screenshot"
          >
            <img src={src} alt="" />
            <span>✕</span>
          </button>
        ))}
        {shots.length < MAX_SHOTS && (
          <label className="shot shot--add">
            <input type="file" accept="image/*" multiple onChange={(e) => add(e.target.files)} hidden />
            <span>{busy ? '…' : '+'}</span>
          </label>
        )}
      </div>
      <p className="source__hint">{hint}</p>
    </div>
  )
}

export function Join({ band, onSubmit }: { band: Band; onSubmit: (p: JoinPayload) => void }) {
  const [letterboxd, setLetterboxd] = useState('')
  const [reddit, setReddit] = useState('')
  const [tiktok, setTiktok] = useState<string[]>([])
  const [instagram, setInstagram] = useState<string[]>([])
  const [name, setName] = useState('')
  const [lookingFor, setLookingFor] = useState<JoinPayload['looking_for'] | ''>('')
  const [dealbreaker, setDealbreaker] = useState('')
  const [consent, setConsent] = useState(false)
  const [sourceConsent, setSourceConsent] = useState(false)

  const sources: Sources = {}
  if (letterboxd.trim()) sources.letterboxd = { username: letterboxd.trim() }
  if (reddit.trim()) sources.reddit = { username: reddit.trim() }
  if (tiktok.length) sources.tiktok = { screenshots: tiktok }
  if (instagram.length) sources.instagram = { screenshots: instagram }
  const connected = Object.keys(sources).length

  const valid = connected >= 2 && name.trim() && lookingFor && dealbreaker.trim() && consent && sourceConsent

  return (
    <main className="screen screen--join">
      <h1 className="display">
        Show us
        <br />
        <em>the real you.</em>
      </h1>
      <p className="lede">Not a bio. What you actually watch, save and talk about.</p>

      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault()
          if (!valid) return
          onSubmit({
            band,
            name: name.trim(),
            looking_for: lookingFor as JoinPayload['looking_for'],
            dealbreaker: dealbreaker.trim(),
            consent: true,
            source_consent: true,
            sources,
          })
        }}
      >
        <div className="section-head">
          <span>Connect at least two</span>
          <span className={connected >= 2 ? 'count is-ok' : 'count'}>{connected}/2</span>
        </div>

        <div className="sources">
          <UsernameCard id="letterboxd" prefix="@" hint="Your public ratings & reviews" value={letterboxd} onChange={setLetterboxd} />
          <UsernameCard id="reddit" prefix="u/" hint="Your public posts & subreddits" value={reddit} onChange={setReddit} />
          <ScreenshotCard id="tiktok" hint="Screenshot your Favorites or Liked tab" shots={tiktok} onChange={setTiktok} />
          <ScreenshotCard id="instagram" hint="Screenshot your Saved or Following" shots={instagram} onChange={setInstagram} />
        </div>

        <div className="section-head">
          <span>Three quick things</span>
        </div>

        <label className="field">
          <span>Your first name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} autoComplete="given-name" placeholder="Holly" />
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
          <input type="checkbox" checked={sourceConsent} onChange={(e) => setSourceConsent(e.target.checked)} />
          <span>Wingman may read what I connect — for this event only. Deleted afterwards.</span>
        </label>
        <label className="consent">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
          <span>I agree to be matched at this event.</span>
        </label>

        <p className="fineprint">
          Nobody sees your feeds or screenshots — only what you have in common. Your band only starts looking when you both say yes.
        </p>

        <button className="btn btn--primary" type="submit" disabled={!valid}>
          Join
        </button>
      </form>
    </main>
  )
}
