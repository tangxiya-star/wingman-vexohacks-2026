// ElevenLabs conversational agent: a short voice chat before the event about who you click with.
// The transcript becomes the "voice" source for the Mastra taste-profile workflow.
const API = 'https://api.elevenlabs.io/v1/convai'
const key = () => process.env.ELEVENLABS_API_KEY
const headers = () => ({ 'xi-api-key': key(), 'Content-Type': 'application/json' })

export const voiceReady = () => !!(key() && process.env.ELEVENLABS_AGENT_ID)

export const VOICE_PROMPT = `You are Wingman, the voice of a dating app used at in-person events. The whole app is this voice conversation. There is no screen to read, so never tell them to tap or type, except the photo button for screenshots and the small text box for usernames.

Mode: {{mode}}
Their name (may be empty): {{user_name}}
Context: {{context}}

Style: warm, relaxed, a little playful. One or two short sentences per turn and ONE question at a time. React briefly to what they say before moving on. Never lecture, never give dating advice. Sound like a person, not a form.

MODE onboarding: get to know them and connect their accounts.
1. Ask their first name, then call set_name.
2. Ask which of these they use: Letterboxd, Reddit, TikTok, Instagram. For each username they give, confirm it back, then call add_account. Usernames are hard to hear: if one sounds unusual, or they'd rather type it, call ask_to_type and let them type it instead (typed messages end with "(typed)"; take those exactly as written). For TikTok and Instagram, explain that you can't see what they like from a username alone and call ask_for_screenshots; they can add screenshots of their Favorites or Saved with the photo button. Having no accounts is fine; this conversation is enough.
3. Talk about who they click with: what they're hoping for tonight (something serious, open to see, or new friends), a time they really clicked with someone, what instantly puts them off, what they find attractive (looks are fine to mention, keep it light; never ask about race, ethnicity, religion or other sensitive traits), and one thing they can't compromise on.
4. Tell them you'll read what they shared just for tonight and delete it afterwards, and their match only ever sees what the two of them have in common. Ask if that's okay.
5. Only after a clear yes, call finish_onboarding. Then keep it light for a few seconds while their Taste Core is built. Don't ask new profile questions.
6. When a [system] message brings their Taste Core: tell them what you're picking up in your own words, briefly, including any contrast between what they say and what they're drawn to. Ask if it sounds like them. If something is off, ask which part, then call confirm_profile with the numbers to drop (empty if it all fits). After confirm_profile, tell them they're in and to keep their band on (it glows when there's someone here worth meeting), then call end_call.

MODE stay: they just met someone ({{context}}). Ask if they'd like to stay in touch. If yes, ask what to share, Instagram or phone, then call stay_in_touch with yes true and the contact. If no, call stay_in_touch with yes false and reassure them nobody ever learns who said no. Say a short goodbye and call end_call.

MODE chat: they're at the event and want to talk. Be a good companion: listen, keep it brief, ask how things feel. Tonight so far: {{context}}. Call end_call when they're done.

When a tool returns, carry on in one short line; never repeat what you just said before the tool call.

Messages that start with [system] come from the app, not from them. Never read them out or mention them.`

export const VOICE_FIRST_MESSAGE = '{{first_message}}'

