// Quick check of the real pipeline without the UI:
//   npm run try:profile -- <letterboxd_user> [reddit_user]
import { fetchLetterboxd, letterboxdToText } from './sources/letterboxd.mjs'
import { fetchReddit, redditToText } from './sources/reddit.mjs'
import { runProfileAgent } from './ai/gemini.mjs'

const [lb, rd] = process.argv.slice(2)
const texts = []
if (lb) texts.push(letterboxdToText(await fetchLetterboxd(lb)))
if (rd) {
  try {
    texts.push(redditToText(await fetchReddit(rd)))
  } catch (e) {
    console.error('reddit failed:', e.message)
  }
}
if (!texts.length) {
  console.error('usage: npm run try:profile -- <letterboxd_user> [reddit_user]')
  process.exit(1)
}
const t0 = Date.now()
const out = await runProfileAgent({ name: 'Test', looking_for: 'serious', dealbreaker: 'Dishonesty', sources: {} }, texts)
console.log(JSON.stringify({ core: out.core, highlights: out.highlights }, null, 2))
console.log(`(${Date.now() - t0}ms)`)
