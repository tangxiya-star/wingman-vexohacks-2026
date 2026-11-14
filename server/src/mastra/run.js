// What the WebSocket server calls. Everything AI goes through Mastra.
import { mastra } from './index.js'
import { matchSchema, ideaSchema } from './schemas.js'
import { cannedMatch } from '../ai/canned.mjs'

/** @returns {Promise<{profile, failed: string[], error?: string}>} */
export async function buildProfile(joinPayload) {
  const run = await mastra.getWorkflow('tasteProfileWorkflow').createRun()
  const res = await run.start({ inputData: joinPayload })
  if (res.status !== 'success') throw new Error(res.error?.message || `workflow ${res.status}`)
  return res.result
}

const slim = (name, p) => ({
  name,
  core: p.core.map(({ kind, text, because }) => ({ kind, text, because })),
  highlights: p.highlights.map(({ source, text }) => ({ source, text })),
  taste: p.taste,
  says: p.stated_type?.says || undefined,
  core_values: p.core_values,
  relationship_intent: p.relationship_intent,
  dealbreakers: p.dealbreakers,
})

/** A, B: { name, profile, join } */
export async function matchPair(A, B) {
  if (process.env.MOCK_AI) return cannedMatch(A.join, B.join)
  const res = await mastra.getAgent('matchAgent').generate(
    `PERSON A:\n${JSON.stringify(slim(A.name, A.profile), null, 1)}\n\nPERSON B:\n${JSON.stringify(slim(B.name, B.profile), null, 1)}`,
    { structuredOutput: { schema: matchSchema }, modelSettings: { temperature: 0.6 } },
  )
  return res.object
}

export async function secondDateIdea(match) {
  if (process.env.MOCK_AI) return 'Pick one thing you both love and go do it this weekend.'
  const res = await mastra
    .getAgent('dateIdeaAgent')
    .generate(JSON.stringify({ core_overlap: match.core_overlap, shared_specifics: match.shared_specifics }), {
      structuredOutput: { schema: ideaSchema },
    })
  return res.object.idea
}
