import { useCallback, useEffect, useRef, useState } from 'react'
import { ConversationProvider, useConversation } from '@elevenlabs/react'
import { FluidBlob, PALETTES, type BlobMood } from '../components/FluidBlob'
import { Mark } from '../components/Plate'
import { SparkBurst } from '../components/SparkBurst'
import gesture from '../config/gesture.json'
import { bandParam, devMode, httpBase, useSocket } from '../ws'
import { SOURCE_META, compressImage } from '../sources'
import { overlapRows } from '../overlaps'
import type { BandPose, HeartRate, ContactExchanged, JoinPayload, MatchFound, Msg, ProfileReady, SessionState, Sources, StateChanged, VoiceTurn } from '../types'
import * as speech from './speech'
import { BandsCard, HeartCard, type HeartSample } from './LiveCards'

/**
 * Wingman is a voice. One live ElevenLabs conversation does the onboarding; the agent calls client tools
 * (set_name, add_account, finish_onboarding, confirm_profile, stay_in_touch) and this app runs them.
 * What's said shows up as bubbles: a transcript, not a chat box.
 */
type Line = {
  id: number
  from: 'agent' | 'user' | 'note'
  text?: string
  list?: string[]
  images?: string[]
  contact?: ContactExchanged
}
type Platform = 'letterboxd' | 'reddit' | 'tiktok' | 'instagram'
type Mode = 'onboarding' | 'stay' | 'chat'
type Pending = null | 'review' | 'stay'

const LABEL: Record<Platform, string> = {
  letterboxd: 'Letterboxd',
  reddit: 'Reddit',
  tiktok: 'TikTok',
  instagram: 'Instagram',
}
const MAX_SHOTS = 4
const params = new URLSearchParams(location.search)
const palette: 'bloom' | 'lagoon' = params.get('blob') === 'lagoon' ? 'lagoon' : 'bloom'
const textOnly = devMode && params.has('text') // dev: run the real agent without a mic
const isSystem = (t: string) => t.trim().startsWith('[system]')

export function VoiceApp() {
  return (
    <ConversationProvider>
      <Wingman />
    </ConversationProvider>
  )
}

