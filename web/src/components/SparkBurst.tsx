import { useEffect, useRef } from 'react'

/**
 * One-shot celebration for "it's a match": gold foil flakes (with a few Wingman marks and glints) thrown up
 * out of the agent's shape. Flakes flip as they fall, so they catch the light, and flutter side to side.
 * `?burst=hearts` swaps the marks for hearts, to compare.
 */
type Kind = 'foil' | 'mark' | 'glint' | 'heart'
type P = { x: number; y: number; vx: number; vy: number; r: number; rot: number; vr: number; flip: number; vf: number; sway: number; size: number; color: string; kind: Kind; born: number; life: number }

const GOLD = ['#a8792a', '#c9962f', '#ddb24a', '#ecca6e', '#f6e2a0', '#fff3cf']

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
        const kind: Kind = roll < 0.72 ? 'foil' : roll < 0.86 ? (hearts ? 'heart' : 'mark') : 'glint'
        parts.push({
          x: ox + Math.cos(a) * 18,
          y: oy + Math.sin(a) * 18,
          vx: Math.cos(a) * v,
          vy: Math.sin(a) * v,
          r: 0,
          rot: Math.random() * Math.PI,
          vr: (Math.random() - 0.5) * 5,
          flip: Math.random() * Math.PI * 2,
          vf: 6 + Math.random() * 8,
          sway: Math.random() * Math.PI * 2,
          size: kind === 'foil' ? 8 + Math.random() * 8 : kind === 'glint' ? 6 + Math.random() * 6 : 9 + Math.random() * 7,
          color: kind === 'heart' ? ['#f2c4cc', '#ddb24a', '#fff3cf'][i % 3] : kind === 'mark' ? '#fbf6ec' : GOLD[Math.floor(Math.random() * GOLD.length)],
          kind,
          born: at,
          life: 2.2 + Math.random() * 1.2,
        })
      }
    }
    wave(46, 0, 760)
    wave(30, 0.22, 560)
    wave(18, 0.5, 420)

    const draw = (p: P, alpha: number, scale: number) => {
      ctx.save()
      ctx.globalAlpha = alpha
      ctx.translate(p.x, p.y)
      ctx.rotate(p.rot)
      ctx.scale(scale, scale)
      const s = p.size
      ctx.fillStyle = p.color
      if (p.kind === 'foil') {
        // a flat flake: its width follows the flip, and it brightens as it faces the light
        const face = Math.cos(p.flip)
        ctx.scale(1, Math.max(0.12, Math.abs(face)))
        ctx.fillStyle = face > 0.55 ? '#fff6d8' : p.color
        ctx.fillRect(-s / 2, -s * 0.32, s, s * 0.64)
      } else if (p.kind === 'glint') {
        ctx.globalAlpha = alpha * (0.4 + 0.6 * Math.abs(Math.sin(p.flip)))
        ctx.fillStyle = '#fffaf0'
        ctx.beginPath()
        for (let k = 0; k < 8; k++) {
          const rr = k % 2 ? s * 0.12 : s * 0.5
          const a = (k * Math.PI) / 4
          ctx[k ? 'lineTo' : 'moveTo'](Math.cos(a) * rr, Math.sin(a) * rr)
        }
        ctx.fill()
      } else if (p.kind === 'mark') {
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
        const drag = Math.exp(-dt * 2.6)
        p.vx *= drag
        p.vy = Math.min(p.vy * drag + 420 * dt, 120) // gravity takes over, but flakes fall slowly like foil
        p.sway += dt * 3
        p.x += (p.vx + Math.sin(p.sway) * 26) * dt // flutter
        p.y += p.vy * dt
        p.rot += p.vr * dt
        p.flip += p.vf * dt
        const u = age / p.life
        const scale = 0.6 + 0.4 * Math.min(1, age / 0.14) // never from zero
        const alpha = u < 0.65 ? 1 : 1 - (u - 0.65) / 0.35
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