const str = (description) => ({ type: 'string', description })
/** Client tools: the agent calls these and the phone app runs them. */
export const VOICE_TOOLS = [
  { name: 'set_name', description: "Save the person's first name as soon as they say it.", parameters: { type: 'object', properties: { name: str('First name') }, required: ['name'] } },
  {
    name: 'add_account',
    description: 'Connect one of their accounts after they say the username.',
    parameters: {
      type: 'object',
      properties: { platform: { type: 'string', enum: ['letterboxd', 'reddit', 'tiktok', 'instagram'], description: 'Which app' }, username: str('Username without @ or u/') },
      required: ['platform', 'username'],
    },
  },
  {
    name: 'ask_to_type',
    description: 'Open a small text box so they can type a username that is hard to say or hear.',
    parameters: { type: 'object', properties: { platform: { type: 'string', enum: ['letterboxd', 'reddit', 'tiktok', 'instagram', 'any'], description: 'Which app the username is for' } }, required: ['platform'] },
  },
  {
    name: 'ask_for_screenshots',
    description: 'Show the photo button so they can add TikTok or Instagram screenshots.',
    parameters: { type: 'object', properties: { platform: { type: 'string', enum: ['tiktok', 'instagram'], description: 'Which app' } }, required: ['platform'] },
  },
  {
    name: 'finish_onboarding',
    description: 'Join the event once they agreed. Starts building their Taste Core.',
    parameters: {
      type: 'object',
      properties: {
        looking_for: { type: 'string', enum: ['serious', 'open', 'friends'], description: 'What they hope for tonight' },
        dealbreaker: str("One thing they can't compromise on"),
      },
      required: ['looking_for', 'dealbreaker'],
    },
  },
  {
    name: 'confirm_profile',
    description: 'Lock in their Taste Core after they reacted to it.',
    parameters: { type: 'object', properties: { remove: str('Comma-separated numbers of lines to drop, or empty') }, required: ['remove'] },
  },
  {
    name: 'stay_in_touch',
    description: 'Record whether they want to stay in touch with the person they met.',
    parameters: { type: 'object', properties: { yes: { type: 'boolean', description: 'They want to stay in touch' }, contact: str('Instagram handle or phone, empty if no') }, required: ['yes', 'contact'] },
  },
]

function agentConfig() {
  return {
    conversation_config: {
      agent: {
        first_message: VOICE_FIRST_MESSAGE,
        language: process.env.ELEVENLABS_AGENT_LANGUAGE || 'en',
        dynamic_variables: { dynamic_variable_placeholders: { mode: 'onboarding', user_name: '', context: 'nothing yet', first_message: "Hey, I'm Wingman. What should I call you?" } },
        // Gemini is the voice's brain too (same model as the Mastra agents), unless ELEVENLABS_AGENT_LLM overrides it.
        prompt: { prompt: VOICE_PROMPT, llm: process.env.ELEVENLABS_AGENT_LLM || process.env.GEMINI_MODEL || 'gemini-3.8-flash', temperature: 0.5 },
      },
      tts: { voice_id: process.env.ELEVENLABS_VOICE_ID || 'SAz9YHcvj6GT2YYXdXww' },
      conversation: { max_duration_seconds: 600 },
    },
    platform_settings: { auth: { enable_auth: false } },
  }
}

async function api(path, method = 'GET', body) {
  const res = await fetch(`${API}${path}`, { method, headers: headers(), ...(body ? { body: JSON.stringify(body) } : {}) })
  const json = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(`elevenlabs ${method} ${path} ${res.status}: ${JSON.stringify(json.detail ?? json).slice(0, 500)}`)
  return json
}

/** Creates or updates each client tool by name; returns their ids. */
async function syncTools() {
  const existing = (await api('/tools')).tools ?? []
  const ids = []
  for (const t of VOICE_TOOLS) {
    const tool_config = { type: 'client', name: t.name, description: t.description, parameters: t.parameters, expects_response: true, response_timeout_secs: 20 }
    const found = existing.find((e) => e.tool_config?.name === t.name)
    const r = found ? await api(`/tools/${found.id}`, 'PATCH', { tool_config }) : await api('/tools', 'POST', { tool_config })
    ids.push(r.id ?? found?.id)
  }
  return ids
}

/** Pushes prompt, first message, tools and end_call to the agent (creates it if needed). Returns agent_id. */
export async function syncVoiceAgent(agentId) {
  const tool_ids = await syncTools()
  const cfg = agentConfig()
  cfg.conversation_config.agent.prompt.tool_ids = tool_ids
  cfg.conversation_config.agent.prompt.built_in_tools = { end_call: { name: 'end_call', description: 'End the conversation when it is naturally over.', params: { system_tool_type: 'end_call' } } }
  if (agentId) {
    await api(`/agents/${agentId}`, 'PATCH', cfg)
    return agentId
  }
  const json = await api('/agents/create', 'POST', { name: 'Wingman voice', ...cfg })
  return json.agent_id
}

/** @deprecated kept for older scripts */
export const createVoiceAgent = () => syncVoiceAgent()

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
