import type { ReactNode } from 'react'
import type { LedMode } from '../types'

/** Wingman mark: a six-spoke asterisk. */
export function Mark({ className = '', size = 28 }: { className?: string; size?: number }) {
  return (
    <svg className={`mark ${className}`} width={size} height={size} viewBox="-50 -50 100 100" aria-hidden="true">
      {[0, 60, 120].map((r) => (
        <rect key={r} x={-8} y={-47} width={16} height={94} rx={8} transform={`rotate(${r})`} />
      ))}
    </svg>
  )
}

/**
 * A soft, out-of-focus "photograph" that mirrors a band's LED.
 * off = haze · white = daylight sky · purple = dusk (pulses) · green = meadow.
 */
export function Plate({
  mode,
  ratio = '4 / 5',
  mark = true,
  className = '',
  children,
}: {
  mode: LedMode
  ratio?: string
  mark?: boolean
  className?: string
  children?: ReactNode
}) {
  return (
    <div className={`plate plate--${mode} ${className}`} style={{ aspectRatio: ratio }} aria-label={`Band light: ${mode}`}>
      <div className="plate__field">
        <i />
        <i />
        <i />
        <i />
        <i />
        <i />
      </div>
      <div className="plate__veil" />
      <div className="plate__grain" />
      {mark && <Mark className="plate__mark" size={56} />}
      {children && <div className="plate__over">{children}</div>}
    </div>
  )
}
