# Wingman — Product & Hackathon Execution PRD v3

**Event:** VexoHacks @ Y Combinator — November 14, 2026  
**Team:** Xiya (Holly) Tang, Will Li  
**Experience:** Ambient + Vision + Voice  
**Hardware:** 1 Vexo Open band + 1 smartphone + 1 laptop  
**AI:** Gemini 4, ElevenLabs, Deepgram, Mastra

---

## 1. Product Vision

### One-liner

**Wingman turns a crowded room into your next meaningful conversation — through a glowing signal, a camera glance, and an AI whisper.**

### Tagline

*Your social intuition, with a pulse.*

Wingman is an ambient AI social copilot that discovers meaningful connections at real-world events and helps people make the first move.

Unlike traditional networking products, Wingman does not require users to browse profiles, rank strangers, or write introductory messages.

It closes the loop between **discovery, navigation, introduction, and connection**.

### Core Product Principles

- **Ambient first:** Opportunities surface without browsing.
- **Intent over identity:** Match what people want now, not just job titles.
- **Mutual value:** Every introduction needs a reason for both people.
- **Physical-world interaction:** The product ends in a human conversation.
- **Consent by design:** Everyone being matched must opt in.
- **Playful, not intrusive:** Technology should reduce social pressure.

---

## 2. Problem Statement

At conferences, hackathons, and professional events, people often miss their most relevant connections.

Existing networking apps have three limitations:

| Problem | Current experience | Wingman |
|---|---|---|
| Discovery | Browse attendee profiles | AI identifies useful connections |
| Navigation | Search manually in a crowded venue | Camera-assisted finding |
| Introduction | Awkward cold opening | Contextual AI icebreaker |
| Follow-up | Forgotten names and context | Optional connection memory |

### Key Insight

**The problem is not a lack of people. It is a lack of context and confidence at the moment of connection.**

The best match is not always the most impressive resume. It may be someone facing the exact problem you solved yesterday.

---

## 3. Target Users & Primary Wedge

### Primary Users

Conference attendees, hackathon participants, startup founders, developers, designers, and people entering unfamiliar professional communities.

### Jobs to Be Done

"When I enter a room full of strangers, help me discover the person I would genuinely benefit from knowing, tell me why, and make approaching them easier."

### Initial Wedge

**AI hackathons and startup networking events.**

People have rapidly changing projects, immediate collaboration needs, and limited time to connect.

### Future Customers

Conference organizers, university alumni networks, startup accelerators, and professional communities.

---

## 4. Core Experience — Seven Moments

### Stage 01 — Join the Room

**Goal:** Establish identity, intent, and consent with minimal friction.

The wearer connects the Vexo band through the laptop console.

A second attendee opens a mobile web page via QR code.

Both provide:

- Name and optional public profile link
- What they are currently working on
- What they are looking for today
- What they can offer
- Whether they are available to meet

The wearer can speak their intent using the Vexo microphone.

Example:

"I'm building an AI healthcare startup and looking for people who know healthcare distribution."

The transcript is converted into a structured, editable `Right Now Profile`.

Public links are optional. Manual input works when external pages cannot be fetched.

**Output:** Two consented, event-scoped profiles.

### Stage 02 — Discover the Match

**Goal:** Find a reason for a valuable two-way conversation.

Gemini compares both profiles using:

1. Current goals and interests
2. Complementary capabilities
3. Shared context
4. Timeliness
5. Evidence confidence

**Example output:**

> "You should meet Xiya. She's building a healthcare AI agent, and you've worked on the distribution problem she's trying to solve."

Each side receives a different explanation based on their own needs.

The system avoids making claims that are not supported by the supplied profiles.

**Output:** Match recommendation, mutual reason, and two conversation openers.

### Stage 03 — Ambient Signal

**Goal:** Alert users without interrupting the event.

The wearer's band pulses purple.

The participant's phone displays a lightweight match notification and vibrates where supported.

Message:

**"Someone here is worth meeting."**

