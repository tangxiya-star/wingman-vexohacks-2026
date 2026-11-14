// Demo safety net: timeouts on every AI call, a disk cache of the last good results, and fallbacks built
// from the person's real data, so a live demo never stalls or ends on "no match" because of an API hiccup.
//
//   DEMO_MODE=1          use cache / fallbacks when Gemini fails or is slow, and always match the pair
//   DEMO_FAIL=profile|match|all   rehearse: pretend Gemini failed at that step
//   PROFILE_TIMEOUT_MS / MATCH_TIMEOUT_MS / IDEA_TIMEOUT_MS
import { existsSync, readFileSync, writeFileSync } from 'node:fs'

export const DEMO_MODE = /^(1|true|yes)$/i.test(process.env.DEMO_MODE || '')
export const DEMO_FAIL = (process.env.DEMO_FAIL || '').toLowerCase()
export const TIMEOUTS = {
  profile: Number(process.env.PROFILE_TIMEOUT_MS || 40_000),
  match: Number(process.env.MATCH_TIMEOUT_MS || 25_000),
  idea: Number(process.env.IDEA_TIMEOUT_MS || 8_000),
}

/** Rejects after ms, or immediately when rehearsing a failure for this step. */
export function guarded(step, promise, ms) {
  if (!DEMO_MODE) return promise // outside demo mode: no extra timeouts, no rehearsal failures
  if (DEMO_FAIL === step || DEMO_FAIL === 'all') return Promise.reject(new Error(`DEMO_FAIL=${DEMO_FAIL} (rehearsal)`))
  let timer
  const timeout = new Promise((_, rej) => (timer = setTimeout(() => rej(new Error(`${step} timed out after ${Math.round(ms / 1000)}s`)), ms)))
  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer))
}

// ---------- cache of last good results (by first name) ----------
const CACHE = new URL('../../.demo-cache.json', import.meta.url)
let cache = { profiles: {}, matches: {} }
try {
  if (existsSync(CACHE)) cache = { profiles: {}, matches: {}, ...JSON.parse(readFileSync(CACHE, 'utf8')) }
} catch {}
const save = () => {
  try {
    writeFileSync(CACHE, JSON.stringify(cache, null, 1))
  } catch (e) {
    console.warn(`demo cache not saved: ${e.message}`)
  }
}

/** Forget everything cached (run before the final rehearsal so no earlier tester leaks in). */
export function clearDemoCache() {
  cache = { profiles: {}, matches: {} }
  save()
}
const key = (name) => String(name || '').trim().toLowerCase()
const pairKey = (a, b) => [key(a), key(b)].sort().join('|')

export function rememberProfile(name, profile) {
  if (!profile?.core?.length) return
  // a copy (live state gets trimmed on confirm), and never the private looks preference
  const copy = structuredClone(profile)
  delete copy.stated_type
  cache.profiles[key(name)] = copy
  save()
}
export function cachedProfile(name) {
  const p = cache.profiles[key(name)]
  return p?.core?.length ? structuredClone(p) : null
}

export function rememberMatch(nameA, nameB, match) {
  cache.matches[pairKey(nameA, nameB)] = { a: key(nameA), match: structuredClone(match) }
  save()
}
export function cachedMatch(nameA, nameB) {
  const hit = cache.matches[pairKey(nameA, nameB)]
  if (!hit?.match?.reasons_for_each || !hit.match.type_fit) return null
  const m = structuredClone(hit.match)
  if (hit.a !== key(nameA)) {
    // stored the other way round: swap the per-person fields
    for (const f of ['reasons_for_each', 'opener_for_each']) m[f] = { A: m[f].B, B: m[f].A }
    m.type_fit = { a_fits_b: m.type_fit.b_fits_a, b_fits_a: m.type_fit.a_fits_b }
  }
  return m
}

// ---------- fallbacks from the person's own data (no AI) ----------
const INTENT = { serious: 'something real', open: 'to see where things go', friends: 'new friends' }

/** A Taste Core from what we actually have: highlights, then what they told us. Never invented. */
export function fallbackProfile(join, partial) {
  const highlights = partial?.highlights ?? []
  const core = highlights.slice(0, 3).map((h, i) => ({ id: `c${i + 1}`, kind: 'theme', text: h.text, because: [h.source] }))
  if (!core.length) core.push({ id: 'c1', kind: 'theme', text: `Here for ${INTENT[join.looking_for] ?? 'someone real'}`, because: ['voice'] })
  if (join.dealbreaker && join.dealbreaker !== 'not said')
    core.push({ id: `c${core.length + 1}`, kind: 'drawn_to', text: `Won't compromise on ${join.dealbreaker}`, because: ['voice'] })
  return {
    core,
    highlights,
    taste: partial?.taste ?? {},
    stated_type: null,
    says_vs_shows: null,
    core_values: [],
    relationship_intent: join.looking_for,
    dealbreakers: [join.dealbreaker],
  }
}

/** A match from real overlaps between the two profiles. */
export function fallbackMatch(A, B) {
  const norm = (s) => String(s).toLowerCase().trim()
  const bag = (p) => [
    ...(p.taste?.films ?? []).map((t) => [t, 'letterboxd']),
    ...(p.taste?.communities ?? []).map((t) => [t, 'reddit']),
    ...(p.taste?.music ?? []).map((t) => [t, 'voice']),
    ...(p.taste?.aesthetics ?? []).map((t) => [t, 'instagram']),
  ]
  const bNorm = new Set(bag(B.profile).map(([t]) => norm(t)))
  const seen = new Set()
  const sharedPairs = bag(A.profile).filter(([t]) => bNorm.has(norm(t)) && !seen.has(norm(t)) && seen.add(norm(t))).slice(0, 3)
  const shared = sharedPairs.map(([t]) => t)
  const sameIntent = A.join.looking_for === B.join.looking_for
  const said = (x) => x && !['not said', 'undefined', ''].includes(norm(x))
  const sameLine = said(A.join.dealbreaker) && norm(A.join.dealbreaker) === norm(B.join.dealbreaker)
  const core_overlap = [
    ...(shared.length ? [`You both keep coming back to ${shared.slice(0, 2).join(' and ')}`] : []),
    ...(sameIntent ? [`You're both here for ${INTENT[A.join.looking_for]}`] : []),
    ...(sameLine ? [`Neither of you compromises on ${A.join.dealbreaker}`] : []),
  ]
  if (!core_overlap.length) core_overlap.push('You both showed up tonight wanting to meet someone for real')
  const score = Math.min(84, 62 + shared.length * 7 + (sameIntent ? 5 : 0) + (sameLine ? 5 : 0))
  return {
    compatible: true,
    score,
    core_overlap,
    type_fit: { a_fits_b: false, b_fits_a: false },
    shared_specifics: sharedPairs.map(([t, source]) => ({ source, text: `You both like ${t}` })),
    shared_values: [],
    reasons_for_each: { A: `You and ${B.name} have more in common than you'd guess.`, B: `You and ${A.name} have more in common than you'd guess.` },
    evidence: [],
    uncertainty: 'high',
    opener_for_each: { A: '', B: '' },
  }
}
