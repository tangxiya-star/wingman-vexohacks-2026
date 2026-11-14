import type { Pose } from '../types'

/**
 * Live cards the agent can put under the shape (show_card), built from the same pieces as the match card:
 * frosted card, small uppercase eyebrow, serif headline, raspberry accent (green once it's a match).
 */

export type HeartSample = { bpm: number; at: number }

/** Their own heart rate (WHOOP). Private: only ever rendered on the wearer's phone. */
export function HeartCard({ samples }: { samples: HeartSample[] }) {
  const now = samples[samples.length - 1]
  if (!now) return null
  const win = samples.filter((s) => now.at - s.at <= 60_000)
  const lo = Math.min(...win.map((s) => s.bpm)) - 4
  const hi = Math.max(...win.map((s) => s.bpm)) + 4
  const W = 280
  const H = 56
  const pts = win.map((s) => [W - ((now.at - s.at) / 60_000) * W, H - ((s.bpm - lo) / Math.max(1, hi - lo)) * H])
  const path = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const beat = 60 / Math.min(200, Math.max(40, now.bpm))
  const stale = Date.now() - now.at > 8000
  return (
    <section className="moment live live--heart" aria-label={`Your heart rate: ${now.bpm} beats per minute`}>
      <div className="moment__head">
        <span className="live__heart" style={{ animationDuration: `${beat}s` }} aria-hidden="true">
          <svg viewBox="0 0 24 24" width="22" height="22">
            <path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z" />
          </svg>
        </span>
        <div>
          <p className="moment__eyebrow">Your heart · only you see this</p>
          <p className="live__bpm">
            {now.bpm}
            <small>bpm</small>
          </p>
        </div>
      </div>
      {pts.length > 1 && (
        <svg className="live__spark" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
          <path d={path} />
          <circle cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="3" />
        </svg>
      )}
      <p className="moment__hint">{stale ? 'Waiting for your band…' : 'Last 60 seconds · WHOOP'}</p>
    </section>
  )
}

const POSE_TEXT: Record<Pose, string> = { up: 'Raised', down: 'Down', unknown: 'Waiting' }

/** Both bands during the match moment: raise them at the same time to confirm. */
export function BandsCard({ you, them, theirName, met, instruction }: { you: Pose; them: Pose; theirName: string; met: boolean; instruction: string }) {
  const both = met || (you === 'up' && them === 'up')
  return (
    <section className={`moment live live--bands ${both ? 'moment--met' : ''}`} aria-live="polite">
      <p className="moment__eyebrow">{met ? "It's a match" : "It's mutual · raise together"}</p>
      <div className="live__pair">
        <BandPlate who="You" pose={met ? 'up' : you} />
        <span className={`live__link ${both ? 'is-on' : ''}`} aria-hidden="true" />
        <BandPlate who={theirName || 'Them'} pose={met ? 'up' : them} />
      </div>
      <p className="live__verdict">{met ? `Meet ${theirName || 'them'}.` : both ? 'Both raised…' : you === 'up' ? `Waiting for ${theirName || 'them'}` : 'Find the other light'}</p>
      <p className="moment__hint">{met ? 'Your bands just turned green.' : instruction}</p>
    </section>
  )
}

function BandPlate({ who, pose }: { who: string; pose: Pose }) {
  return (
    <div className={`live__plate is-${pose}`}>
      <span className="live__who">{who}</span>
      <span className="live__pose">
        <i aria-hidden="true" />
        {POSE_TEXT[pose]}
      </span>
    </div>
  )
}
