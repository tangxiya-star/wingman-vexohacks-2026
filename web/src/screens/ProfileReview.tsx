import { useEffect, useState } from 'react'
import { Orb } from '../components/Orb'
import { SOURCE_META } from '../sources'
import type { CoreLine, ProfileReady, SourceId } from '../types'

export function ProfileReview({
  profile,
  connectedSources,
  onConfirm,
}: {
  profile: ProfileReady | null
  connectedSources: SourceId[]
  onConfirm: (removed: string[]) => void
}) {
  const [removed, setRemoved] = useState<string[]>([])
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (profile) return
    const t = setInterval(() => setTick((n) => n + 1), 1100)
    return () => clearInterval(t)
  }, [profile])

  if (!profile) {
    const reading = connectedSources.length ? connectedSources[tick % connectedSources.length] : null
    return (
      <main className="screen screen--center">
        <Orb mode="white" size={120} />
        <h2 className="title">Getting to know you…</h2>
        {reading && (
          <p className="lede reading" key={reading}>
            {SOURCE_META[reading].icon} Reading your {SOURCE_META[reading].label}
          </p>
        )}
      </main>
    )
  }

  const core = profile.core ?? []
  const themes = core.filter((c) => c.kind === 'theme')
  const drawnTo = core.filter((c) => c.kind === 'drawn_to')
  const kept = [...core, ...profile.highlights].filter((h) => !removed.includes(h.id))
  const toggle = (id: string) => setRemoved((r) => (r.includes(id) ? r.filter((x) => x !== id) : [...r, id]))

  const coreList = (lines: CoreLine[]) => (
    <ul className="core">
      {lines.map((c) => {
        const off = removed.includes(c.id)
        return (
          <li key={c.id} className={off ? 'is-off' : ''}>
            <div className="core__body">
              <p className="core__text">{c.text}</p>
              {c.because.length > 0 && <p className="core__because">because {c.because.join(' · ')}</p>}
            </div>
            <button type="button" className="highlights__x" aria-label={off ? 'Restore' : 'Remove'} onClick={() => toggle(c.id)}>
              {off ? '↺' : '✕'}
            </button>
          </li>
        )
      })}
    </ul>
  )

  return (
    <main className="screen">
      <p className="eyebrow">What Wingman picked up</p>
      <h2 className="title">Does this sound like you?</h2>
      <p className="fineprint">Remove anything you don't want used. Only overlaps are ever shown to a match.</p>

      {themes.length > 0 && (
        <section className="core-section">
          <h3 className="section-head">Your core</h3>
          {coreList(themes)}
        </section>
      )}
      {drawnTo.length > 0 && (
        <section className="core-section">
          <h3 className="section-head">You seem drawn to</h3>
          {coreList(drawnTo)}
        </section>
      )}

      <h3 className="section-head">Specifics</h3>
      <ul className="highlights">
        {profile.highlights.map((h) => {
          const off = removed.includes(h.id)
          return (
            <li key={h.id} className={off ? 'is-off' : ''}>
              <span className="highlights__icon">{SOURCE_META[h.source]?.icon ?? '✦'}</span>
              <span className="highlights__text">{h.text}</span>
              <button
                type="button"
                className="highlights__x"
                aria-label={off ? 'Restore' : 'Remove'}
                onClick={() => toggle(h.id)}
              >
                {off ? '↺' : '✕'}
              </button>
            </li>
          )
        })}
      </ul>

      {profile.failed_sources.length > 0 && (
        <p className="fineprint">
          Couldn't read {profile.failed_sources.map((s) => SOURCE_META[s]?.label ?? s).join(', ')} — skipped.
        </p>
      )}

      <button className="btn btn--primary" disabled={kept.length === 0} onClick={() => onConfirm(removed)}>
        Looks like me
      </button>
    </main>
  )
}
