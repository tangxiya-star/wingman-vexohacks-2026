// ElevenLabs text-to-speech for openers. Optional: without a key the phone falls back to browser speech.
export const hasVoice = () => !!process.env.ELEVENLABS_API_KEY

/** @returns {Promise<Buffer>} mp3 bytes */
export async function speak(text) {
  const voice = process.env.ELEVENLABS_VOICE_ID || '21m00Tcm4TlvDq8Ikt8R'
  const res = await fetch(`https://api.elevenlabs.io/v1/text-to-speech/${voice}?output_format=mp3_44100_128`, {
    method: 'POST',
    headers: { 'xi-api-key': process.env.ELEVENLABS_API_KEY, 'Content-Type': 'application/json', Accept: 'audio/mpeg' },
    body: JSON.stringify({ text, model_id: 'eleven_multilingual_v2' }),
    signal: AbortSignal.timeout(15000),
  })
  if (!res.ok) throw new Error(`elevenlabs ${res.status}: ${(await res.text()).slice(0, 200)}`)
  return Buffer.from(await res.arrayBuffer())
}
