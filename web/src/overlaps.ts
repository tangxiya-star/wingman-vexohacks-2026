import { SOURCE_META } from './sources'
import type { MatchFound, Overlap, RoomUpdate } from './types'

export const DIMENSION_LABEL: Record<Overlap['dimension'], string> = {
  taste: 'Taste',
  values: 'Values',
  intent: 'Wants',
  style: 'Style',
}

const sourceLabel = (s: string) => (s === 'answers' ? 'Told Wingman' : (SOURCE_META[s as keyof typeof SOURCE_META]?.label ?? s))

export type OverlapRow = { label: string; text: string; from: string }

/**
 * What two people share, as rows to show: one per dimension first (so it never reads as "you like the same films"),
 * then the rest. Falls back to the older fields for matches cached before overlaps existed.
 */
export function overlapRows(m: Pick<MatchFound, 'core_overlap' | 'type_fit' | 'shared_specifics'> & { overlaps?: Overlap[] } | RoomUpdate, max = 4): OverlapRow[] {
  const list = m.overlaps ?? []
  if (list.length) {
    const seen = new Set<string>()
    const first = list.filter((o) => !seen.has(o.dimension) && seen.add(o.dimension))
    const rest = list.filter((o) => !first.includes(o))
    return [...first, ...rest].slice(0, max).map((o) => ({
      label: DIMENSION_LABEL[o.dimension] ?? o.dimension,
      text: o.text,
      from: [...new Set(o.sources ?? [])].map(sourceLabel).join(' + '),
    }))
  }
  return [
    ...(m.shared_specifics ?? []).map((x) => ({ label: 'Taste', text: x.text, from: sourceLabel(x.source) })),
    ...(m.core_overlap ?? []).map((text) => ({ label: 'Core', text, from: '' })),
    ...(m.type_fit ? [{ label: 'Type', text: "You're each other's type", from: '' }] : []),
  ].slice(0, max)
}