No numeric attractiveness or social ranking is shown.

The user can dismiss or snooze a match.

**Output:** An actionable social opportunity.

### Stage 04 — Find the Person

**Goal:** Turn discovery into physical navigation.

The guest selects **Find Your Match** on their phone.

The camera launches with a minimal visual overlay.

For the hackathon, the wearer uses a consented visual identifier such as a Wingman badge, QR marker, or clearly visible light.

Gemini can interpret consented camera snapshots and provide visual context. A local marker detector handles fast, reliable target confirmation.

Phone feedback:

- Searching: calm scanning animation
- Candidate detected: target halo
- Target confirmed: stronger haptic cue and visual lock
- Lost target: return to scanning

Feedback intensity is based on marker detection confidence or apparent marker size, not inferred GPS distance.

**Output:** The matched participant is visually located.

### Stage 05 — The Spark

**Goal:** Confirm that the people actually met.

The guest approaches the wearer.

The guest gently touches their phone to the consenting wearer's band.

The band emits a `tap` event. The phone detects a motion spike.

The backend compares event timestamps within a calibrated tolerance.

If both signals align:

- Meeting state becomes `confirmed`
- Band LED turns solid green
- Phone scanning stops
- Success animation plays
- ElevenLabs introduction is triggered

If motion sensors are unavailable, the band tap plus an explicit phone confirmation provides a fallback.

This is a playful interaction, not cryptographic proof of physical contact.

**Output:** Confirmed meeting event.

### Stage 06 — The Whisper

**Goal:** Remove the difficulty of the first sentence.

ElevenLabs generates a short spoken introduction.

Guest example:

"Ask Xiya how she's making healthcare AI feel human."

Wearer example:

"He understands healthcare distribution. Ask what hospitals actually buy."

The demo phone delivers the guest's opener. The laptop may deliver the wearer's version through private audio, if configured.

**Output:** A contextual opening that gets the conversation started.

### Stage 07 — Remember the Connection

**Goal:** Preserve the value of the real-world interaction.

After meeting, the attendee may dictate or type one takeaway.

Example:

"We talked about a possible pilot with outpatient clinics."

Wingman turns that explicit note into a follow-up draft.

No message is sent without approval. No conversation recording occurs automatically.

**Output:** An optional personal connection memory.

---

## 5. Physical Interaction System

### Band LED State Machine

| State | LED | Meaning |
|---|---|---|
| Idle | Off / subtle white | Ready, no active alert |
| Listening | Solid blue | Microphone active; firmware-controlled |
| Match found | Purple blinking | A relevant match is available |
| Finding | Purple blinking | The introduction is still pending |
| Confirmed | Solid green | Connection confirmed |
| Snoozed | Off | Notifications temporarily paused |
| Disconnected | Console error state | Requires reconnect |

**Hardware constraint:** The microphone locks the LED to blue. The recording window must end before displaying a match alert.

### Gesture Mapping

| Gesture | Action |
|---|---|
| Single band tap | Confirm or acknowledge, depending on state |
| Double tap | Snooze current introduction |
| Phone-to-band touch | Physical meeting confirmation attempt |
| Spoken self-introduction | Update current intent profile |
| Camera scan | Locate consented match |
| Phone confirmation | Accessible fallback for the physical tap |

Do not overload single taps with contradictory actions in the same state.

### Phone Feedback

Supported Android browsers can use vibration.

If vibration is unavailable, use an animated pulse, sound cue where permitted, and clear visual feedback.

The experience must remain usable without haptics.

---

## 6. Mobile UX

