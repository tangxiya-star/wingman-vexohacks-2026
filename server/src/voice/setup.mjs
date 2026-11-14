// One-time: create the ElevenLabs voice agent and save its id to .env.
//   npm run voice:setup
import { readFileSync, writeFileSync } from 'node:fs'
import { createVoiceAgent } from './agent.mjs'

if (!process.env.ELEVENLABS_API_KEY) {
  console.error('Set ELEVENLABS_API_KEY in server/.env first.')
  process.exit(1)
}
if (process.env.ELEVENLABS_AGENT_ID) {
  console.log(`Already set: ELEVENLABS_AGENT_ID=${process.env.ELEVENLABS_AGENT_ID} (delete it from .env to create a new one)`)
  process.exit(0)
}
const id = await createVoiceAgent()
const envPath = new URL('../../.env', import.meta.url)
let env = ''
try {
  env = readFileSync(envPath, 'utf8')
} catch {}
env = /^ELEVENLABS_AGENT_ID=.*$/m.test(env) ? env.replace(/^ELEVENLABS_AGENT_ID=.*$/m, `ELEVENLABS_AGENT_ID=${id}`) : `${env.trimEnd()}\nELEVENLABS_AGENT_ID=${id}\n`
writeFileSync(envPath, env)
console.log(`Created voice agent ${id} and saved it to server/.env. Restart the server.`)
