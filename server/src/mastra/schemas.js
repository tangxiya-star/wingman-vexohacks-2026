import { z } from 'zod'

export const sourceId = z.enum(['letterboxd', 'reddit', 'tiktok', 'instagram', 'spotify', 'voice', 'gallery'])

export const profileSchema = z.object({
  core: z
    .array(
      z.object({
        kind: z.enum(['theme', 'drawn_to']),
        text: z.string().describe('Under 14 words, second person, specific'),
        because: z.array(z.string()).describe('At least 2 concrete items from the sources'),
      }),
    )
    .describe('2-3 theme lines + 1-2 drawn_to lines'),
  highlights: z.array(z.object({ source: sourceId, text: z.string() })).describe('3-6 most specific, distinctive items'),
  taste: z.object({
    films: z.array(z.string()),
    communities: z.array(z.string()),
    music: z.array(z.string()),
    aesthetics: z.array(z.string()),
    humor: z.string(),
  }),
  stated_type: z
    .object({
      says: z.string().describe('Who they SAY they click with, from the voice chat, in one line. Empty if no voice chat.'),
      looks: z.string().nullable().describe('Looks/style they said they like, in their words. null if not mentioned. Never race/ethnicity.'),
    })
    .nullable()
    .describe('null when there is no voice chat'),
  says_vs_shows: z
    .string()
    .nullable()
    .describe('One warm, honest line comparing what they say they want vs. what their taste shows they are drawn to. null without a voice chat.'),
  core_values: z.array(z.string()),
  relationship_intent: z.enum(['serious', 'open', 'friends']),
  dealbreakers: z.array(z.string()),
})

// What two people share is read on several axes, never just one platform's taste.
export const dimension = z.enum(['taste', 'values', 'intent', 'style'])
export const overlapSource = z.enum([...sourceId.options, 'answers'])

export const matchSchema = z.object({
  compatible: z.boolean(),
  overlaps: z
    .array(
      z.object({
        dimension,
        text: z.string().describe('Under 14 words, "You both..." / "You\'re both...", concrete'),
        sources: z.array(overlapSource).describe('Where this shows up, for both people'),
      }),
    )
    .describe('2-4 lines covering at least 2 different dimensions'),
  score: z.number().int().min(0).max(100),
  core_overlap: z.array(z.string()),
  type_fit: z.object({ a_fits_b: z.boolean(), b_fits_a: z.boolean() }),
  shared_specifics: z.array(z.object({ source: sourceId, text: z.string() })),
  shared_values: z.array(z.string()),
  reasons_for_each: z.object({ A: z.string(), B: z.string() }),
  evidence: z.array(z.string()),
  uncertainty: z.enum(['low', 'medium', 'high']),
  opener_for_each: z.object({ A: z.string(), B: z.string() }),
})

export const ideaSchema = z.object({ idea: z.string() })
