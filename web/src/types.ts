export type Band = 'A' | 'B'
export type Role = 'phone' | 'console' | 'room'

export type SessionState =
  | 'idle'
  | 'profiling'
  | 'matched'
  | 'mutual'
  | 'meeting_confirmed'
  | 'whisper'
  | 'stay_in_touch'
  | 'no_match'
  | 'passed'
  | 'expired'
  | 'hidden'
  | 'band_disconnected'

export type LedMode = 'off' | 'white' | 'purple_slow' | 'purple_fast' | 'green'

export interface Msg<T = any> {
  type: string
  ts: number
  data: T
}

export interface StateChanged {
  state: SessionState
  match_gesture?: string
  you_joined?: boolean
  you_confirmed?: boolean
  their_name?: string
}

export type SourceId = 'letterboxd' | 'reddit' | 'tiktok' | 'instagram' | 'spotify' | 'voice'

export interface Specific {
  source: SourceId
  text: string
}

export interface Highlight extends Specific {
  id: string
}

export interface CoreLine {
  id: string
  kind: 'theme' | 'drawn_to'
  text: string
  because: string[]
}

export interface ProfileReady {
  core: CoreLine[]
  highlights: Highlight[]
  says_vs_shows?: string | null
  failed_sources: SourceId[]
}

export interface MatchFound {
  core_overlap: string[]
  type_fit: boolean
  shared_specifics: Specific[]
  shared_values: string[]
  reason: string
  evidence: string[]
  opener: string
}

export interface WhisperReady {
  band: Band
  audio_url: string | null
  text: string
}

export interface ContactExchanged {
  name: string
  contact: string
  second_date_idea: string
}

export interface RoomUpdate {
  state: SessionState
  leds: Record<Band, LedMode>
  last_events: string[]
  core_overlap?: string[]
  type_fit?: boolean
  shared_specifics?: Specific[]
  shared_values?: string[]
  match_gesture?: string
  names?: Partial<Record<Band, string>>
}

export interface Sources {
  letterboxd?: { username: string }
  reddit?: { username: string }
  spotify?: { playlist_url: string }
  tiktok?: { screenshots: string[] }
  instagram?: { screenshots: string[] }
  voice?: { conversation_id?: string; transcript: VoiceTurn[] }
}

export interface VoiceTurn {
  role: 'user' | 'agent'
  text: string
}

export interface JoinPayload {
  band: Band
  name: string
  looking_for: 'serious' | 'open' | 'friends'
  dealbreaker: string
  about?: string
  consent: true
  source_consent: true
  sources: Sources
}
