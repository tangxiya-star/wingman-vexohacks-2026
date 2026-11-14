// Run the real Mastra taste-profile workflow without the UI:
//   npm run try:profile -- <letterboxd_user> [reddit_user]
import { buildProfile } from './mastra/run.js'

const [lb, rd] = process.argv.slice(2)
if (!lb) {
  console.error('usage: npm run try:profile -- <letterboxd_user> [reddit_user]')
  process.exit(1)
}
const sources = { letterboxd: { username: lb } }
if (rd) sources.reddit = { username: rd }
const t0 = Date.now()
const { profile, failed, error } = await buildProfile({ name: 'Test', looking_for: 'serious', dealbreaker: 'Dishonesty', sources })
if (error) console.error('error:', error)
if (failed.length) console.error('failed sources:', failed.join(', '))
console.log(JSON.stringify({ core: profile.core, highlights: profile.highlights }, null, 2))
console.log(`(${Date.now() - t0}ms)`)
