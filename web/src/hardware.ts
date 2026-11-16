import type { HeartRate, Pose } from './types'

export type HeartSample = HeartRate
export const QUICK_RAISE_INSTRUCTION = 'Raise your hand quickly once to accept.'
export const STAGE_MATCH_TITLE = 'We found a match for you'
export const STAGE_MATCH_INSTRUCTION = 'Raise your hand'

export function freshHeart(sample: HeartSample | undefined, now = Date.now()): sample is HeartSample & { bpm: number } {
  return !!sample && typeof sample.bpm === 'number' && Number.isFinite(sample.bpm)
    && sample.bpm > 0 && sample.bpm <= 600 && Number.isFinite(sample.at)
    && now - sample.at <= 8000 && sample.at - now <= 1000
}

/** Keep the source timestamp; reconnects must not make an old reading fresh. */
export function appendHeart(samples: HeartSample[], reading: HeartRate): HeartSample[] {
  if (!reading || !Number.isFinite(reading.at)
    || (reading.bpm !== null && (typeof reading.bpm !== 'number' || !Number.isFinite(reading.bpm)
      || reading.bpm <= 0 || reading.bpm > 600))) return []
  if (reading.bpm !== null && reading.at < (samples[samples.length - 1]?.at ?? -Infinity)) return samples
  const source = reading.source === 'Apple Watch' || reading.source === 'WHOOP' ? reading.source : undefined
  return [...samples.filter((sample) => reading.at - sample.at <= 90_000 && sample.at !== reading.at).slice(-179),
    { bpm: reading.bpm, at: reading.at, source }]
}

type StageHeart = { samples: HeartSample[]; backup: boolean }

/** Keep the stage display populated with bounded backup readings when the live feed expires. */
export function updateStageHeart(
  state: StageHeart,
  now: number,
  { reading, disconnected = false, step = 1 }: { reading?: HeartRate; disconnected?: boolean; step?: -1 | 1 } = {},
): StageHeart {
  const latest = state.samples[state.samples.length - 1]
  if (freshHeart(reading, now)) {
    const previous = state.backup ? state.samples.filter(sample => sample.at < reading.at) : state.samples
    return { samples: appendHeart(previous, { bpm: reading.bpm, at: reading.at }), backup: false }
  }
  if (!state.backup && !disconnected && reading?.bpm !== null && freshHeart(latest, now)) return state
  if (state.backup && latest && now - latest.at < 4000) return state

  const lastBpm = Math.max(80, Math.min(100, latest?.bpm ?? 90))
  const bpm = state.backup && latest
    ? lastBpm + (lastBpm === 80 ? 1 : lastBpm === 100 ? -1 : step)
    : lastBpm
  return { samples: appendHeart(state.samples, { bpm, at: now }), backup: true }
}

export function motionLabel(pose: Pose, latched: boolean): string {
  if (pose === 'unknown') return 'Unavailable'
  return latched ? (pose === 'up' ? 'Triggered' : 'Waiting') : (pose === 'up' ? 'Raised' : 'Not yet')
}
