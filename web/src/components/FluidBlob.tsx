import { useEffect, useRef } from 'react'

export type BlobMood = 'idle' | 'listening' | 'speaking' | 'rest'
export type BlobPalette = 'bloom' | 'lagoon'

/**
 * core (deep, gives depth) → body → band/iris (hues the surface drifts through with angle) → rim (emissive light).
 */
export const PALETTES: Record<BlobPalette, { core: number[]; body: number[]; band: number[]; iris: number[]; rim: number[]; glow: number[]; bg: string }> = {
  // raspberry light: wine depth, raspberry body, olive-lime + gold shimmer, rose-cream rim, on neutral grey
  bloom: { core: [0.42, 0.04, 0.14], body: [0.84, 0.22, 0.36], band: [0.6, 0.74, 0.3], iris: [0.96, 0.74, 0.36], rim: [1.0, 0.89, 0.85], glow: [0.9, 0.36, 0.44], bg: '#e6e6e4' },
  // navy / teal / lime on pale mint
  lagoon: { core: [0.06, 0.08, 0.32], body: [0.13, 0.46, 0.62], band: [0.36, 0.86, 0.5], iris: [0.4, 0.75, 1.0], rim: [0.86, 1.0, 0.6], glow: [0.55, 0.85, 0.6], bg: '#dde7e4' },
}

const VERT = `attribute vec2 a; void main(){ gl_Position = vec4(a, 0.0, 1.0); }`

const FRAG = `precision highp float;
uniform vec2 r; uniform float t; uniform float lv; uniform float sat;
uniform vec3 cCore, cBody, cRim, cBand, cIris, cGlow;

mat2 rot(float a){ float c = cos(a), s = sin(a); return mat2(c, -s, s, c); }

float sdf(vec3 p){
  p.xz *= rot(t * 0.22);
  p.xy *= rot(sin(t * 0.13) * 0.5);
  p *= vec3(0.86, 1.12, 1.0);                       // slightly wide, like a lens
  float a = 0.15 + lv * 0.26;
  float d = length(p) - 1.0;
  d += a * sin(p.x * 2.1 + t * 0.9) * sin(p.y * 2.4 - t * 0.7) * sin(p.z * 2.2 + t * 0.8);
  d += a * 0.55 * sin(p.x * 3.9 - t * 1.3 + p.y * 2.6) * sin(p.z * 3.4 + t * 1.1);
  d += lv * 0.08 * sin(p.y * 9.0 + t * 6.0);         // fine ripples while someone talks
  return d * 0.42;
}

vec3 normalAt(vec3 p){
  vec2 e = vec2(0.003, 0.0);
  return normalize(vec3(sdf(p + e.xyy) - sdf(p - e.xyy), sdf(p + e.yxy) - sdf(p - e.yxy), sdf(p + e.yyx) - sdf(p - e.yyx)));
}

void main(){
  vec2 uv = (gl_FragCoord.xy - 0.5 * r) / min(r.x, r.y);
  vec3 ro = vec3(0.0, 0.0, 4.4);
  vec3 rd = normalize(vec3(uv, -1.55));

  float dist = 0.0, minD = 10.0;
  bool hit = false;
  vec3 p = ro;
  for (int i = 0; i < 110; i++){
    p = ro + rd * dist;
    float d = sdf(p);
    minD = min(minD, d);
    if (d < 0.0015){ hit = true; break; }
    dist += d;
    if (dist > 8.0) break;
  }

  // soft halo around the shape
  float halo = exp(-max(minD, 0.0) * 6.0) * (0.38 + lv * 0.3) * smoothstep(0.62, 0.25, length(uv));
  vec4 outc = vec4(cGlow * halo, halo);

  if (hit){
    vec3 n = normalAt(p);
    float facing = max(dot(n, -rd), 0.0);
    float fres = pow(1.0 - facing, 2.0);
    vec3 L = normalize(vec3(-0.55, 0.7, 0.55));
    float ndl = dot(n, L);
    float wrap = clamp((ndl + 0.45) / 1.45, 0.0, 1.0);          // light wraps into the shadow side (subsurface feel)
    vec3 H = normalize(L - rd);
    float spec = pow(max(dot(n, H), 0.0), 70.0);                // tight highlight
    float sheen = pow(max(dot(n, H), 0.0), 8.0);                // broad soft sheen

    // iridescence: hue drifts with view angle + surface direction + time
    float k = fres * 1.6 + dot(n, vec3(0.35, 0.6, -0.2)) * 0.9 + t * 0.06;
    float w1 = 0.5 + 0.5 * cos(6.2832 * k);
    float w2 = 0.5 + 0.5 * cos(6.2832 * (k + 0.37));
    vec3 shimmer = mix(cBand, cIris, w1);
    vec3 col = mix(cBody, shimmer, 0.3 + 0.5 * w2 * smoothstep(0.0, 0.6, fres + 0.15));

    // depth: deep core where the surface faces you, darker on the unlit side
    col = mix(col, cCore, smoothstep(0.7, 1.0, facing) * (0.3 + 0.3 * (1.0 - wrap)));
    col *= 0.78 + 0.42 * wrap;

    // light: emissive rim + sheen + highlight
    col += cRim * pow(fres, 1.9) * 1.2;
    col += shimmer * sheen * 0.22;
    col += vec3(1.0) * spec * 0.55;
    col += lv * 0.06 * cRim;

    col = col / (1.0 + col * 0.18);                             // soft tone map keeps highlights from clipping flat
    float l = dot(col, vec3(0.299, 0.587, 0.114));
    col = mix(vec3(l), col, sat);
    float alpha = 1.0 - pow(fres, 6.0) * 0.55;                  // feathered edge
    outc = vec4(col * alpha, alpha) + outc * (1.0 - alpha);
  }
  float grain = (fract(sin(dot(gl_FragCoord.xy + t, vec2(12.9898, 78.233))) * 43758.5453) - 0.5) * 0.04;
  outc.rgb += grain * outc.a;
  gl_FragColor = outc;
}`

