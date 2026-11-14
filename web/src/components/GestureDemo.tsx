import gesture from '../config/gesture.json'

/**
 * Looping hint for the match gesture.
 * The gesture is still TBD (docs/contract.md §5) — swap src/config/gesture.json
 * and, if needed, add a dedicated animation keyed by gesture.id here.
 */
export function GestureDemo({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`gesture ${compact ? 'gesture--compact' : ''}`} data-gesture={gesture.id}>
      <div className="gesture__stage">
        <div className="gesture__wrist gesture__wrist--left">
          <span className="gesture__band" />
        </div>
        <div className="gesture__wrist gesture__wrist--right">
          <span className="gesture__band" />
        </div>
        <span className="gesture__spark" />
      </div>
      <p className="gesture__name">{gesture.name}</p>
    </div>
  )
}

export { gesture }