### Screen A — Join Wingman

    WINGMAN

    Who are you hoping to meet today?

    [ LinkedIn or website — optional ]

    I'm currently working on:
    [________________________]

    I would love to meet someone who:
    [________________________]

    [ I'm available to connect ]

    [ FIND MY PEOPLE ]

### Screen B — Match Found

    WINGMAN           ✦

    SOMEONE HERE IS WORTH MEETING

    You share an interest in
    AI-powered healthcare.

    Why you should connect:
    You may be able to help
    each other launch a pilot.

    [ FIND YOUR MATCH ]

    Maybe later

### Screen C — Find Mode

    [ LIVE CAMERA VIEW ]

              ◎
         TARGET FOUND

    Follow the glowing signal.

    [ Target indicator ]
    [ Scanning animation ]

    Move closer to say hello.

### Screen D — The Spark

    ✦ CONNECTION MADE ✦

         [ Green Halo ]

    You found your person.

    Meet Xiya.

    ▶ HEAR YOUR ICEBREAKER

    [ CONTINUE ]

### Screen E — Connection Memory

    YOU MET XIYA

    What did you talk about?

    [ Add a quick note ]

    [ DRAFT A FOLLOW-UP ]

**UX direction:** Editorial, minimal, atmospheric, and premium. Dark background, restrained gradients, circular motion graphics, purple discovery states, green success states. Avoid a traditional networking dashboard or chatbot interface.

---

## 7. AI Agent Architecture

### Profile Agent — Gemini 4

Inputs:

- Opted-in attendee profile
- Optional pasted bio / uploaded public-profile screenshot
- Wearer-authored voice transcript
- Current networking intent

Outputs:

`{ now_focus, looking_for, can_offer, shared_topics, evidence }`

### Match Agent — Gemini 4 + Mastra

Inputs: Two structured attendee profiles.

Outputs:

`{ mutual_fit, reasons_for_each, evidence, uncertainty, opener_for_each }`

The agent should prioritize mutual utility over generic similarity.

### Finder — Gemini 4 Vision + Deterministic Marker Detection

Inputs:

- Explicitly activated camera
- Consented visual reference or marker
- Match session ID

Outputs:

`{ candidate_visible, confidence, approximate_frame_region }`

Fast frame-by-frame confirmation should rely on local marker recognition where possible. Gemini contributes scene interpretation and visual reasoning.

### Whisper Tool — ElevenLabs

Inputs: Approved, evidence-grounded opener text.

Outputs: Short speech suitable for one private interaction.

### Follow-Up Agent — Gemini 4

Inputs: Meeting context and user-written or user-dictated notes.

Outputs: Editable follow-up draft.

---

## 8. System Architecture

    VEXO BAND
    | microphone + tap + LED + motion
    v
    LAPTOP / CHROME CONSOLE
    | Bluetooth + Deepgram
    | WebSocket
    v
    MASTRA BACKEND
    |-- Profile Agent (Gemini 4)
    |-- Match Agent (Gemini 4)
    |-- Finder Tool (Vision)
    |-- Whisper Tool (ElevenLabs)
    |-- Meeting State + Notes
    |
    +----------- WebSocket ----------+
                                      |
                                      v
                                PHONE WEB APP
                                | Camera
                                | Haptics
                                | Motion
                                | Audio

For the hackathon, use in-memory session storage, one active match, and no persistent user-account system.

### Core States

`idle → listening → profiling → matched → finding → meeting_confirmed → whisper → follow_up`

Additional states:

`no_match`, `snoozed`, `permission_denied`, `target_lost`, `band_disconnected`, `expired`

Every stage must have a retry or fallback behavior.

---

## 9. MVP Priorities

| Priority | Feature | Acceptance criteria |
|---|---|---|
| P0 | Real band connection | Connect and receive actual tap events |
| P0 | LED control | Purple alert and green confirmation work |
| P0 | Consent + two profiles | Both participants join one session |
| P0 | Gemini reasoning | Relevant, distinct reasons for each participant |
| P0 | The Spark | Band tap confirms meeting and triggers success |
| P0 | ElevenLabs | Plays an actual generated opener |
| P0 | Phone camera | Opens and confirms a consented target marker |
| P0.5 | Deepgram | Band speech creates the wearer's current-intent profile |
| P1 | Dual-device impact correlation | Matches calibrated band and phone motion |
| P1 | Vision scene reasoning | Gemini processes a real camera snapshot |
| P2 | Follow-up drafting | Generates draft from explicitly entered notes |
| P3 | Continuous ambient discovery | Future multi-user, multi-band product |

**Hard MVP cut line:** One person, one band, one phone, one real match, one physical confirmation, one AI-generated spoken opener.

---

## 10. Privacy, Safety & Trust

- Matching is limited to explicitly opted-in participants.
- The microphone records surrounding speech, not only the wearer. Use short intentional recording windows and provide clear notice.
- A public profile link does not authorize unrestricted collection or scraping.
- The camera runs only when the guest explicitly opens Find Mode.
- Use consented badges or visual markers, not covert face recognition.
- Never reveal sensitive personal details or unsupported inferences in an opener.
- The user can pause matching or withdraw consent.
- Follow-up notes are opt-in; no automatic sharing.
- Session data is deleted after the event.

---

## 11. Demo — Three-Minute Story

**0:00–0:30 — The Problem**

"Look around this room. There might be someone here who could change what you're building. But you don't know who."

**0:30–1:00 — Build a Live Profile**

Xiya introduces what she's currently working on through the Vexo microphone.

Deepgram transcribes. Gemini extracts her immediate goals.

**1:00–1:30 — Find a Match**

The guest submits a short profile on the phone.

Gemini discovers a relevant two-way connection.

Xiya's band begins pulsing purple.

**1:30–2:10 — The Hunt**

The guest launches the camera, finds the visible Wingman marker, and receives visual or haptic confirmation.

**2:10–2:40 — The Spark**

The guest touches the band with the phone.

The band turns green.

ElevenLabs delivers a contextual first line.

**2:40–3:00 — The Closing**

"LinkedIn tells you who someone is. Wingman tells you why you should talk — and helps you actually meet."

---

## 12. Success Metrics

### Technical

- A real hardware event visibly changes the experience.
- Gemini produces an evidence-grounded match.
- Camera detection works in the demo space.
- The confirmation-to-voice flow completes reliably.
- The complete demo can be repeated without manual backend repair.

### Product

- A user understands why they were matched.
- A user can identify the intended person.
- The introduction feels helpful rather than awkward.
- Users would try the experience at another event.

### Product North Star

**Meaningful conversations started per opted-in attendee per event.**

Not impressions, swipes, raw matches, or contacts collected.

---

## 13. Future Vision

### Phase 1 — Hackathons & Conferences
Opt-in social discovery with one wearable and a phone.

### Phase 2 — Wearable-to-Wearable
Mutual matching, reciprocal light signals, private audio, and device-assisted confirmation.

### Phase 3 — Personalized Social Memory
Remember people, follow-ups, shared projects, and changing goals with user control.

### Phase 4 — Ambient Social Intelligence
A context-aware copilot for professional communities, events, and everyday social interactions.

**Long-Term Vision:** An AI that helps people form meaningful real-world relationships without turning social interaction into another app.

---

## 14. Hackathon Build Strategy

**Suggested parallel ownership**

**Xiya — Product, UX, frontend, and demo**
- End-to-end experience and state transitions
- Mobile flow and finder UI
- Consent and live input
- Visual identity and presentation
- Acceptance testing and final demo

**Will — Hardware, backend, and integrations**
- Vexo Bluetooth connection and events
- LED control and microphone flow
- Gemini/Mastra orchestration
- ElevenLabs integration
- WebSocket state synchronization

**Integration checkpoint:** Before polishing the camera experience, confirm that a real band tap triggers an actual spoken opener.

### Submission Definition of Done

A judge can join the experience, receive a real AI recommendation, locate the opted-in wearer, confirm the encounter through the band, and hear a personalized introduction.

The experience succeeds even when advanced spatial inference, continuous listening, or two-device impact correlation are unavailable.

---

## Final Product Statement

**Wingman doesn't help you collect more contacts. It helps you make the connections you would otherwise miss.**
