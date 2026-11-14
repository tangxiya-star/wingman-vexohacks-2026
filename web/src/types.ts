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
  their_name?: string
}

export interface MatchFound {
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
  shared_values?: string[]
  match_gesture?: string
  names?: Partial<Record<Band, string>>
}

export interface JoinPayload {
  band: Band
  name: string
  weekend: string
  matters_most: string
  looking_for: 'serious' | 'open' | 'friends'
  dealbreaker: string
  about?: string
  consent: true
}
