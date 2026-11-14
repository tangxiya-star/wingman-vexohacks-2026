// taste-profile: fetch every connected source in parallel → Profile Agent finds the Taste Core.
import { createStep, createWorkflow } from '@mastra/core/workflows'
import { z } from 'zod'
import { getLetterboxd, getReddit } from '../tools/sources.js'
import { fetchVoiceTranscript, voiceToText } from '../../voice/agent.mjs'
import { profileSchema } from '../schemas.js'
import { profileAgent } from '../agents/index.js'
import { cannedProfile, rawHighlights } from '../../ai/canned.mjs'

const person = z.object({
  name: z.string(),
  looking_for: z.enum(['serious', 'open', 'friends']),
  dealbreaker: z.string(),
  about: z.string().optional(),
  transcript: z.string().optional(),
  sources: z.record(z.string(), z.any()).default({}),
})

const fetched = z.object({
  person,
  texts: z.array(z.string()),
  failed: z.array(z.string()),
  raw: z.record(z.string(), z.any()),
})

const fetchSources = createStep({
  id: 'fetch-sources',
  description: 'Fetch Letterboxd / Reddit in parallel; screenshots pass through for the vision step.',
  inputSchema: person,
  outputSchema: fetched,
  execute: async ({ inputData: p }) => {
    const jobs = []
    if (p.sources.letterboxd?.username) jobs.push(['letterboxd', getLetterboxd(p.sources.letterboxd.username)])
    if (p.sources.reddit?.username) jobs.push(['reddit', getReddit(p.sources.reddit.username)])
    const results = await Promise.all(jobs.map(([, j]) => j))
    const texts = []
    const failed = []
    const raw = {}
    results.forEach((r, i) => {
      const id = jobs[i][0]
      if (r.ok) {
        texts.push(r.text)
        raw[id] = r.raw
      } else failed.push(id)
    })
    const voice = p.sources.voice
    if (voice && (voice.conversation_id || voice.transcript?.length)) {
      let turns = voice.transcript ?? []
      if (voice.conversation_id && process.env.ELEVENLABS_API_KEY) {
        try {
          const server = await fetchVoiceTranscript(voice.conversation_id)
          if (server.length) turns = server
        } catch {
          /* keep the transcript the phone collected */
        }
      }
      if (turns.some((t) => t.role === 'user' && t.text?.trim())) {
        texts.push(voiceToText(turns))
        raw.voice = turns
      } else failed.push('voice')
    }
    if (p.sources.spotify) failed.push('spotify') // P1
    return { person: p, texts, failed, raw }
  },
})

const SHOT_LABELS = {
  tiktok: 'TIKTOK screenshots (Favorites / Liked / For You):',
  instagram: 'INSTAGRAM screenshots (Saved / Following / Explore):',
  gallery: 'CAMERA ROLL photos (everyday life; faces already blurred):',
}

function buildMessage(p, texts) {
  const content = [
    {
      type: 'text',
      text: [
        `Person: ${p.name}`,
        `Looking for: ${p.looking_for}`,
        `Dealbreaker: ${p.dealbreaker}`,
        p.about && `About (their words): ${p.about}`,
        p.transcript && `Voice intro transcript: ${p.transcript}`,
        '',
        ...texts,
      ]
        .filter((x) => x !== undefined && x !== false)
        .join('\n'),
    },
  ]
  for (const [src, label] of Object.entries(SHOT_LABELS)) {
    const shots = p.sources[src]?.screenshots ?? []
    if (!shots.length) continue
    content.push({ type: 'text', text: label })
    for (const s of shots.slice(0, src === 'gallery' ? 20 : 4)) {
      const m = /^data:(image\/[a-z+]+);base64,/i.exec(s)
      if (m) content.push({ type: 'image', image: s, mimeType: m[1] })
    }
  }
  return [{ role: 'user', content }]
}

const tasteCore = createStep({
  id: 'taste-core',
  description: 'Profile Agent (Gemini, multimodal) finds themes + who they are drawn to, with evidence.',
  inputSchema: fetched,
  outputSchema: z.object({ profile: z.any(), failed: z.array(z.string()), error: z.string().optional() }),
  execute: async ({ inputData: { person: p, texts, failed, raw } }) => {
    const hasShots = Object.keys(SHOT_LABELS).some((k) => p.sources[k]?.screenshots?.length)
    const fallback = (error) => ({
      profile: { core: [], highlights: rawHighlights(raw), taste: {}, stated_type: null, says_vs_shows: null, core_values: [], relationship_intent: p.looking_for, dealbreakers: [p.dealbreaker] },
      failed,
      error,
    })

    if (process.env.MOCK_AI) return { profile: cannedProfile(p), failed }
    if (!texts.length && !hasShots) return fallback("We couldn't read any of your sources. Check the usernames, or add screenshots.")

    try {
      const res = await profileAgent.generate(buildMessage(p, texts), {
        structuredOutput: { schema: profileSchema, jsonPromptInjection: true },
        modelSettings: { temperature: 0.6 },
      })
      const out = res.object
      out.core = out.core.map((c, i) => ({ id: `c${i + 1}`, ...c, because: c.because.slice(0, 4) }))
      out.highlights = out.highlights.map((h, i) => ({ id: `h${i + 1}`, ...h }))
      return { profile: out, failed }
    } catch (e) {
      return fallback(`AI profile failed: ${e.message.replace(/\.$/, "")}. Showing raw data only.`)
    }
  },
})

export const tasteProfileWorkflow = createWorkflow({
  id: 'taste-profile',
  description: "Fetch a person's sources, then find their Taste Core.",
  inputSchema: person,
  outputSchema: z.object({ profile: z.any(), failed: z.array(z.string()), error: z.string().optional() }),
})
  .then(fetchSources)
  .then(tasteCore)
  .commit()
