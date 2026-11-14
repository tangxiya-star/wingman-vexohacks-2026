import { Agent } from '@mastra/core/agent'
import { PROFILE_SYSTEM, MATCH_SYSTEM, FOLLOW_SYSTEM } from '../../ai/prompts.mjs'
import { letterboxdTool, redditTool } from '../tools/sources.js'

export const MODEL = `google/${process.env.GEMINI_MODEL || 'gemini-2.5-flash'}`

/**
 * Reads everything one person shared and finds their Taste Core.
 * Has the source tools so it can also be used on its own (e.g. in Mastra Studio:
 * "Find the taste core of Letterboxd user davidehrlich").
 */
export const profileAgent = new Agent({
  id: 'profile-agent',
  name: 'Profile Agent',
  description: "Finds a person's Taste Core from their Letterboxd, Reddit and TikTok/Instagram/gallery screenshots.",
  instructions:
    PROFILE_SYSTEM +
    '\n\nIf source data is already included in the message, use it directly. Only call a tool when you are given a username without its data.',
  model: MODEL,
  tools: { letterboxdTool, redditTool },
})

/** Compares two Taste Cores and decides whether they should meet. */
export const matchAgent = new Agent({
  id: 'match-agent',
  name: 'Match Agent',
  description: 'Decides whether two profiles should meet, with core overlap, mutual type fit, shared specifics and openers.',
  instructions: MATCH_SYSTEM,
  model: MODEL,
})

/** One concrete second-date idea from what a pair shares. */
export const dateIdeaAgent = new Agent({
  id: 'date-idea-agent',
  name: 'Second Date Agent',
  description: 'Suggests one specific second-date idea from a match.',
  instructions: FOLLOW_SYSTEM,
  model: MODEL,
})
