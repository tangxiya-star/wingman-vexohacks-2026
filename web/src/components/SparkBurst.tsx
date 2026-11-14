import { useEffect, useRef } from 'react'

/**
 * One-shot celebration for "it's a match": a burst of Wingman marks (six-spoke asterisks) and glossy
 * droplets from the agent's shape, in the match palette. Two waves, then they drift down and fade.
 * `?burst=hearts` swaps the marks for hearts, to compare.
 */
type Kind = 'mark' | 'drop' | 'heart'
type P = { x: number; y: number; vx: number; vy: number; r: number; rot: number; vr: number; size: number; color: string; kind: Kind; born: number; life: number }

const COLORS = ['#4f8a3a', '#7bb35e', '#d6be5c', '#efdc95', '#f2c4cc', '#fbf6ec'] // match greens + gold + blush; no strong red next to green (reads as Christmas)

export function SparkBurst({ originEl }: { originEl: () => HTMLElement | null }) {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return
    const c = ref.current!
    const ctx = c.getContext('2d')
    if (!ctx) return
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    const W = window.innerWidth
    const H = window.innerHeight
    c.width = W * dpr
    c.height = H * dpr
    ctx.scale(dpr, dpr)

    const box = originEl()?.getBoundingClientRect()
    const ox = box ? box.left + box.width / 2 : W / 2
    const oy = box ? box.top + box.height / 2 : H / 3
    const hearts = new URLSearchParams(location.search).get('burst') === 'hearts'
    const parts: P[] = []
    const wave = (n: number, at: number, speed: number) => {
      for (let i = 0; i < n; i++) {
        // mostly up and out, like it's been released from the shape
        const a = -Math.PI / 2 + (Math.random() - 0.5) * Math.PI * 1.5
        const v = speed * (0.55 + Math.random() * 0.6)
        const roll = Math.random()
        parts.push({
          x: ox + Math.cos(a) * 18,
          y: oy + Math.sin(a) * 18,
          vx: Math.cos(a) * v,
          vy: Math.sin(a) * v,
          r: 0,
          rot: Math.random() * Math.PI,
          vr: (Math.random() - 0.5) * 6,
          size: 7 + Math.random() * 9,
          color: COLORS[Math.floor(Math.random() * COLORS.length)],
          kind: roll < 0.6 ? (hearts ? 'heart' : 'mark') : 'drop',
          born: at,
          life: 1.3 + Math.random() * 0.7,
        })
      }
    }
    wave(26, 0, 620)
    wave(16, 0.18, 460)

    const draw = (p: P, alpha: number, scale: number) => {
      ctx.save()
      ctx.globalAlpha = alpha
      ctx.translate(p.x, p.y)
      ctx.rotate(p.rot)
      ctx.scale(scale, scale)
      const s = p.size
      ctx.fillStyle = p.color
      if (p.kind === 'mark') {
        for (let k = 0; k < 3; k++) {
          ctx.rotate(Math.PI / 3)
          ctx.beginPath()
          ctx.roundRect(-s * 0.09, -s / 2, s * 0.18, s, s * 0.09)
          ctx.fill()
        }
      } else if (p.kind === 'heart') {
        ctx.beginPath()
        ctx.moveTo(0, s * 0.35)
        ctx.bezierCurveTo(-s * 0.6, -s * 0.05, -s * 0.3, -s * 0.55, 0, -s * 0.2)
        ctx.bezierCurveTo(s * 0.3, -s * 0.55, s * 0.6, -s * 0.05, 0, s * 0.35)
        ctx.fill()
      } else {
        const g = ctx.createRadialGradient(-s * 0.15, -s * 0.15, 0, 0, 0, s * 0.42)
        g.addColorStop(0, '#ffffff')
        g.addColorStop(0.35, p.color)
        g.addColorStop(1, p.color)
        ctx.fillStyle = g
        ctx.beginPath()
        ctx.arc(0, 0, s * 0.42, 0, Math.PI * 2)
        ctx.fill()
      }
      ctx.restore()
    }

    let raf = 0
    const t0 = performance.now()
    let last = t0
    const frame = (now: number) => {
      const t = (now - t0) / 1000
      const dt = Math.min(0.033, (now - last) / 1000)
      last = now
      ctx.clearRect(0, 0, W, H)
      let alive = 0
      for (const p of parts) {
        const age = t - p.born
        if (age < 0) {
          alive++
          continue
        }
        if (age > p.life) continue
        alive++
        const drag = Math.exp(-dt * 2.4)
        p.vx *= drag
        p.vy = p.vy * drag + 520 * dt // gravity takes over once the push fades
        p.x += p.vx * dt
        p.y += p.vy * dt
        p.rot += p.vr * dt
        const u = age / p.life
        const scale = 0.6 + 0.4 * Math.min(1, age / 0.14) // never from zero
        const alpha = u < 0.6 ? 1 : 1 - (u - 0.6) / 0.4
        draw(p, alpha, scale)
      }
      if (alive) raf = requestAnimationFrame(frame)
      else ctx.clearRect(0, 0, W, H)
    }
    raf = requestAnimationFrame(frame)
    return () => cancelAnimationFrame(raf)
  }, [originEl])

  return <canvas ref={ref} className="burst" aria-hidden="true" />
}
