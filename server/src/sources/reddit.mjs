// Reddit: a user's public posts + comments, summarized by subreddit.
// Uses app-only OAuth when REDDIT_CLIENT_ID/SECRET are set (Reddit blocks most anonymous requests).

const UA = () => process.env.REDDIT_USER_AGENT || 'wingman-hackathon/0.1'

let token = null // { value, expires }

async function getToken() {
  const id = process.env.REDDIT_CLIENT_ID
  const secret = process.env.REDDIT_CLIENT_SECRET
  if (!id || !secret) return null
  if (token && token.expires > Date.now() + 60_000) return token.value
  const res = await fetch('https://www.reddit.com/api/v1/access_token', {
    method: 'POST',
    headers: {
      Authorization: 'Basic ' + Buffer.from(`${id}:${secret}`).toString('base64'),
      'Content-Type': 'application/x-www-form-urlencoded',
      'User-Agent': UA(),
    },
    body: 'grant_type=client_credentials',
    signal: AbortSignal.timeout(6000),
  })
  if (!res.ok) throw new Error(`reddit auth ${res.status}`)
  const j = await res.json()
  token = { value: j.access_token, expires: Date.now() + j.expires_in * 1000 }
  return token.value
}

async function listing(user, kind, timeoutMs) {
  const t = await getToken()
  const base = t ? 'https://oauth.reddit.com' : 'https://www.reddit.com'
  const suffix = t ? '' : '.json'
  const res = await fetch(`${base}/user/${user}/${kind}${suffix}?limit=50&raw_json=1`, {
    headers: { 'User-Agent': UA(), ...(t ? { Authorization: `Bearer ${t}` } : {}) },
    signal: AbortSignal.timeout(timeoutMs),
  })
  if (res.status === 404) throw new Error('user not found')
  if (!res.ok) throw new Error(`reddit ${res.status}${t ? '' : ' (set REDDIT_CLIENT_ID/SECRET)'}`)
  const j = await res.json()
  return (j?.data?.children ?? []).map((c) => c.data)
}

/** @returns {Promise<{ username, topSubreddits: Array<{name,count}>, posts: string[], comments: string[] }>} */
export async function fetchReddit(username, { timeoutMs = 6000 } = {}) {
  const user = String(username).trim().replace(/^u\//, '').replace(/[^a-zA-Z0-9_-]/g, '')
  if (!user) throw new Error('empty username')
  const [posts, comments] = await Promise.all([
    listing(user, 'submitted', timeoutMs).catch(() => []),
    listing(user, 'comments', timeoutMs),
  ])
  const nsfwFree = (x) => !x.over_18
  const counts = new Map()
  for (const x of [...posts, ...comments].filter(nsfwFree)) {
    const s = x.subreddit
    if (s && !String(s).startsWith('u_')) counts.set(s, (counts.get(s) || 0) + 1)
  }
  const topSubreddits = [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12)
    .map(([name, count]) => ({ name, count }))
  if (!topSubreddits.length) throw new Error('no public activity')
  return {
    username: user,
    topSubreddits,
    posts: posts.filter(nsfwFree).slice(0, 15).map((p) => `[r/${p.subreddit}] ${p.title}`.slice(0, 200)),
    comments: comments.filter(nsfwFree).slice(0, 20).map((c) => `[r/${c.subreddit}] ${String(c.body).replace(/\s+/g, ' ')}`.slice(0, 240)),
  }
}

export function redditToText(d) {
  return [
    `REDDIT (u/${d.username}):`,
    `Most active subreddits: ${d.topSubreddits.map((s) => `r/${s.name} (${s.count})`).join(', ')}`,
    d.posts.length ? `Recent post titles:\n${d.posts.map((p) => `- ${p}`).join('\n')}` : '',
    d.comments.length ? `Recent comments:\n${d.comments.map((c) => `- ${c}`).join('\n')}` : '',
  ]
    .filter(Boolean)
    .join('\n')
}

// `npm run try:reddit -- <username>`
if (import.meta.url === `file://${process.argv[1]}`) {
  const u = process.argv[2] || 'spez'
  fetchReddit(u)
    .then((d) => console.log(redditToText(d)))
    .catch((e) => console.error('failed:', e.message))
}
