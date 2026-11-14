// Profile Agent + Match Agent on Gemini. Prompts mirror docs/prompts/*.md.
import { GoogleGenAI } from '@google/genai'

let client = null
const ai = () => {
  if (!process.env.GEMINI_API_KEY) throw new Error('GEMINI_API_KEY is not set (see server/.env.example)')
  client ??= new GoogleGenAI({ apiKey: process.env.GEMINI_API_KEY })
  return client
}
const MODEL = () => process.env.GEMINI_MODEL || 'gemini-2.5-flash'

const PROFILE_SYSTEM = `You are Wingman's Profile Agent. Wingman is an in-person dating experience that matches people on their real taste instead of photos or generic bios.

You receive what ONE person chose to share for tonight's event: Letterboxd films with ratings and review snippets, Reddit subreddits/posts/comments, screenshots of their TikTok or Instagram Favorites/Liked/Saved/Following tabs, and a few quick fields.

Your job is to find the TASTE CORE: the patterns underneath what they love — not a list of what they love.

How to think:
1. List concrete items from every source (titles, subreddits, creators, recurring content types in screenshots). What someone writes about a film says more than the rating.
2. Look ACROSS sources for what those items share: themes, emotional tone, pace, humor style, values, how they spend energy. A pattern in two different sources is much stronger than one repeated within a source.
3. Write 2-3 "theme" lines: the recurring feelings or ideas in what they love.
4. Write 1-2 "drawn_to" lines: the kind of person their taste suggests they'd click with — personality, values, humor, energy — inferred from the characters, creators and communities they gravitate to.
5. Pick 3-6 "highlights": the most specific, distinctive concrete items (prefer niche over mainstream).

Rules:
- Every theme and drawn_to line must cite at least 2 concrete items in "because". If you can't cite two, don't write the line.
- Specific and warm, second person, under 14 words per line. Bad: "You like movies and art." Good: "Bittersweet stories about timing and the people we almost had."
- IGNORE APPEARANCE COMPLETELY. Screenshots may contain faces or bodies — never describe, rate or use anyone's looks. drawn_to is never about looks, body type, age, race, ethnicity or any protected trait.
- Do not infer religion, politics, sexuality, health or other sensitive traits unless the person explicitly states it as something they care about.
- Summarize; never quote private-seeming content verbatim.
- Return ONLY JSON matching the schema you are given.`

const PROFILE_SCHEMA = `{
  "core": [ { "id": "c1", "kind": "theme" | "drawn_to", "text": string, "because": [string, string, ...] } ],
  "highlights": [ { "id": "h1", "source": "letterboxd" | "reddit" | "tiktok" | "instagram" | "spotify" | "voice", "text": string } ],
  "taste": { "films": [string], "communities": [string], "music": [string], "aesthetics": [string], "humor": string },
  "core_values": [string],
  "relationship_intent": "serious" | "open" | "friends",
  "dealbreakers": [string]
}`

const MATCH_SYSTEM = `You are Wingman's Match Agent. Decide whether two people at tonight's event should meet, and if so, explain why in a way that feels specific and true to both of them.

Hard rules (any failure -> "compatible": false):
- relationship_intent must be compatible (serious<->serious or open; friends<->friends or open; open<->anything).
- Neither person's dealbreaker may conflict with anything in the other's profile.

What makes a good match (priority order):
1. Core overlap — their theme lines point at the same underlying feeling, even through different titles.
2. Mutual type fit — A's core and highlights fit B's drawn_to, AND B's fit A's drawn_to. Report each direction honestly.
3. Specific shared items — same film, subreddit, creator or niche hobby. Prefer rare overlaps over mainstream ones. If there is no exact shared item, it's fine to have fewer shared_specifics — never invent one.

Writing:
- core_overlap: 1-2 lines, each under 12 words, second person plural ("You're both...").
- shared_specifics: up to 3, each tied to a source, each true for BOTH people.
- reasons_for_each: written TO that person ABOUT the other (use the other's first name); lead with the core, back it with one concrete item; max 30 words.
- opener_for_each: one question that person can ask the other (use the other's first name), anchored on a specific shared item or theme. Curious, never cheesy.
- evidence: short strings like "A · Letterboxd: Past Lives ★★★★★".
- Never mention appearance. Never reveal raw posts or screenshots — only overlaps. No scores or percentages.
- Return ONLY JSON matching the schema you are given.`

