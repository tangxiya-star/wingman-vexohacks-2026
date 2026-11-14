import type { LedMode } from '../types'

/** A glowing circle that mirrors a band's LED. */
export function Orb({ mode, size = 160, label }: { mode: LedMode; size?: number; label?: string }) {
  return (
    <div className={`orb orb--${mode}`} style={{ width: size, height: size }} aria-label={label ?? `Band light: ${mode}`}>
      <span className="orb__ring" />
      <span className="orb__core" />
    </div>
  )
}
