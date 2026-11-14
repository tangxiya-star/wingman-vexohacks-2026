// Create the ElevenLabs voice agent (or update it after prompt/tool changes) and save its id to .env.
//   npm run voice:setup
import { readFileSync, writeFileSync } from 'node:fs'
import { syncVoiceAgent } from './agent.mjs'

if (!process.env.ELEVENLABS_API_KEY) {
  console.error('Set ELEVENLABS_API_KEY in server/.env first.')
  process.exit(1)
}
if (process.env.ELEVENLABS_AGENT_ID) {
  await syncVoiceAgent(process.env.ELEVENLABS_AGENT_ID)
  console.log(`Updated voice agent ${process.env.ELEVENLABS_AGENT_ID} (prompt, tools, end_call).`)
  process.exit(0)
}
const id = await syncVoiceAgent()
const envPath = new URL('../../.env', import.meta.url)
let env = ''
try {
  env = readFileSync(envPath, 'utf8')
} catch {}
env = /^ELEVENLABS_AGENT_ID=.*$/m.test(env) ? env.replace(/^ELEVENLABS_AGENT_ID=.*$/m, `ELEVENLABS_AGENT_ID=${id}`) : `${env.trimEnd()}\nELEVENLABS_AGENT_ID=${id}\n`
writeFileSync(envPath, env)
console.log(`Created voice agent ${id} and saved it to server/.env. Restart the server.`)
