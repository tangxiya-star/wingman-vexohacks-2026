import { httpBase } from '../ws'

/**
 * Wingman's spoken chat lines. Plays ElevenLabs audio (server /tts, or a given mp3 url) one after another
 * through an analyser, so the fluid shape can move with the voice. Falls back to browser speech.
 */
type Job = { text?: string; url?: string | null; soft?: boolean }

let ctx: AudioContext | null = null
let analyser: AnalyserNode | null = null
let buf: Uint8Array<ArrayBuffer> | null = null
let current: HTMLAudioElement | null = null
let queue: Job[] = []
let busy = false
let enabled = true
let ttsAvailable = true
let fallbackLevel = 0
const listeners = new Set<() => void>()

const emit = () => listeners.forEach((f) => f())
export const onSpeechChange = (f: () => void) => (listeners.add(f), () => void listeners.delete(f))
export const isSpeaking = () => busy
export const soundOn = () => enabled

export function setSound(on: boolean) {
  enabled = on
  if (!on) stopSpeech()
  emit()
}

/** Call from a user gesture once, so later playback isn't blocked by autoplay rules. */
export function unlockAudio() {
  try {
    ctx ??= new AudioContext()
    if (ctx.state === 'suspended') void ctx.resume()
  } catch {}
}

/** soft: quieter, like leaning in to whisper */
export function speakLine(text: string, opts: { soft?: boolean } = {}) {
  if (!enabled || !text.trim()) return
  queue.push({ text, soft: opts.soft })
  void pump()
}

export function playUrl(url: string | null, text: string) {
  if (!enabled) return
  queue.push({ url, text })
  void pump()
}

export function stopSpeech() {
  queue = []
  current?.pause()
  current = null
  if ('speechSynthesis' in window) window.speechSynthesis.cancel()
  busy = false
  fallbackLevel = 0
  emit()
}

/** 0..1 loudness of whatever Wingman is saying right now. */
export function speechLevel() {
  if (!busy) return 0
  if (analyser && buf && current) {
    analyser.getByteTimeDomainData(buf)
    let sum = 0
    for (let i = 0; i < buf.length; i++) {
      const v = (buf[i] - 128) / 128
      sum += v * v
    }
    return Math.min(1, Math.sqrt(sum / buf.length) * 3)
  }
  return fallbackLevel
}

async function pump() {
  if (busy) return
  const job = queue.shift()
  if (!job) return
  busy = true
  emit()
  try {
    const src = job.url ?? (job.text ? await ttsUrl(job.text) : null)
    if (src) await playAudio(src, job.soft ? 0.55 : 1)
    else if (job.text) await browserSpeak(job.text)
  } catch {
    if (job.text) await browserSpeak(job.text).catch(() => {})
  }
  busy = false
  current = null
  emit()
  void pump()
}

const urlCache = new Map<string, string>()
async function ttsUrl(text: string): Promise<string | null> {
  if (!ttsAvailable) return null
  const hit = urlCache.get(text)
  if (hit) return hit
  const res = await fetch(`${httpBase()}/tts`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ text }) })
  if (res.status === 503) {
    ttsAvailable = false
    return null
  }
  if (!res.ok) throw new Error('tts failed')
  const url = URL.createObjectURL(await res.blob())
  urlCache.set(text, url)
  return url
}

function playAudio(src: string, volume = 1) {
  return new Promise<void>((resolve, reject) => {
    const a = new Audio()
    a.crossOrigin = 'anonymous'
    a.src = src
    a.volume = volume
    current = a
    try {
      ctx ??= new AudioContext()
      if (!analyser) {
        analyser = ctx.createAnalyser()
        analyser.fftSize = 512
        analyser.connect(ctx.destination)
        buf = new Uint8Array(analyser.fftSize)
      }
      ctx.createMediaElementSource(a).connect(analyser)
      if (ctx.state === 'suspended') void ctx.resume()
    } catch {}
    a.onended = () => resolve()
    a.onerror = () => reject(new Error('audio error'))
    a.play().catch(reject)
  })
}

function browserSpeak(text: string) {
  return new Promise<void>((resolve) => {
    if (!('speechSynthesis' in window)) return resolve()
    const u = new SpeechSynthesisUtterance(text)
    u.rate = 1
    u.onboundary = () => (fallbackLevel = 0.6)
    const tick = setInterval(() => (fallbackLevel *= 0.8), 60)
    u.onend = u.onerror = () => (clearInterval(tick), (fallbackLevel = 0), resolve())
    window.speechSynthesis.speak(u)
  })
}