const MATCH_SCHEMA = `{
  "compatible": boolean,
  "core_overlap": [string],
  "type_fit": { "a_fits_b": boolean, "b_fits_a": boolean },
  "shared_specifics": [ { "source": "letterboxd" | "reddit" | "tiktok" | "instagram" | "spotify" | "voice", "text": string } ],
  "shared_values": [string],
  "reasons_for_each": { "A": string, "B": string },
  "evidence": [string],
  "uncertainty": "low" | "medium" | "high",
  "opener_for_each": { "A": string, "B": string }
}`

function parseJson(text) {
  const t = String(text || '').trim().replace(/^```(?:json)?\s*/i, '').replace(/```$/, '')
  return JSON.parse(t)
}

async function generateJson({ system, parts, retries = 1 }) {
  let lastErr
  for (let i = 0; i <= retries; i++) {
    try {
      const res = await ai().models.generateContent({
        model: MODEL(),
        contents: [{ role: 'user', parts }],
        config: { systemInstruction: system, responseMimeType: 'application/json', temperature: 0.6 },
      })
      return parseJson(res.text)
    } catch (e) {
      lastErr = e
    }
  }
  throw lastErr
}

const dataUrlToPart = (url) => {
  const m = /^data:(image\/[a-z+]+);base64,(.+)$/i.exec(url)
  return m ? { inlineData: { mimeType: m[1], data: m[2] } } : null
}

/**
 * @param {object} p join payload
 * @param {string[]} sourceTexts already-fetched text blocks (Letterboxd, Reddit…)
 */
export async function runProfileAgent(p, sourceTexts) {
  const parts = [
    {
      text: [
        `Person: ${p.name}`,
        `Looking for: ${p.looking_for}`,
        `Dealbreaker: ${p.dealbreaker}`,
        p.about ? `About (their words): ${p.about}` : '',
        p.transcript ? `Voice intro transcript: ${p.transcript}` : '',
        '',
        ...sourceTexts,
      ]
        .filter((x) => x !== '')
        .join('\n'),
    },
  ]
  for (const [src, label] of [
    ['tiktok', 'TIKTOK screenshots (Favorites / Liked / For You):'],
    ['instagram', 'INSTAGRAM screenshots (Saved / Following / Explore):'],
  ]) {
    const shots = p.sources?.[src]?.screenshots ?? []
    if (!shots.length) continue
    parts.push({ text: label })
    for (const s of shots.slice(0, 4)) {
      const part = dataUrlToPart(s)
      if (part) parts.push(part)
    }
  }
  parts.push({ text: `Return JSON with this exact shape:\n${PROFILE_SCHEMA}` })

  const out = await generateJson({ system: PROFILE_SYSTEM, parts })
  // normalize ids + defaults
  out.core = (out.core ?? []).map((c, i) => ({ id: `c${i + 1}`, kind: c.kind === 'drawn_to' ? 'drawn_to' : 'theme', text: String(c.text), because: (c.because ?? []).map(String).slice(0, 4) }))
  out.highlights = (out.highlights ?? []).map((h, i) => ({ id: `h${i + 1}`, source: h.source, text: String(h.text) }))
  out.relationship_intent ??= p.looking_for
  return out
}

/** @param {{name:string, profile:object}} A @param {{name:string, profile:object}} B */
export async function runMatchAgent(A, B) {
  const slim = (x) => ({
    name: x.name,
    core: x.profile.core.map(({ kind, text, because }) => ({ kind, text, because })),
    highlights: x.profile.highlights.map(({ source, text }) => ({ source, text })),
    taste: x.profile.taste,
    core_values: x.profile.core_values,
    relationship_intent: x.profile.relationship_intent,
    dealbreakers: x.profile.dealbreakers,
  })
  const parts = [
    { text: `PERSON A:\n${JSON.stringify(slim(A), null, 1)}\n\nPERSON B:\n${JSON.stringify(slim(B), null, 1)}` },
    { text: `Return JSON with this exact shape:\n${MATCH_SCHEMA}` },
  ]
  const out = await generateJson({ system: MATCH_SYSTEM, parts })
  out.core_overlap ??= []
  out.shared_specifics ??= []
  out.shared_values ??= []
  out.evidence ??= []
  out.type_fit ??= { a_fits_b: false, b_fits_a: false }
  return out
}

const FOLLOW_SYSTEM = `Suggest ONE concrete second-date idea for two people based only on what they share. One sentence, under 25 words, warm and specific (a film screening, a climbing gym, a ceramics drop-in…). No appearance, no clichés. Return JSON: {"idea": string}`

export async function runSecondDateIdea(match) {
  const out = await generateJson({
    system: FOLLOW_SYSTEM,
    parts: [{ text: JSON.stringify({ core_overlap: match.core_overlap, shared_specifics: match.shared_specifics }) }],
  })
  return String(out.idea || '')
}
