// ElevenLabs conversational agent: a short voice chat before the event about who you click with.
// The transcript becomes the "voice" source for the Mastra taste-profile workflow.
const API = 'https://api.elevenlabs.io/v1/convai'
const key = () => process.env.ELEVENLABS_API_KEY
const headers = () => ({ 'xi-api-key': key(), 'Content-Type': 'application/json' })

export const voiceReady = () => !!(key() && process.env.ELEVENLABS_AGENT_ID)

export const VOICE_PROMPT = `You are Wingman, a warm, curious host at an in-person dating event. Before the event starts, you have a short voice chat (about two minutes) with one guest to understand who they really click with.

Style: relaxed, a little playful, genuinely interested. Keep every turn to one or two short sentences and ask ONE question at a time. React briefly to what they say before moving on. Never lecture, never give dating advice.

Cover these, in a natural order, skipping anything they already answered:
1. What they're hoping for tonight (something serious, open to see, or new friends).
2. A time they really clicked with someone — what made it work?
3. What kind of conversation makes them lose track of time.
4. What instantly puts them off in someone.
5. What they find attractive. If they talk about looks or style, that's fine — listen and acknowledge it lightly, but don't dig into bodies, and never ask about race, ethnicity, religion or other sensitive traits.
6. One thing they can't compromise on.

After about five or six exchanges, or when they want to stop, wrap up warmly in one sentence ("Got it — I think I know who you'd click with. Enjoy tonight.") and stop asking questions.`

export const VOICE_FIRST_MESSAGE = "Hey, I'm Wingman. Before tonight starts, tell me a bit about the kind of person you click with — what are you hoping for tonight?"

/** Creates the agent once; returns agent_id. */
export async function createVoiceAgent() {
  const body = {
    name: 'Wingman voice intro',
    conversation_config: {
      agent: {
        first_message: VOICE_FIRST_MESSAGE,
        language: process.env.ELEVENLABS_AGENT_LANGUAGE || 'en',
        prompt: { prompt: VOICE_PROMPT, ...(process.env.ELEVENLABS_AGENT_LLM ? { llm: process.env.ELEVENLABS_AGENT_LLM } : {}) },
      },
      tts: { voice_id: process.env.ELEVENLABS_VOICE_ID || 'SAz9YHcvj6GT2YYXdXww' },
      conversation: { max_duration_seconds: 240 },
    },
    platform_settings: { auth: { enable_auth: false } },
  }
  const res = await fetch(`${API}/agents/create`, { method: 'POST', headers: headers(), body: JSON.stringify(body) })
  const json = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(`elevenlabs create agent ${res.status}: ${JSON.stringify(json.detail ?? json).slice(0, 400)}`)
  return json.agent_id
}

/** Signed URL so the browser never sees our API key. Falls back to the (public) agent id. */
export async function voiceSession() {
  const agentId = process.env.ELEVENLABS_AGENT_ID
  try {
    const res = await fetch(`${API}/conversation/get-signed-url?agent_id=${encodeURIComponent(agentId)}`, { headers: headers() })
    if (res.ok) {
      const { signed_url } = await res.json()
      if (signed_url) return { signed_url }
    }
  } catch {}
  return { agent_id: agentId }
}

/** Polls until ElevenLabs has finished processing the conversation. */
export async function fetchVoiceTranscript(conversationId, { timeoutMs = 12000 } = {}) {
  const until = Date.now() + timeoutMs
  while (Date.now() < until) {
    const res = await fetch(`${API}/conversations/${encodeURIComponent(conversationId)}`, { headers: headers() })
    if (!res.ok) throw new Error(`elevenlabs conversation ${res.status}`)
    const c = await res.json()
    const turns = (c.transcript ?? []).filter((t) => t.message).map((t) => ({ role: t.role === 'agent' ? 'agent' : 'user', text: t.message }))
    if (c.status === 'done' || c.status === 'failed' || (turns.length && Date.now() + 2000 > until)) return turns
    await new Promise((r) => setTimeout(r, 1500))
  }
  throw new Error('elevenlabs transcript not ready')
}

export function voiceToText(turns) {
  const lines = turns.map((t) => `${t.role === 'agent' ? 'Wingman' : 'Them'}: ${t.text}`)
  return `VOICE CHAT with Wingman before the event (their own words — this is what they SAY they want):\n${lines.join('\n')}`
}
