// Mastra entry: agents + workflows. `npm run studio` opens Mastra Studio on this.
import { Mastra } from '@mastra/core/mastra'

// Mastra's google provider reads GOOGLE_GENERATIVE_AI_API_KEY; we keep GEMINI_API_KEY in .env.
if (process.env.GEMINI_API_KEY && !process.env.GOOGLE_GENERATIVE_AI_API_KEY) {
  process.env.GOOGLE_GENERATIVE_AI_API_KEY = process.env.GEMINI_API_KEY
}

const { profileAgent, matchAgent, dateIdeaAgent } = await import('./agents/index.js')
const { tasteProfileWorkflow } = await import('./workflows/taste-profile.js')

export const mastra = new Mastra({
  agents: { profileAgent, matchAgent, dateIdeaAgent },
  workflows: { tasteProfileWorkflow },
})
