// Source fetchers exposed as Mastra tools (usable by agents, steps and Studio).
import { createTool } from '@mastra/core/tools'
import { z } from 'zod'
import { fetchLetterboxd, letterboxdToText } from '../../sources/letterboxd.mjs'
import { fetchReddit, redditToText } from '../../sources/reddit.mjs'

const out = z.object({
  ok: z.boolean(),
  text: z.string().describe('Prompt-ready summary of what the person loves'),
  error: z.string().optional(),
  raw: z.any().optional(),
})

const wrap = (fetcher, toText) => async (username) => {
  try {
    const raw = await fetcher(username)
    return { ok: true, text: toText(raw), raw }
  } catch (e) {
    return { ok: false, text: '', error: e.message }
  }
}

export const getLetterboxd = wrap(fetchLetterboxd, letterboxdToText)
export const getReddit = wrap(fetchReddit, redditToText)

export const letterboxdTool = createTool({
  id: 'letterboxd-diary',
  description: "Fetch a Letterboxd member's recent public diary: films, star ratings, likes and review text.",
  inputSchema: z.object({ username: z.string().describe('Letterboxd username, without @') }),
  outputSchema: out,
  execute: async ({ username }) => getLetterboxd(username),
})

export const redditTool = createTool({
  id: 'reddit-activity',
  description: "Fetch a Reddit user's public activity: top subreddits, recent post titles and comments (NSFW removed).",
  inputSchema: z.object({ username: z.string().describe('Reddit username, without u/') }),
  outputSchema: out,
  execute: async ({ username }) => getReddit(username),
})
