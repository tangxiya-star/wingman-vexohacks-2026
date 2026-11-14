import type { SourceId } from './types'

export const SOURCE_META: Record<SourceId, { icon: string; label: string }> = {
  letterboxd: { icon: '🎬', label: 'Letterboxd' },
  reddit: { icon: '👽', label: 'Reddit' },
  tiktok: { icon: '🎵', label: 'TikTok' },
  instagram: { icon: '📷', label: 'Instagram' },
  spotify: { icon: '🎧', label: 'Spotify' },
  voice: { icon: '🎙', label: 'Voice' },
}

/** Downscale a screenshot to a JPEG data URL (long edge ≤ max px). */
export async function compressImage(file: File, max = 1280, quality = 0.7): Promise<string> {
  const bmp = await createImageBitmap(file)
  const scale = Math.min(1, max / Math.max(bmp.width, bmp.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(bmp.width * scale)
  canvas.height = Math.round(bmp.height * scale)
  canvas.getContext('2d')!.drawImage(bmp, 0, 0, canvas.width, canvas.height)
  bmp.close()
  return canvas.toDataURL('image/jpeg', quality)
}
