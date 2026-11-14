import { useEffect, useState } from 'react'
import { Orb } from '../components/Orb'
import { SOURCE_META } from '../sources'
import type { ProfileReady, SourceId } from '../types'

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

  const kept = profile.highlights.filter((h) => !removed.includes(h.id))

  return (
    <main className="screen">
      <p className="eyebrow">What Wingman picked up</p>
      <h2 className="title">Does this sound like you?</h2>
      <p className="fineprint">Remove anything you don't want used. Only overlaps are ever shown to a match.</p>

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
                onClick={() => setRemoved((r) => (off ? r.filter((x) => x !== h.id) : [...r, h.id]))}
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
