import { useEffect, useRef } from 'react'

export type BlobMood = 'idle' | 'listening' | 'speaking' | 'rest'

const VERT = `attribute vec2 a; void main(){ gl_Position = vec4(a, 0.0, 1.0); }`

// Domain-warped fbm gradient. t = accumulated phase (advances faster while someone talks),
// lv = smoothed voice level (deepens the warp), sat = saturation per mood.
const FRAG = `precision highp float;
uniform vec2 r; uniform float t; uniform float lv; uniform float sat; uniform float seed;
float hash(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p){
  vec2 i = floor(p), f = fract(p); vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x), mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
}
float fbm(vec2 p){ float v = 0.0, a = 0.5; for (int i = 0; i < 5; i++){ v += a * noise(p); p = p * 2.03 + vec2(1.7, 9.2); a *= 0.5; } return v; }
void main(){
  vec2 uv = gl_FragCoord.xy / r;
  vec2 p = uv * 1.5 + seed;
  float w = 0.6 + lv * 1.1;
  vec2 q = vec2(fbm(p + t * 0.11), fbm(p + vec2(5.2, 1.3) - t * 0.09));
  vec2 s = vec2(fbm(p + w * q + vec2(1.7, 9.2) + t * 0.15), fbm(p + w * q + vec2(8.3, 2.8) - t * 0.13));
  float f = fbm(p + w * s);

  vec3 mag = vec3(0.80, 0.31, 0.46);
  vec3 coral = vec3(0.90, 0.50, 0.40);
  vec3 yel = vec3(0.93, 0.84, 0.55);
  vec3 olive = vec3(0.68, 0.77, 0.42);

  float m1 = smoothstep(0.2, 0.8, f + (uv.x - 0.5) * 0.7);
  float m2 = smoothstep(0.42, 0.85, s.y * 0.7 + (0.5 - uv.y) * 1.3);
  vec3 top = mix(mag, coral, m1);
  vec3 bot = mix(yel, olive, smoothstep(0.3, 0.85, q.x + (uv.x - 0.5) * 0.9));
  vec3 col = mix(top, bot, m2);

  float l = dot(col, vec3(0.299, 0.587, 0.114));
  col = mix(vec3(l), col, sat);
  col = pow(col, vec3(0.92));
  col += lv * 0.05;
  col += (hash(gl_FragCoord.xy + fract(t * 3.0) * 97.0) - 0.5) * 0.045;
  gl_FragColor = vec4(col, 1.0);
}`

const MOOD = {
  rest: { speed: 0.35, sat: 0.6 },
  idle: { speed: 0.6, sat: 1.0 },
  listening: { speed: 0.85, sat: 1.0 },
  speaking: { speed: 1.0, sat: 1.12 },
} as const

/**
 * Living gradient for the agent. Idles slowly; while anyone talks, `getLevel()` (0..1 voice volume)
 * pushes the flow forward in bursts — so it moves with the rhythm of speech, not just loudness.
 * Also writes --level on the parent so CSS can scale the squircle.
 */
export function ShaderBlob({ getLevel, mood }: { getLevel: () => number; mood: BlobMood }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const moodRef = useRef(mood)
  moodRef.current = mood
  const levelFn = useRef(getLevel)
  levelFn.current = getLevel

  useEffect(() => {
    const c = canvas.current!
    const gl = c.getContext('webgl', { antialias: false, premultipliedAlpha: false })
    if (!gl) return // CSS blobs underneath stay visible
    const sh = (type: number, src: string) => {
      const s = gl.createShader(type)!
      gl.shaderSource(s, src)
      gl.compileShader(s)
      return s
    }
    const prog = gl.createProgram()!
    gl.attachShader(prog, sh(gl.VERTEX_SHADER, VERT))
    gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FRAG))
    gl.linkProgram(prog)
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return
    gl.useProgram(prog)
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer())
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW)
    const a = gl.getAttribLocation(prog, 'a')
    gl.enableVertexAttribArray(a)
    gl.vertexAttribPointer(a, 2, gl.FLOAT, false, 0, 0)
    const U = (n: string) => gl.getUniformLocation(prog, n)
    const uR = U('r'), uT = U('t'), uLv = U('lv'), uSat = U('sat')
    gl.uniform1f(U('seed'), Math.random() * 10)
    c.classList.add('is-on')

    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches
    const resize = () => {
      const scale = 0.5 // it's a soft blur — half resolution is plenty and cheap on phones
      c.width = Math.max(2, Math.round(c.clientWidth * scale))
      c.height = Math.max(2, Math.round(c.clientHeight * scale))
      gl.viewport(0, 0, c.width, c.height)
      gl.uniform2f(uR, c.width, c.height)
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(c)

    let raf = 0
    let last = performance.now()
    let phase = 0
    let level = 0
    let sat = MOOD[moodRef.current].sat
    const parent = c.parentElement
    const frame = (now: number) => {
      const dt = Math.min(0.05, (now - last) / 1000)
      last = now
      let raw = 0
      try {
        raw = Math.min(1, levelFn.current() * 2.2)
      } catch {}
      // fast attack, slower release → syllables read as pulses
      level += (raw - level) * (raw > level ? 0.35 : 0.08)
      const m = MOOD[moodRef.current]
      sat += (m.sat - sat) * 0.04
      phase += dt * (reduce ? 0.15 : m.speed + level * 5)
      gl.uniform1f(uT, phase)
      gl.uniform1f(uLv, level)
      gl.uniform1f(uSat, sat)
      gl.drawArrays(gl.TRIANGLES, 0, 3)
      parent?.style.setProperty('--level', level.toFixed(3))
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
    }
  }, [])

  return <canvas ref={canvas} className="blob__canvas" aria-hidden="true" />
}
