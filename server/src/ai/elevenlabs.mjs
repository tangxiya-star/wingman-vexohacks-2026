// ElevenLabs text-to-speech for openers. Optional: without a key the phone falls back to browser speech.
export const hasVoice = () => !!process.env.ELEVENLABS_API_KEY

/** @returns {Promise<Buffer>} mp3 bytes */
export async function speak(text) {
  const voice = process.env.ELEVENLABS_VOICE_ID || 'cgSgspJ2msm6clMCkdW9' // Jessica: young, playful, warm
  const res = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${voice}?output_format=mp3_44100_128`, {
    method: 'POST',
    headers: { 'xi-api-key': process.env.ELEVENLABS_API_KEY, 'Content-Type': 'application/json', Accept: 'audio/mpeg' },
    // same model and feel as the voice agent, so the app's own lines sound like the same person
    body: JSON.stringify({ text, model_id: 'eleven_v4_turbo', voice_settings: { stability: 0.4, similarity_boost: 0.75, speed: 1.03 } }),
    signal: AbortSignal.timeout(15000),
  })
  if (!res.ok) throw new Error(`elevenlabs ${res.status}: ${(await res.text()).slice(0, 200)}`)
  return Buffer.from(await res.arrayBuffer())
}
