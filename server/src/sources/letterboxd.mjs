// Letterboxd: public RSS feed of a member's recent diary entries / reviews.
// https://letterboxd.com/<username>/rss/
import { XMLParser } from 'fast-xml-parser'

const parser = new XMLParser({ ignoreAttributes: true, cdataPropName: false })

const NAMED = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ' }
const decode = (s = '') =>
  String(s).replace(/&(#x[0-9a-f]+|#\d+|[a-z]+);/gi, (m, e) =>
    e[0] === '#' ? String.fromCodePoint(e[1].toLowerCase() === 'x' ? parseInt(e.slice(2), 16) : Number(e.slice(1))) : NAMED[e.toLowerCase()] ?? m,
  )

const stripHtml = (html = '') =>
  decode(String(html))
    .replace(/<img[^>]*>/g, '')
    .replace(/<[^>]+>/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()

const stars = (r) => {
  if (r == null || r === '') return ''
  const n = Number(r)
  return '★'.repeat(Math.floor(n)) + (n % 1 ? '½' : '')
}

/** @returns {Promise<{ username: string, films: Array<{title, year, rating, liked, review}> }>} */
export async function fetchLetterboxd(username, { timeoutMs = 6000 } = {}) {
  const user = String(username).trim().replace(/^@/, '').replace(/[^a-zA-Z0-9_]/g, '')
  if (!user) throw new Error('empty username')
  const res = await fetch(`https://letterboxd.com/${user}/rss/`, {
    headers: { 'User-Agent': 'Mozilla/5.0 (Wingman hackathon prototype)' },
    signal: AbortSignal.timeout(timeoutMs),
  })
  if (!res.ok) throw new Error(`letterboxd ${res.status}`)
  const xml = await res.text()
  const doc = parser.parse(xml)
  let items = doc?.rss?.channel?.item ?? []
  if (!Array.isArray(items)) items = [items]

  const films = items
    .filter((it) => it['letterboxd:filmTitle'])
    .slice(0, 40)
    .map((it) => {
      const review = stripHtml(it.description).replace(/^Watched on [^.]+\.\s*/, '')
      return {
        title: decode(it['letterboxd:filmTitle']),
        year: it['letterboxd:filmYear'] ? Number(it['letterboxd:filmYear']) : undefined,
        rating: it['letterboxd:memberRating'] != null ? Number(it['letterboxd:memberRating']) : null,
        liked: it['letterboxd:memberLike'] === 'Yes',
        review: review.slice(0, 400),
      }
    })

  if (!films.length) throw new Error('no public diary entries')
  return { username: user, films }
}

/** Compact text block for the Profile Agent. */
export function letterboxdToText(data) {
  const lines = data.films.map((f) => {
    const r = f.rating != null ? ` ${stars(f.rating)}` : ''
    const like = f.liked ? ' ♥' : ''
    const rev = f.review ? ` — "${f.review}"` : ''
    return `- ${f.title}${f.year ? ` (${f.year})` : ''}${r}${like}${rev}`
  })
  return `LETTERBOXD (@${data.username}, ${data.films.length} recent entries):\n${lines.join('\n')}`
}

// `npm run try:letterboxd -- <username>`
if (import.meta.url === `file://${process.argv[1]}`) {
  const u = process.argv[2] || 'dave'
  fetchLetterboxd(u)
    .then((d) => console.log(letterboxdToText(d)))
    .catch((e) => console.error('failed:', e.message))
}
