// Fallbacks: used when MOCK_AI=1, and to build real-data-only highlights when Gemini fails.

/** Deterministic highlights from fetched raw data (no AI). */
export function rawHighlights(raw) {
  const out = []
  if (raw.letterboxd) {
    const loved = raw.letterboxd.films.filter((f) => (f.rating ?? 0) >= 4 || f.liked).slice(0, 4)
    if (loved.length) out.push({ source: 'letterboxd', text: `Loved: ${loved.map((f) => f.title).join(', ')}` })
  }
  if (raw.reddit) {
    out.push({ source: 'reddit', text: `Active in ${raw.reddit.topSubreddits.slice(0, 4).map((s) => `r/${s.name}`).join(', ')}` })
  }
  return out.map((h, i) => ({ id: `h${i + 1}`, ...h }))
}

export function cannedProfile(p) {
  const has = (k) => !!p.sources?.[k]
  return {
    core: [
      { id: 'c1', kind: 'theme', text: 'Bittersweet stories about timing and the people we almost had', because: ['Past Lives ★★★★★', 'Aftersun ★★★★★'] },
      { id: 'c2', kind: 'theme', text: 'Slow, hands-on crafts where progress is quiet', because: [has('tiktok') ? 'ceramics TikToks' : 'Perfect Days', 'r/bouldering'] },
      { id: 'c3', kind: 'drawn_to', text: 'Quiet, observant people with a dry sense of humor', because: ['Perfect Days', 'deadpan comedy TikToks'] },
    ],
    highlights: [
      { id: 'h1', source: 'letterboxd', text: '5★ Past Lives, Aftersun, Perfect Days' },
      { id: 'h2', source: 'reddit', text: 'Regular on r/bouldering and r/Letterboxd' },
    ],
    taste: { films: ['Past Lives', 'Aftersun'], communities: ['r/bouldering'], music: [], aesthetics: [], humor: 'deadpan' },
    stated_type: has('voice') ? { says: 'Someone spontaneous who always has a plan for the weekend', looks: null } : null,
    says_vs_shows: has('voice') ? 'You say you want someone spontaneous, but your taste keeps choosing quiet, observant people.' : null,
    core_values: [],
    relationship_intent: p.looking_for,
    dealbreakers: [p.dealbreaker],
  }
}

export function cannedMatch(A, B) {
  return {
    compatible: true,
    score: 87,
    overlaps: [
      { dimension: 'taste', text: 'You both gave Past Lives five stars', sources: ['letterboxd'] },
      { dimension: 'values', text: 'You both reward honesty over polish in what you love', sources: ['letterboxd', 'answers'] },
      { dimension: 'style', text: 'You both like slow, hands-on things: climbing, long films', sources: ['reddit', 'letterboxd'] },
      ...(A.looking_for === B.looking_for ? [{ dimension: 'intent', text: 'You both want something real', sources: ['answers'] }] : []),
    ],
    core_overlap: ["You're both drawn to bittersweet stories about timing", 'You both love slow, hands-on crafts'],
    type_fit: { a_fits_b: true, b_fits_a: true },
    shared_specifics: [
      { source: 'letterboxd', text: 'You both gave Past Lives 5★' },
      { source: 'reddit', text: "You're both regulars on r/bouldering" },
    ],
    shared_values: A.looking_for === B.looking_for ? ['You both want something real'] : [],
    reasons_for_each: {
      A: `${B.name} loved Past Lives as much as you did and climbs most weekends.`,
      B: `${A.name} rated Past Lives 5★ too and is on r/bouldering every week.`,
    },
    evidence: [`${A.name} · Letterboxd: Past Lives ★★★★★`, `${B.name} · Letterboxd: Past Lives ★★★★★`],
    uncertainty: 'low',
    opener_for_each: {
      A: `Ask ${B.name} what they thought of the ending of Past Lives.`,
      B: `Ask ${A.name} which climbing gym they go to.`,
    },
  }
}