const MOOD = {
  rest: { speed: 0.35, sat: 0.55 },
  idle: { speed: 0.55, sat: 0.95 },
  listening: { speed: 0.8, sat: 1.0 },
  speaking: { speed: 1.0, sat: 1.12 },
} as const

/**
 * Floating 3D fluid shape (raymarched). Idles slowly; `getLevel()` (0..1 voice volume)
 * pushes the motion forward in bursts and deepens the deformation — it moves with speech.
 */
export function FluidBlob({ getLevel, mood, palette = 'bloom' }: { getLevel: () => number; mood: BlobMood; palette?: BlobPalette }) {
  const canvas = useRef<HTMLCanvasElement>(null)
  const moodRef = useRef(mood)
  moodRef.current = mood
  const levelFn = useRef(getLevel)
  levelFn.current = getLevel

  useEffect(() => {
    const c = canvas.current!
    const gl = c.getContext('webgl', { antialias: false, premultipliedAlpha: true, alpha: true })
    if (!gl) return
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
    const pal = PALETTES[palette]
    gl.uniform3fv(U('cCore'), pal.core)
    gl.uniform3fv(U('cBody'), pal.body)
    gl.uniform3fv(U('cRim'), pal.rim)
    gl.uniform3fv(U('cBand'), pal.band)
    gl.uniform3fv(U('cIris'), pal.iris)
    gl.uniform3fv(U('cGlow'), pal.glow)
    gl.clearColor(0, 0, 0, 0)

    const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches
    const resize = () => {
      const scale = Math.min(window.devicePixelRatio || 1, 2) * 0.6
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
    let phase = Math.random() * 20
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
      level += (raw - level) * (raw > level ? 0.35 : 0.07) // fast attack, slow release → syllable pulses
      const m = MOOD[moodRef.current]
      sat += (m.sat - sat) * 0.04
      phase += dt * (reduce ? 0.15 : m.speed + level * 4)
      gl.uniform1f(uT, phase)
      gl.uniform1f(uLv, level)
      gl.uniform1f(uSat, sat)
      gl.clear(gl.COLOR_BUFFER_BIT)
      gl.drawArrays(gl.TRIANGLES, 0, 3)
      parent?.style.setProperty('--level', level.toFixed(3))
      raf = requestAnimationFrame(frame)
    }
    raf = requestAnimationFrame(frame)
    c.classList.add('is-on')
    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
    }
  }, [palette])

  return <canvas ref={canvas} className="fluid__canvas" aria-hidden="true" />
}
