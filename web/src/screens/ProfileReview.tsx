import { useState } from 'react'
import { Plate } from '../components/Plate'
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
  if (!profile) {
    return (
      <main className="screen">
        <Plate mode="white" />
        <h2 className="title">Getting to know you…</h2>
        <p className="lede reading">Preparing your profile from the sources you shared.</p>
      </main>
    )
  }

  const core = profile.core ?? []
  const themes = core.filter((c) => c.kind === 'theme')
  const drawnTo = core.filter((c) => c.kind === 'drawn_to')
  const kept = [...core, ...profile.highlights].filter((h) => !removed.includes(h.id))
  const toggle = (id: string) => setRemoved((r) => (r.includes(id) ? r.filter((x) => x !== id) : [...r, id]))

  const coreList = (lines: CoreLine[]) => (
    <ul className="numbered">
      {lines.map((c) => {
        const off = removed.includes(c.id)
        return (
          <li key={c.id} className={off ? 'is-off' : ''}>
            <p className="numbered__text">{c.text}</p>
            <button type="button" className="remove" onClick={() => toggle(c.id)}>
              {off ? 'Undo' : 'Remove'}
            </button>
            {c.because.length > 0 && <p className="numbered__sub">From {c.because.join(', ')}</p>}
          </li>
        )
      })}
    </ul>
  )

  return (
    <main className="screen">
      <p className="eyebrow">What we picked up</p>
      <h2 className="title">Does this sound like you?</h2>
      <p className="fineprint">Remove anything you don't want used. Only overlaps are ever shown to a match.</p>

      {profile.says_vs_shows && (
        <section className="says">
          <h3 className="section-head">What you say vs. what you're drawn to</h3>
          <p className="says__text">{profile.says_vs_shows}</p>
        </section>
      )}

      {themes.length > 0 && (
        <section className="core-section" style={{ width: '100%' }}>
          <h3 className="section-head">Your core</h3>
          {coreList(themes)}
        </section>
      )}
      {drawnTo.length > 0 && (
        <section className="core-section" style={{ width: '100%' }}>
          <h3 className="section-head">You seem drawn to</h3>
          {coreList(drawnTo)}
        </section>
      )}

      <h3 className="section-head">Specifics</h3>
      <ul className="numbered">
        {profile.highlights.map((h) => {
          const off = removed.includes(h.id)
          return (
            <li key={h.id} className={off ? 'is-off' : ''}>
              <p className="numbered__text">
                <span className="numbered__src">{SOURCE_META[h.source]?.label ?? h.source}</span>
                {h.text}
              </p>
              <button type="button" className="remove" onClick={() => toggle(h.id)}>
                {off ? 'Undo' : 'Remove'}
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
