import type { Pose } from '../types'
import { freshHeart, motionLabel, type HeartSample } from '../hardware'

/**
 * Live cards the agent can put under the shape (show_card), built from the same pieces as the match card:
 * frosted card, small uppercase eyebrow, serif headline, raspberry accent (green once it's a match).
 */

export type { HeartSample } from '../hardware'

/** Their own measured heart rate; never forwarded to the voice agent. */
export function HeartCard({ samples }: { samples: HeartSample[] }) {
  const now = samples[samples.length - 1]
  const fresh = freshHeart(now)
  const win = samples.filter((s): s is HeartSample & { bpm: number } =>
    typeof s.bpm === 'number' && Number.isFinite(s.bpm) && (now?.at ?? Date.now()) - s.at <= 60_000)
  const lo = Math.min(...win.map((s) => s.bpm)) - 4
  const hi = Math.max(...win.map((s) => s.bpm)) + 4
  const W = 280
  const H = 56
  const pts = win.map((s) => [W - (((now?.at ?? Date.now()) - s.at) / 60_000) * W, H - ((s.bpm - lo) / Math.max(1, hi - lo)) * H])
  const path = pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join(' ')
  const beat = fresh ? 60 / Math.min(200, Math.max(40, now.bpm)) : 1
  return (
    <section className="moment live live--heart" aria-label={fresh ? `Your heart rate: ${now.bpm} beats per minute` : 'Heart rate unavailable'}>
      <div className="moment__head">
        <span className="live__heart" style={{ animationDuration: `${beat}s`, animationPlayState: fresh ? 'running' : 'paused' }} aria-hidden="true">
          <svg viewBox="0 0 24 24" width="22" height="22">
            <path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z" />
          </svg>
        </span>
        <div>
          <p className="moment__eyebrow">Your heart · only you see this</p>
          <p className="live__bpm">
            {fresh ? now.bpm : '--'}
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
      <p className="moment__hint">{fresh ? `Last 60 seconds · ${now.source || 'Heart rate'}` : `Waiting for ${now?.source || 'your heart-rate source'}…`}</p>
    </section>
  )
}

/** Legacy pose wire values are explicitly labelled as triggers in latch mode. */
export function BandsCard({ you, them, theirName, met, instruction, spot, wearing, latched = false }: { you: Pose; them: Pose; theirName: string; met: boolean; instruction: string; spot?: string; wearing?: string; latched?: boolean }) {
  const both = you === 'up' && them === 'up'
  return (
    <section className={`moment live live--bands ${both ? 'moment--met' : ''}`} aria-live="polite">
      <p className="moment__eyebrow">{met ? "It's a match" : latched ? 'Your quick-raise confirmations' : "It's mutual · raise together"}</p>
      <div className="live__pair">
        <BandPlate who="You" pose={you} latched={latched} />
        <span className={`live__link ${both ? 'is-on' : ''}`} aria-hidden="true" />
        <BandPlate who={theirName || 'Them'} pose={them} latched={latched} />
      </div>
      {!met && (spot || wearing) && (
        <dl className="live__find">
          {spot && (
            <div>
              <dt>Meet</dt>
              <dd>{spot.charAt(0).toUpperCase() + spot.slice(1)}</dd>
            </div>
          )}
          {wearing && (
            <div>
              <dt>Look for</dt>
              <dd>{wearing}</dd>
            </div>
          )}
        </dl>
      )}
      <p className="live__verdict">{met ? `Meet ${theirName || 'them'}.` : both ? (latched ? 'Both actions registered' : 'Both raised…') : you === 'up' ? `Waiting for ${theirName || 'them'}` : latched ? 'Waiting for your quick raise' : 'Find the other light'}</p>
      <p className="moment__hint">{met ? 'Your meeting is confirmed.' : instruction}</p>
      {latched && <p className="moment__hint live__out">Triggered means your action was registered this round, not that your arm is still raised.</p>}
      {!met && !latched && <p className="moment__hint live__out">Not feeling it in person? Double-tap your band to leave quietly. They'll never know why.</p>}
    </section>
  )
}

function BandPlate({ who, pose, latched }: { who: string; pose: Pose; latched: boolean }) {
  return (
    <div className={`live__plate is-${pose}`}>
      <span className="live__who">{who}</span>
      <span className="live__pose">
        <i aria-hidden="true">
          <svg viewBox="0 0 12 12" width="10" height="10">
            <path d="M6 9.5V2.5M2.75 5.5 6 2.25 9.25 5.5" />
          </svg>
        </i>
        {motionLabel(pose, latched)}
      </span>
    </div>
  )
}