function Wingman() {
  const band = bandParam
  const [lines, setLines] = useState<Line[]>([])
  const [thinking, setThinking] = useState(false)
  const [pending, setPendingState] = useState<Pending>(null)
  const [joined, setJoined] = useState(false)
  const [confirmed, setConfirmed] = useState(false)
  const [needShots, setNeedShots] = useState<'tiktok' | 'instagram' | null>(null)
  const [shotMenu, setShotMenu] = useState(false)
  const [sound, setSound] = useState(!params.has('mute'))
  const [talking, setTalking] = useState(false)
  const [error, setError] = useState('')
  const [devText, setDevText] = useState('')
  const [typeFor, setTypeFor] = useState<Platform | 'any' | null>(null)
  const [typed, setTyped] = useState('')
  const [, bump] = useState(0)
  const [room, setRoom] = useState<SessionState>('idle')
  const [match, setMatch] = useState<MatchFound | null>(null)
  const [moment, setMoment] = useState<null | 'found' | 'mutual' | 'met'>(null)
  const [saidYes, setSaidYes] = useState(false)
  // generative UI: the agent picks the live card under the shape (show_card); null = follow the night automatically
  type LiveCard = 'heartbeat' | 'bands' | 'match' | 'none'
  const [agentCard, setAgentCard] = useState<LiveCard | null>(null)
  const liveCardRef = useRef<LiveCard | null>(null)
  const fluidRef = useRef<HTMLDivElement>(null)
  // "it's a match" gets its own scene first: just the shape, the gold, and their name. Then the card.
  const [scene, setScene] = useState(false)
  useEffect(() => {
    if (moment !== 'met') return setScene(false)
    setScene(true)
    const t = setTimeout(() => setScene(false), 3600)
    return () => clearTimeout(t)
  }, [moment])
  const fluidEl = useCallback(() => fluidRef.current, [])
  useEffect(() => setAgentCard(null), [moment]) // when the night moves on, the screen follows it again
  const [heart, setHeart] = useState<HeartSample[]>([])
  // re-check freshness every couple of seconds, so the badge and card notice when the band stops sending
  const [, setHeartTick] = useState(0)
  const hasHeart = heart.length > 0
  useEffect(() => {
    if (!hasHeart) return
    const t = setInterval(() => setHeartTick((n) => n + 1), 2000)
    return () => clearInterval(t)
  }, [hasHeart])
  const heartRef = useRef<HeartSample[]>([])
  const lastSpike = useRef(0)
  const [pose, setPose] = useState<BandPose>({ you: 'unknown', them: 'unknown' })

  const nextId = useRef(1)
  const pendingRef = useRef<Pending>(null)
  const d = useRef({
    name: '',
    accounts: {} as Partial<Record<Platform, string>>,
    shots: { tiktok: [] as string[], instagram: [] as string[] },
    profile: null as ProfileReady | null,
    lookingFor: 'open' as JoinPayload['looking_for'],
    dealbreaker: '',
  })
  const ev = useRef({
    state: 'idle' as SessionState,
    first: true,
    joined: false,
    confirmed: false,
    theirName: '',
    saidYes: false,
    stayAnswered: false,
    stayAsked: false,
    matchAnnounced: false,
    contact: false,
  })
  const mode = useRef<Mode>('onboarding')
  const turns = useRef<VoiceTurn[]>([])
  if (textOnly) (window as unknown as { __turns: typeof turns }).__turns = turns // dev: read the transcript in tests
  const lastResponse = useRef<string | undefined>(undefined)
  const lastAgentLine = useRef<number | null>(null)
  const announceAfterConnect = useRef<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)

  const setPending = (p: Pending) => {
    pendingRef.current = p
    setPendingState(p)
  }
  const push = (l: Omit<Line, 'id'>) => setLines((ls) => [...ls, { ...l, id: nextId.current++ }])
  const note = (text: string) => push({ from: 'note', text })

  /** Wingman says something outside a live conversation (room events): bubble + spoken. */
  const announce = (text: string, opts: { speak?: boolean } = {}) => {
    push({ from: 'agent', text })
    if (live()) conversation.sendUserMessage(`[system] Say this to them now, in your own words, in one line: "${text}"`)
    else if (opts.speak !== false) speech.speakLine(text)
  }

  // ---------- client tools (the agent calls these) ----------
  const clientTools = {
    set_name: ({ name }: { name: string }) => {
      d.current.name = String(name || '')
        .trim()
        .slice(0, 24)
      return `Saved. Their name is ${d.current.name}.`
    },
    add_account: ({ platform, username }: { platform: Platform; username: string }) => {
      const u = String(username || '')
        .trim()
        .replace(/^@|^u\//i, '')
        .replace(/\s+/g, '')
      if (!LABEL[platform] || !u) return 'Could not save that. Ask again.'
      d.current.accounts[platform] = u
      setTypeFor(null)
      bump((n) => n + 1)
      if (platform === 'tiktok' || platform === 'instagram') {
        setNeedShots(platform)
        return `Noted @${u}. ${LABEL[platform]} likes aren't visible from a username; the photo button is now highlighted so they can add screenshots of their ${platform === 'tiktok' ? 'Favorites' : 'Saved'}.`
      }
      return `Connected ${LABEL[platform]} @${u}. Their public ${platform === 'letterboxd' ? 'ratings and reviews' : 'posts'} will be read.`
    },
    ask_to_type: ({ platform }: { platform: Platform | 'any' }) => {
      setTypeFor(LABEL[platform as Platform] ? platform : 'any')
      return 'A small text box is open on their screen; their typed username will arrive as their next message.'
    },
    ask_for_screenshots: ({ platform }: { platform: 'tiktok' | 'instagram' }) => {
      setNeedShots(platform === 'instagram' ? 'instagram' : 'tiktok')
      return 'The photo button is highlighted on their screen now.'
    },
    finish_onboarding: ({ looking_for, dealbreaker }: { looking_for: JoinPayload['looking_for']; dealbreaker: string }) => {
      d.current.lookingFor = ['serious', 'open', 'friends'].includes(looking_for) ? looking_for : 'open'
      d.current.dealbreaker = String(dealbreaker || '').slice(0, 120)
      return join()
        ? 'Joined. Their Taste Core is being built and takes about fifteen seconds. Keep it light until it arrives.'
        : "Couldn't reach the room. Tell them to give it a second, then try finish_onboarding again."
    },
    confirm_profile: ({ remove }: { remove: string }) => {
      const core = d.current.profile?.core ?? []
      const drop = String(remove || '')
        .split(/[^0-9]+/)
        .map(Number)
        .filter((n) => n >= 1 && n <= core.length)
        .map((n) => core[n - 1].id)
      if (!send('profile_confirm', { band, removed: drop })) return "Couldn't reach the room. Tell them to give it a second, then call confirm_profile again."
      ev.current.confirmed = true
      setConfirmed(true)
      setPending(null)
      return `Confirmed${drop.length ? `, dropped ${drop.length} line${drop.length > 1 ? 's' : ''}` : ''}. They're in.`
    },
    show_card: ({ card }: { card: LiveCard }) => {
      if (!['heartbeat', 'bands', 'match', 'none'].includes(card)) return 'Unknown card. Use heartbeat, bands, match or none.'
      if (card === 'heartbeat' && !heartRef.current.length) return "No heart rate yet: their band isn't sending it. Don't mention it."
      if (card === 'match' && !ev.current.matchAnnounced) return "There's no match yet."
      setAgentCard(card)
      return card === 'none' ? 'Cleared.' : `Showing the ${card} card.`
    },
    stay_in_touch: ({ yes, contact }: { yes: boolean; contact?: string }) => {
      const ok = yes === true || String(yes) === 'true'
      const sent = send('stay_in_touch', {
        band,
        yes: ok,
        ...(ok && contact ? { contact: String(contact).slice(0, 80) } : {}),
      })
      if (!sent) return "Couldn't reach the room. Tell them to give it a second, then call stay_in_touch again."
      ev.current.stayAnswered = true
      setPending(null)
      return ok ? "Recorded. It's only shared if they say yes too." : 'Recorded. Nobody learns who said no.'
    },
  }

  const conversation = useConversation({
    clientTools,
    onMessage: (m) => {
      const text = m.message
      if (!text || isSystem(text)) return
      const role: VoiceTurn['role'] = m.role === 'user' || m.source === 'user' ? 'user' : 'agent'
      const t = turns.current
      if (role === 'agent' && m.response_id && m.response_id === lastResponse.current && t[t.length - 1]?.role === 'agent') {
        turns.current = [...t.slice(0, -1), { role, text }]
        const id = lastAgentLine.current
        setLines((ls) => ls.map((l) => (l.id === id ? { ...l, text } : l)))
      } else {
        turns.current = [...t, { role, text }]
        if (role === 'agent') lastAgentLine.current = nextId.current
        push({ from: role, text })
      }
      lastResponse.current = role === 'agent' ? m.response_id : undefined
    },
    onConnect: () => {
      const msg = announceAfterConnect.current
      announceAfterConnect.current = null
      if (msg) setTimeout(() => conversation.sendUserMessage(msg), 400)
    },
    onError: (e: unknown) => setError(typeof e === 'string' ? e : ((e as Error)?.message ?? 'Voice error')),
    onDisconnect: () => setNeedShots(null),
  })
  const live = () => conversation.status === 'connected'
  const isLive = conversation.status === 'connected'
  const connecting = conversation.status === 'connecting'

  // ---------- sessions ----------
  const summary = () => {
    const x = d.current
    const acc = Object.entries(x.accounts).map(([p, u]) => `${LABEL[p as Platform]} @${u}`)
    const shots = (['tiktok', 'instagram'] as const).filter((p) => x.shots[p].length).map((p) => `${x.shots[p].length} ${LABEL[p]} screenshots`)
    const bits = [...acc, ...shots]
    return bits.length ? `Already connected: ${bits.join(', ')}.` : 'Nothing connected yet.'
  }

  async function start(m: Mode, firstMessage: string, context: string, afterConnect?: string) {
    speech.stopSpeech()
    speech.unlockAudio()
    setError('')
    if (!textOnly) {
      try {
        const probe = await navigator.mediaDevices.getUserMedia({ audio: true })
        probe.getTracks().forEach((t) => t.stop())
      } catch {
        return setError('Wingman needs your microphone.')
      }
    }
    try {
      const res = await fetch(`${httpBase()}/voice/session`)
      const s = await res.json()
      if (!res.ok) throw new Error(s.error || 'Voice is unavailable')
      mode.current = m
      announceAfterConnect.current = afterConnect ?? null
      lastResponse.current = undefined
      conversation.startSession({
        ...(s.signed_url ? { signedUrl: s.signed_url } : { agentId: s.agent_id }),
        dynamicVariables: {
          mode: m,
          user_name: d.current.name,
          context,
          first_message: firstMessage,
        },
        ...(textOnly ? { overrides: { conversation: { textOnly: true } } } : {}),
      })
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const tapMain = () => {
    if (isLive) return conversation.endSession()
    if (connecting) return
    const x = d.current
    const e = ev.current
    if (x.profile && (pendingRef.current === 'review' || (e.joined && !e.confirmed)))
      return start('onboarding', `Okay${x.name ? ` ${x.name}` : ''}, I've got a read on you.`, summary(), profileMessage(x.profile))
    if (pendingRef.current === 'stay')
      return start('stay', `So, you just met ${e.theirName || 'someone'}. Want to stay in touch?`, e.theirName || 'someone at the event')
    if (e.joined) return start('chat', x.name ? `Hey ${x.name}. How's tonight going?` : "Hey. How's tonight going?", tonight())
    if (x.name || Object.keys(x.accounts).length) return start('onboarding', `Welcome back${x.name ? `, ${x.name}` : ''}. Where were we?`, summary())
    return start('onboarding', "Hey, I'm Wingman. I'll help you meet someone here who actually gets your taste. What should I call you?", summary())
  }

  const tonight = () => {
    const e = ev.current
    if (e.contact) return `They met ${e.theirName} and swapped contacts.`
    if (e.theirName) return `They met ${e.theirName}.`
    return "They're in and waiting for their band to light up."
  }

  const profileMessage = (p: ProfileReady) => {
    const linesTxt = p.core.map((c, i) => `${i + 1}. ${c.text}`).join('\n')
    const failed = p.failed_sources.map((s) => SOURCE_META[s]?.label ?? s)
    return `[system] Their Taste Core is ready:\n${linesTxt}${p.says_vs_shows ? `\nSays vs shows: ${p.says_vs_shows}` : ''}${failed.length ? `\nCouldn't read: ${failed.join(', ')}.` : ''}\nPresent it to them now, then call confirm_profile.`
  }

  // ---------- room ----------
  const join = () => {
    const x = d.current
    const sources: Sources = {}
    const spoken = turns.current.filter((t) => !isSystem(t.text))
    if (spoken.some((t) => t.role === 'user')) sources.voice = { transcript: spoken }
    if (x.accounts.letterboxd) sources.letterboxd = { username: x.accounts.letterboxd }
    if (x.accounts.reddit) sources.reddit = { username: x.accounts.reddit }
    if (x.shots.tiktok.length) sources.tiktok = { screenshots: x.shots.tiktok }
    if (x.shots.instagram.length) sources.instagram = { screenshots: x.shots.instagram }
    const handles = (['tiktok', 'instagram'] as const).filter((p) => x.accounts[p]).map((p) => `${LABEL[p]} @${x.accounts[p]}`)
    const ok = send('join', {
      band,
      name: x.name || 'Guest',
      looking_for: x.lookingFor,
      dealbreaker: x.dealbreaker || 'not said',
      consent: true,
      source_consent: true,
      sources,
      ...(handles.length ? { about: `Handles they shared: ${handles.join(', ')}` } : {}),
    })
    if (ok) {
      setNeedShots(null)
      setThinking(true)
    }
    return ok
  }

  const { connected, send } = useSocket('phone', band, (m: Msg) => {
    const e = ev.current
    switch (m.type) {
      case 'state_changed': {
        const s = m.data as StateChanged
        const prev = e.state
        const first = e.first
        e.first = false
        e.state = s.state
        setRoom(s.state)
        if (s.their_name) e.theirName = s.their_name
        if (s.you_joined === false && e.joined) return restart()
        if (typeof s.you_joined === 'boolean') {
          e.joined = s.you_joined
          setJoined(s.you_joined)
        }
        if (s.you_joined && !s.you_confirmed && !e.confirmed) setThinking(!d.current.profile)
        if (e.confirmed && s.you_joined && s.you_confirmed === false) send('profile_confirm', { band, removed: [] })
        if (s.you_confirmed && !e.confirmed) {
          e.confirmed = true
          setConfirmed(true)
          setThinking(false)
          if (pendingRef.current === 'review') setPending(null)
          if (!live()) announce(first ? "Welcome back. You're in." : "You're in. Keep your band on. It glows when there's someone here worth meeting.")
        }
        if (s.state !== prev && !first) onState(s.state, prev)
        return
      }
      case 'profile_ready': {
        if (e.confirmed) return
        const p = m.data as ProfileReady
        const replay = d.current.profile !== null && JSON.stringify(d.current.profile?.core) === JSON.stringify(p.core)
        d.current.profile = p
        setThinking(false)
        if (replay) return
        push({ from: 'note', list: p.core.map((c) => c.text) })
        setPending('review')
        if (live()) conversation.sendUserMessage(profileMessage(p))
        else {
          setPending('review')
          announce('Your Taste Core is ready. Tap to hear it.')
        }
        return
      }
      case 'match_found': {
        const mt = m.data as MatchFound
        if (e.matchAnnounced) return
        e.matchAnnounced = true
        setMatch(mt)
        setSaidYes(false)
        // after a reload the server replays the match: land on the screen that fits where the room is
        const at = e.state
        if (at === 'mutual') return setMoment('mutual')
        if (['meeting_confirmed', 'whisper', 'stay_in_touch'].includes(at)) return setMoment('met')
        setMoment('found')
        // a quiet heads-up, not an announcement: no number, just the one specific reason
        const whisper = `Psst${d.current.name ? `, ${d.current.name}` : ''}. There's someone here you might really click with. ${mt.reason}`
        if (live()) conversation.sendContextualUpdate(`[system] They just got a match. Never give a score or percentage. Why: ${mt.reason}`)
        else speech.speakLine(whisper, { soft: true })
        return
      }
      case 'decision_status':
        if (m.data?.you_said_yes && !e.saidYes) {
          e.saidYes = true
          setSaidYes(true)
          speech.speakLine('You said yes. Waiting for them.', { soft: true })
        }
        return
      case 'whisper_ready': {
        // no scripted opener: just the stay-in-touch question, once they've had a moment
        if (e.stayAnswered || e.stayAsked) return
        e.stayAsked = true
        setPending('stay')
        announce(`Enjoy it. Whenever you're ready, tap and tell me if you want to stay in touch with ${e.theirName || 'them'}.`)
        return
      }
      case 'contact_exchanged': {
        const c = m.data as ContactExchanged
        e.contact = true
        setPending(null)
        push({ from: 'note', contact: c })
        announce(`${c.name} said yes too. Next time: ${c.second_date_idea}`)
        return
      }
      case 'heart_rate': {
        const h = { bpm: (m.data as HeartRate).bpm, at: Date.now() } // phone clock: freshness can't drift with the server's
        const list = [...heartRef.current, h].filter((x) => h.at - x.at <= 90_000)
        heartRef.current = list
        setHeart(list)
        // a clear jump over the last minute's resting level: let the agent know (it may mention it, lightly)
        const before = list.filter((x) => h.at - x.at > 15_000)
        // never during onboarding: the agent's reply would land in the voice transcript and the taste profile
        if (before.length >= 5 && live() && mode.current !== 'onboarding' && h.at - lastSpike.current > 90_000) {
          const base = Math.round(before.reduce((a, x) => a + x.bpm, 0) / before.length)
          if (h.bpm - base >= 15) {
            lastSpike.current = h.at
            conversation.sendContextualUpdate(`[system] Their heart rate just jumped from about ${base} to ${h.bpm} bpm. Private to them.`)
          }
        }
        return
      }
      case 'band_pose':
        return setPose(m.data as BandPose)
      case 'error':
        return setError(m.data?.message ?? 'Something went wrong.')
    }
  })

  const onState = (s: SessionState, prev: SessionState) => {
    const e = ev.current
    if (!e.confirmed) return
    switch (s) {
      case 'matched':
        e.saidYes = false
        return // match_found brings the card and the whisper
      case 'mutual':
        setMoment('mutual')
        return announce(`It's mutual. Look around for the other light. ${gesture.instruction}`)
      case 'meeting_confirmed':
        setMoment('met')
        try {
          navigator.vibrate?.([30, 70, 30]) // Android: a small double tap in the hand as the bands go green
        } catch {}
        return announce(e.theirName ? `It's a match. Meet ${e.theirName}.` : "It's a match.")
      case 'stay_in_touch':
        if (e.stayAnswered)
          setTimeout(() => {
            if (!ev.current.contact && ev.current.state === 'stay_in_touch') announce('Thanks for meeting.')
          }, 1800)
        return
      case 'no_match':
      case 'passed':
      case 'expired':
        setPending(null)
        setMoment(null)
        setMatch(null)
        ev.current.matchAnnounced = false
        if (['matched', 'mutual', 'profiling'].includes(prev)) announce("No match right now. I'll keep looking.")
        return
      case 'hidden':
        setPending(null)
        setMoment(null)
        setMatch(null)
        ev.current.matchAnnounced = false
        return announce("You're hidden. You won't be matched tonight.")
      case 'band_disconnected':
        return setError('Reconnecting the bands…')
    }
  }

  function restart() {
    if (live()) conversation.endSession()
    speech.stopSpeech()
    setLines([])
    setThinking(false)
    setPending(null)
    setMoment(null)
    setMatch(null)
    setJoined(false)
    setConfirmed(false)
    setNeedShots(null)
    heartRef.current = []
    setHeart([])
    lastSpike.current = 0
    setPose({ you: 'unknown', them: 'unknown' })
    setAgentCard(null)
    turns.current = []
    d.current = {
      ...d.current,
      accounts: {},
      shots: { tiktok: [], instagram: [] },
      profile: null,
      lookingFor: 'open',
      dealbreaker: '',
    }
    Object.assign(ev.current, {
      joined: false,
      confirmed: false,
      theirName: '',
      saidYes: false,
      stayAnswered: false,
      stayAsked: false,
      matchAnnounced: false,
      contact: false,
    })
    if (d.current.name) speech.speakLine(`New round, ${d.current.name}. Tap when you want to talk.`)
  }

  // ---------- screenshots ----------
  const pickShots = (p: 'tiktok' | 'instagram') => {
    setNeedShots(p)
    setShotMenu(false)
    fileRef.current?.click()
  }
  const onFiles = async (files: FileList | null) => {
    const p = needShots ?? 'tiktok'
    if (!files?.length) return
    // one at a time: decoding several phone photos at once can run a phone out of memory
    const imgs: string[] = []
    for (const f of Array.from(files)
      .filter((f) => f.type.startsWith('image/'))
      .slice(0, MAX_SHOTS)) {
      try {
        imgs.push(await compressImage(f))
      } catch {
        /* skip an unreadable image */
      }
    }
    if (fileRef.current) fileRef.current.value = ''
    if (!imgs.length) return
    const x = d.current
    x.shots[p] = [...x.shots[p], ...imgs].slice(0, MAX_SHOTS)
    bump((n) => n + 1)
    setNeedShots(null)
    if (live()) conversation.sendContextualUpdate(`[system] They added ${imgs.length} ${LABEL[p]} screenshot${imgs.length > 1 ? 's' : ''}.`)
  }

  // ---------- effects ----------
  useEffect(() => {
    const off = speech.onSpeechChange(() => setTalking(speech.isSpeaking()))
    const unlock = () => speech.unlockAudio()
    window.addEventListener('pointerdown', unlock, { once: true })
    return () => {
      off()
      window.removeEventListener('pointerdown', unlock)
    }
  }, [])
  useEffect(() => speech.setSound(sound), [sound])

  // ---------- render ----------
  const getLevel = () => {
    const fake = devMode ? (window as unknown as { __voiceLevel?: number }).__voiceLevel : undefined
    if (fake != null) return fake
    if (isLive && !textOnly) return conversation.isSpeaking ? conversation.getOutputVolume() : conversation.getInputVolume()
    const spoken = speech.speechLevel()
    const hr = heartRef.current[heartRef.current.length - 1]
    if (!spoken && liveCardRef.current === 'heartbeat' && hr) {
      const t = ((performance.now() / 1000) * hr.bpm) / 60
      return Math.pow(Math.max(0, Math.sin(t * Math.PI * 2)), 12) * 0.45 // a soft lub at their pulse
    }
    return spoken
  }
  const mood: BlobMood = isLive
    ? conversation.isSpeaking
      ? 'speaking'
      : 'listening'
    : talking
      ? 'speaking'
      : thinking
        ? 'listening'
        : confirmed
          ? 'rest'
          : 'idle'
  const status = connecting
    ? 'Connecting…'
    : isLive
      ? conversation.isSpeaking
        ? 'Wingman is talking'
        : 'Listening'
      : thinking
        ? 'Reading your taste…'
        : pending === 'review'
          ? 'Tap to hear your Taste Core'
          : pending === 'stay'
            ? 'Tap to answer'
            : confirmed && room === 'matched'
              ? 'Someone here gets your taste. Tap your band to meet.'
              : confirmed && room === 'mutual'
                ? 'Look around for the other light'
                : confirmed && ['meeting_confirmed', 'whisper'].includes(room)
                  ? ev.current.theirName
                    ? `Meet ${ev.current.theirName}`
                    : 'You found each other'
                  : confirmed && ev.current.contact
                    ? `You and ${ev.current.theirName || 'them'} are connected`
                    : confirmed && room === 'hidden'
                      ? 'You’re hidden'
                      : confirmed
                        ? 'Your band will glow when there’s someone worth meeting'
                        : turns.current.length
                          ? 'Tap to keep talking'
                          : 'Tap to talk to Wingman'
  const canAddShots = !confirmed && !joined
  const shapePalette = moment === 'met' ? 'spark' : palette
  const heartFresh = heart.length > 0 && Date.now() - heart[heart.length - 1].at < 10_000
  const autoCard: LiveCard | null = moment === 'mutual' ? 'bands' : moment && match ? 'match' : null
  const liveCard = agentCard === 'none' ? null : (agentCard ?? autoCard)
  liveCardRef.current = liveCard
  const x = d.current
  const connectedBits = [
    ...Object.entries(x.accounts).map(([p, u]) => `${LABEL[p as Platform]} @${u}`),
    ...(['tiktok', 'instagram'] as const)
      .filter((p) => x.shots[p].length)
      .map((p) => `${x.shots[p].length} ${LABEL[p]} screenshot${x.shots[p].length > 1 ? 's' : ''}`),
  ]
  const card = [...lines].reverse().find((l) => l.contact)
  const sendTyped = () => {
    const u = typed.trim()
    if (!u || !live()) return
    const text = typeFor && typeFor !== 'any' ? `My ${LABEL[typeFor]} username is ${u} (typed)` : `${u} (typed)`
    conversation.sendUserMessage(text)
    turns.current = [...turns.current, { role: 'user', text }]
    setTyped('')
    setTypeFor(null)
  }

  return (
    <div className={`voice ${moment ? `voice--moment voice--${moment}` : ''} ${scene ? 'voice--scene' : ''}`} style={{ ['--agent-bg' as string]: PALETTES[shapePalette].bg }}>
      <header className="voice__top">
        <span className="brand">
          <Mark size={14} />
          Wingman
        </span>
        <span className="voice__meta">
          <span className={`dot ${connected ? 'dot--on' : ''}`} title={connected ? 'Connected' : 'Reconnecting'} />
          <span>Band {band}</span>
          {heartFresh && (
            <button
              className={`voice__link voice__hr ${liveCard === 'heartbeat' ? 'is-on' : ''}`}
              onClick={() => setAgentCard((c) => (c === 'heartbeat' ? null : 'heartbeat'))}
              aria-pressed={liveCard === 'heartbeat'}
              aria-label={`Heart rate ${heart[heart.length - 1].bpm}, show card`}
            >
              ♥ {heart[heart.length - 1].bpm}
            </button>
          )}
          <button className="voice__link" onClick={() => setSound((v) => !v)} aria-pressed={sound}>
            {sound ? 'Sound on' : 'Sound off'}
          </button>
          {joined && (
            <button className="voice__link" onClick={() => send('hide', { band })}>
              Hide
            </button>
          )}
        </span>
      </header>

      <div ref={fluidRef} className={`voice__fluid fluid fluid--${mood}`}>
        <FluidBlob getLevel={getLevel} mood={mood} palette={shapePalette} />
      </div>

      {!(liveCard && !card && !pending && !isLive && !connecting) && <p className="voice__status">{status}</p>}
      {error && <p className="voice__error">{error}</p>}
      {canAddShots && connectedBits.length > 0 && (
        <ul className="voice__connected" aria-label="Connected">
          {connectedBits.map((t) => (
            <li key={t}>{t}</li>
          ))}
        </ul>
      )}
      {moment === 'met' && <SparkBurst originEl={fluidEl} />}
      {scene && (
        <button className="scene" onClick={() => setScene(false)} aria-label="It's a match. Tap to continue">
          <span className="scene__title">It&rsquo;s a match.</span>
        </button>
      )}
      {!card && !scene && liveCard === 'heartbeat' && <HeartCard samples={heart} />}
      {!card && !scene && liveCard === 'bands' && (
        <BandsCard you={pose.you} them={pose.them} theirName={ev.current.theirName} met={moment === 'met'} instruction={gesture.instruction} />
      )}
      {!card && !scene && liveCard === 'match' && moment && match && (
        <MatchMoment key={moment} moment={moment === 'mutual' ? 'found' : moment} match={match} theirName={ev.current.theirName} saidYes={saidYes} />
      )}
      {card && <Bubble line={card} />}

      {typeFor && isLive && (
        <form
          className="voice__type"
          onSubmit={(e) => {
            e.preventDefault()
            sendTyped()
          }}
        >
          <input
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder={typeFor === 'any' ? 'Type it here' : `Your ${LABEL[typeFor]} username`}
            autoFocus
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            enterKeyHint="send"
          />
          <button type="submit" aria-label="Send" disabled={!typed.trim()}>
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path d="M12 19V5M6 11l6-6 6 6" stroke="currentColor" strokeWidth="1.7" fill="none" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </form>
      )}

      <div className="voice__bar">
        <div className="voice__side">
          {canAddShots && (
            <div className="voice__shots">
              <button
                className={`voice__round ${needShots ? 'is-asking' : ''}`}
                onClick={() => (needShots ? pickShots(needShots) : setShotMenu((v) => !v))}
                aria-label="Add screenshots"
              >
                <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
                  <rect x="3.5" y="5.5" width="17" height="13" rx="3" stroke="currentColor" strokeWidth="1.5" fill="none" />
                  <circle cx="9" cy="10.5" r="1.6" fill="currentColor" />
                  <path d="M5 17l4.5-4 3 2.5 3.5-3.5 3.5 3.5" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinejoin="round" />
                </svg>
              </button>
              {needShots && <span className="voice__hint">{LABEL[needShots]}</span>}
              {shotMenu && !needShots && (
                <div className="voice__menu">
                  <button onClick={() => pickShots('tiktok')}>TikTok screenshots</button>
                  <button onClick={() => pickShots('instagram')}>Instagram screenshots</button>
                </div>
              )}
            </div>
          )}
        </div>

        <button
          className={`voice__main ${isLive ? 'is-live' : ''} ${pending ? 'is-pending' : ''}`}
          onClick={tapMain}
          disabled={connecting}
          aria-label={isLive ? 'End' : 'Talk to Wingman'}
        >
          {isLive ? (
            <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true">
              <path d="M6 6l12 12M18 6L6 18" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
            </svg>
          ) : (
            <svg viewBox="0 0 24 24" width="24" height="24" aria-hidden="true">
              <rect x="9" y="3" width="6" height="11" rx="3" fill="currentColor" />
              <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" />
            </svg>
          )}
        </button>

        <div className="voice__side voice__side--right">
          {isLive && (
            <button className={`voice__round ${typeFor ? 'is-on' : ''}`} onClick={() => setTypeFor((v) => (v ? null : 'any'))} aria-label="Type a username">
              <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
                <rect x="3" y="6.5" width="18" height="11" rx="2.5" stroke="currentColor" strokeWidth="1.5" fill="none" />
                <path d="M7 10h.01M10 10h.01M13 10h.01M16 10h.01M8 14h8" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
              </svg>
            </button>
          )}
          {isLive && !textOnly && (
            <button
              className={`voice__round ${conversation.isMuted ? 'is-muted' : ''}`}
              onClick={() => conversation.setMuted(!conversation.isMuted)}
              aria-label={conversation.isMuted ? 'Unmute' : 'Mute'}
            >
              <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
                <rect x="9" y="3" width="6" height="11" rx="3" stroke="currentColor" strokeWidth="1.5" fill="none" />
                <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" stroke="currentColor" strokeWidth="1.5" fill="none" strokeLinecap="round" />
                {conversation.isMuted && <path d="M4 4l16 16" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />}
              </svg>
            </button>
          )}
        </div>
      </div>

      {textOnly && isLive && (
        <form
          className="voice__dev"
          onSubmit={(e) => {
            e.preventDefault()
            if (!devText.trim()) return
            conversation.sendUserMessage(devText.trim())
            turns.current = [...turns.current, { role: 'user', text: devText.trim() }]
            setDevText('')
          }}
        >
          <input value={devText} onChange={(e) => setDevText(e.target.value)} placeholder="dev: say something" />
        </form>
      )}
      <input ref={fileRef} type="file" accept="image/*" multiple hidden onChange={(e) => onFiles(e.target.files)} />
    </div>
  )
}

function Bubble({ line: l }: { line: Line }) {
  const cls = `msg msg--${l.from}`
  if (l.images)
    return (
      <div className={`${cls} msg--images`}>
        {l.images.map((src, i) => (
          <img key={i} src={src} alt="Screenshot" />
        ))}
      </div>
    )
  if (l.list)
    return (
      <ol className={`${cls} msg--list`}>
        {l.list.map((t) => (
          <li key={t}>{t}</li>
        ))}
      </ol>
    )
  if (l.contact)
    return (
      <div className={`${cls} msg--card`}>
        <span className="msg__label">{l.contact.name}</span>
        <p className="msg__big">{l.contact.contact || '—'}</p>
      </div>
    )
  return <div className={cls}>{l.text}</div>
}

/** The match, on screen: what you share across several dimensions (with where we saw it), and what to do next. No score. */
function MatchMoment({ moment, match, theirName, saidYes }: { moment: 'found' | 'mutual' | 'met'; match: MatchFound; theirName: string; saidYes: boolean }) {
  // what you share, one dimension per row (taste / values / wants / style), each with where we saw it
  const specifics = overlapRows(match, 3)
  return (
    <section className={`moment moment--${moment}`} aria-live="polite">
      <div className="moment__head">
        <div>
          <p className="moment__eyebrow">{moment === 'found' ? 'Someone here might be your person' : moment === 'mutual' ? "It's mutual" : "It's a match"}</p>
          <p className="moment__title">
            {moment === 'found' ? 'Your band is glowing.' : moment === 'mutual' ? 'You both said yes.' : theirName ? `Meet ${theirName}.` : 'You found each other.'}
          </p>
        </div>
      </div>
      {moment !== 'mutual' && match.reason && <p className="moment__reason">{match.reason}</p>}
      {moment !== 'mutual' && specifics.length > 0 && (
        <ul className="moment__why">
          {specifics.map((t) => (
            <li key={t.text}>
              <span className="moment__dim">{t.label}</span>
              <span>
                {t.text}
                {t.from && <small className="moment__from">{t.from}</small>}
              </span>
            </li>
          ))}
        </ul>
      )}
      <p className="moment__hint">
        {moment === 'found'
          ? saidYes
            ? 'You said yes. Waiting for them…'
            : "Tap your band once to meet · twice to pass. They'll never know."
          : moment === 'mutual'
            ? `Look around for the other light. ${gesture.instruction}`
            : 'Your bands just turned green.'}
      </p>
    </section>
  )
}
