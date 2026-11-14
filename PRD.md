# Wingman — Product & Hackathon Execution PRD v4 (Dating)

**Event:** VexoHacks @ Y Combinator — November 14, 2026  
**Team:** Xiya (Holly) Tang, Will Li  
**Experience:** Ambient + Vision + Voice  
**Hardware:** 1 Vexo Open band + 1 smartphone + 1 laptop  
**AI:** Gemini 4, ElevenLabs, Deepgram, Mastra

---

## 1. Product Vision

### One-liner

**Wingman finds the person in the room who shares your values — and walks you all the way to the first hello. No swiping.**

### Tagline

*Values first. Then you meet.*

Wingman is an offline-first AI dating copilot. At real-world events, it matches people on what actually lasts — values, lifestyle, what they want in a relationship — instead of photos, then helps both people physically meet and start talking.

Dating apps end at a match. **Wingman ends at a real conversation.**

### Core Product Principles

- **Offline first:** The product ends in a face-to-face conversation, not a chat thread.
- **Values over looks:** Matching never uses photos or appearance.
- **Mutual yes:** Nobody can be found unless both people agree first.
- **Reasons, not scores:** Every match explains *why* you two fit. No ratings, no rankings.
- **Ambient, not addictive:** No feed, no swiping, no endless browsing.
- **Safe by design:** Public venues, consent at every step, one-tap hide.

---

## 2. Problem Statement

Two things are broken about dating apps today:

**1. Everything happens online, and nothing follows through.**
People swipe, match, chat for a few days, and never meet. The match is the end of the experience, not the beginning of a relationship.

**2. Matching is based on looks, not on what actually matters.**
A swipe takes half a second and is decided by a photo. Nobody knows whether two people share the same values, life goals, or way of seeing the world — the things that decide whether a relationship works.

| Problem | Dating apps today | Wingman |
|---|---|---|
| Discovery | Swipe through photos | AI matches on values, no photos |
| Signal | Endless notifications | One glowing pulse when it matters |
| Meeting | Weeks of chat, often never | Walk over now, in the same room |
| First line | "hey" | A personal opener based on what you share |
| Follow-through | Ghosting | Both people choose to stay in touch |

### Key Insight

**The best person for you might be ten feet away. What's missing is a reason to walk over — and the confidence to say the first sentence.**

---

## 3. Target Users & Primary Wedge

### Primary Users

Singles aged 22–35 who are tired of dating apps, want to meet people in real life, and care more about compatibility than looks.

### Jobs to Be Done

"When I'm at an event full of strangers, help me find the person whose values match mine, let me know they're open to meeting too, and make walking over feel natural."

### Initial Wedge

**Singles mixers, community events, and social nights at hackathons and universities.**

Everyone is already in one room, already open to meeting people, and short on a reason to start.

### Future Customers

Event hosts, singles-event organizers, run clubs, university communities, and venues that want guests to actually connect.

---

## 4. Core Experience — Seven Moments

### Stage 01 — Join the Room

**Goal:** Capture who someone is underneath the surface, with clear consent.

The wearer connects the Vexo band through the laptop console. A guest opens the mobile web page via QR code.

Both answer a few short values questions:

- What does a perfect weekend look like for you?
- What matters most to you in life right now?
- What are you looking for? (something serious / open to see / new friends)
- One thing you can't compromise on.
- Optional: one sentence about yourself.

**No photos are collected.**

The wearer can also speak for 30 seconds through the Vexo microphone:

"I'm happiest outdoors, family comes first for me, and I want someone who's curious and doesn't take themselves too seriously."

The transcript becomes an editable `Values Profile`.

**Output:** Two consented, event-scoped values profiles.

### Stage 02 — Discover the Match

**Goal:** Find two people whose values genuinely fit.

Gemini compares both profiles on:

1. Core values and priorities
2. Lifestyle (how they spend time, energy level)
3. Relationship intent — must be compatible
4. Dealbreakers — any conflict blocks the match
5. Evidence confidence

**Example output:**

> "You both put family first, you'd both rather spend Saturday on a trail than at a club, and you're both looking for something real."

Each side receives a reason written for them. The system never claims anything not supported by what each person wrote. No compatibility percentage is shown.

**Output:** Match recommendation, shared values, and two openers.

### Stage 03 — Mutual Yes

**Goal:** Make sure both people want to meet before anyone is found.

The guest's phone shows: **"Someone here shares your values."** with the reasons, and asks: *Want to meet?*

The wearer's band pulses purple. The wearer can see the reasons on the console.

- Wearer: **single tap** on the band = yes, **double tap** = pass
- Guest: **Yes / Not now** on the phone

**Only when both say yes** does Find Mode unlock. If either passes, the other is simply told there's no match right now — never that they were declined.

**Output:** A mutual, consented intent to meet.

### Stage 04 — The Hunt

**Goal:** Turn a match into walking over.

The guest taps **Find Them**. The camera opens with a minimal overlay.

The wearer carries a consented visual marker — a Wingman badge or QR marker. A local marker detector confirms the target fast; Gemini can optionally interpret a snapshot for context.

- Searching: calm scanning animation
- Candidate detected: target halo
- Target confirmed: haptic cue + visual lock
- Lost: return to scanning

No face recognition. No location sharing.

**Output:** The match is visually located.

### Stage 05 — The Spark

**Goal:** Mark the moment two people actually meet.

The guest walks over and touches their phone to the wearer's band.

The band emits a `tap` event; the phone detects a motion spike. The backend checks the timestamps line up.

When confirmed:

- Band LED turns solid green
- Phone shows a success animation: **"You found each other."**
- ElevenLabs opener is triggered

Fallback: band tap + explicit phone confirmation.

**Output:** Confirmed meeting.

### Stage 06 — The Whisper

**Goal:** Remove the pressure of the first sentence.

ElevenLabs speaks a short, personal opener built on shared values.

Guest example:

"Ask Holly about the best hike she's ever done — you both live for weekends outside."

Wearer example:

"He just moved here and is looking for something real. Ask him what he misses most about home."

Openers never mention appearance and never reveal anything the person didn't write.

**Output:** A natural first line.

### Stage 07 — Stay in Touch

**Goal:** Turn the meeting into follow-through — only if both want it.

After talking, each person privately answers: *Want to stay in touch?*

- Both yes → contact info is exchanged, and Wingman suggests a second-date idea based on shared interests ("You both love hiking — try the Lands End trail this weekend.")
- Otherwise → nothing is shared, and nobody is told who said no.

Each person can also save a private note for themselves.

**Output:** Real follow-through, by mutual choice.

---

## 5. Physical Interaction System

### Band LED State Machine

| State | LED | Meaning |
|---|---|---|
| Idle | Off / subtle white | Ready |
| Listening | Solid blue | Microphone active; firmware-controlled |
| Match found | Purple blinking | Someone here shares your values — tap to say yes |
| Mutual yes / Finding | Purple slow pulse | They're on their way to find you |
| Confirmed | Solid green | You met |
| Hidden | Off | Not visible to matching |
| Disconnected | Console error state | Requires reconnect |

**Hardware constraint:** The microphone locks the LED to blue. The recording window must end before a match alert.

### Gesture Mapping

| State | Gesture | Action |
|---|---|---|
| Match found | Single tap | Yes, I want to meet |
| Match found | Double tap | Pass |
| Finding | Phone-to-band touch | The Spark — confirm meeting |
| Any | Spoken intro | Update values profile |
| Any (console) | Hide | Leave matching immediately |

### Phone Feedback

Vibration on supported Android browsers; animated pulse and sound cue otherwise. The experience must work without haptics.

---

## 6. Mobile UX

### Screen A — Join

    WINGMAN

    No photos. Just you.

    A perfect weekend looks like:
    [________________________]

    What matters most to you right now:
    [________________________]

    I'm looking for:
    ( something serious ) ( open to see ) ( new friends )

    One thing I can't compromise on:
    [________________________]

    [ ✓ I agree to be matched at this event ]

    [ FIND MY PERSON ]

### Screen B — Match Found

    WINGMAN           ✦

    SOMEONE HERE SHARES
    YOUR VALUES

    You both put family first.
    You'd both pick a trail over a club.
    You both want something real.

    Want to meet?

    [ YES ]        Not now

### Screen B2 — Waiting

    ✦

    Waiting for them to say yes…

    (If they pass: "No match right now. We'll keep looking.")

### Screen C — The Hunt

    [ LIVE CAMERA VIEW ]

              ◎
         FOUND THEM

    Look for the glowing badge.

    [ I found them ]

### Screen D — The Spark

    ✦ YOU FOUND EACH OTHER ✦

         [ Green Halo ]

    Meet Holly.

    ▶ HEAR YOUR OPENER

    [ CONTINUE ]

### Screen E — Stay in Touch

    YOU MET HOLLY

    Want to stay in touch?

    [ YES ]        No thanks

    (Both yes → contact exchanged + a second-date idea)

**UX direction:** Warm, editorial, intimate, premium. Dark background, soft gradients, circular motion, purple for discovery, green for connection. Nothing that looks like a swipe deck.

---

## 7. AI Agent Architecture

### Profile Agent — Gemini 4

Inputs: values answers, optional spoken intro transcript.

Outputs: `{ core_values, lifestyle, relationship_intent, dealbreakers, about, evidence }`

### Match Agent — Gemini 4 + Mastra

Inputs: two values profiles.

Outputs: `{ compatible, shared_values, reasons_for_each, evidence, uncertainty, opener_for_each }`

Rules:

- Relationship intent must be compatible.
- Any dealbreaker conflict → no match.
- Prioritize deep values over surface interests.
- Never use or infer appearance, race, religion, or other sensitive traits unless the person explicitly wrote it as a value.

### Finder — Local Marker Detection (+ optional Gemini Vision)

Inputs: explicitly opened camera, consented marker, session ID.

Outputs: `{ candidate_visible, confidence, approximate_frame_region }`

### Whisper Tool — ElevenLabs

Inputs: approved, evidence-grounded opener. Outputs: short speech.

### Follow-Through Agent — Gemini 4

Inputs: shared values and interests (only when both chose to stay in touch).

Outputs: one second-date suggestion.

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
    |-- Finder Tool
    |-- Whisper Tool (ElevenLabs)
    |-- Consent + Meeting State
    |
    +----------- WebSocket ----------+
                                      |
                                      v
                                PHONE WEB APP
                                | Camera
                                | Haptics
                                | Motion
                                | Audio

Hackathon scope: in-memory session, one active match, no accounts.

### Core States

`idle → listening → profiling → matched → mutual → finding → meeting_confirmed → whisper → stay_in_touch`

Additional states: `no_match`, `passed`, `hidden`, `permission_denied`, `target_lost`, `band_disconnected`, `expired`

Every stage has a retry or fallback.

---

## 9. MVP Priorities

| Priority | Feature | Acceptance criteria |
|---|---|---|
| P0 | Real band connection | Connect and receive actual tap events |
| P0 | LED control | Purple alert and green confirmation work |
| P0 | Values profiles + consent | Both participants join one session, no photos |
| P0 | Gemini values matching | Distinct, evidence-grounded reasons for each side |
| P0 | Mutual yes | Band tap + phone yes both required before Find Mode |
| P0 | The Spark | Band tap confirms meeting and triggers success |
| P0 | ElevenLabs | Plays an actual generated opener |
| P0 | Phone camera | Opens and locks onto a consented marker |
| P0.5 | Deepgram | Spoken intro builds the wearer's values profile |
| P1 | Dual-device impact correlation | Band and phone motion line up |
| P1 | Stay in touch | Mutual contact exchange + second-date idea |
| P3 | Multi-person, multi-band rooms | Future |

**Hard MVP cut line:** One band, one phone, one values match, one mutual yes, one physical meeting, one AI-spoken opener.

---

## 10. Privacy, Safety & Trust

- Only explicitly opted-in people can be matched.
- **Mutual yes before anyone can be found.** Nobody is ever told they were passed on.
- No photos are collected or used for matching.
- No face recognition — only a marker the wearer chooses to carry.
- No location is shared; finding only works in the same room.
- The camera runs only after a mutual yes and only when the guest opens it.
- The microphone may capture nearby speech: short, intentional recording windows with clear notice.
- One-tap **Hide** removes you from matching instantly.
- Contact info is shared only if both people choose to stay in touch.
- Designed for public venues and hosted events.
- All session data is deleted after the event.

---

## 11. Demo — Three-Minute Story

**0:00–0:30 — The Problem**

"We swipe on hundreds of photos and almost never meet. And when we do, we find out in five minutes that our values don't match. What if it worked the other way around?"

**0:30–1:00 — Values Profile**

Holly speaks into the Vexo band about what matters to her. Deepgram transcribes; Gemini extracts her values. No photo.

**1:00–1:40 — Match + Mutual Yes**

The guest answers the values questions on the phone. Gemini finds a real fit and explains why. Holly's band pulses purple. Holly taps the band — yes. The guest taps yes.

**1:40–2:10 — The Hunt**

The guest opens the camera and finds Holly's glowing badge.

**2:10–2:40 — The Spark**

The guest touches the band with the phone. The band turns green. ElevenLabs speaks an opener built on what they share.

**2:40–3:00 — The Closing**

"Dating apps end at a match. Wingman ends at a real conversation — with someone who actually shares your values."

---

## 12. Success Metrics

### Technical

- A real hardware event visibly changes the experience.
- Gemini produces an evidence-grounded values match.
- Mutual yes gates Find Mode every time.
- Camera detection works in the demo space.
- The full demo repeats without manual backend repair.

### Product

- Users understand *why* they were matched.
- Users feel safe — nobody felt "hunted" without agreeing.
- The opener made starting the conversation easier.
- Users would come to another Wingman event.

### Product North Star

**Real conversations that turn into a second meeting.**

Not swipes, not matches, not messages sent.

---

## 13. Future Vision

### Phase 1 — Hosted Events
Values matching at singles mixers and community nights with one band and a phone.

### Phase 2 — Band-to-Band
Both people wear bands: reciprocal glow, private audio openers, device-confirmed meetings.

### Phase 3 — Everyday Serendipity
Opt-in matching at cafés, run clubs, and venues — still mutual yes, still offline first.

### Phase 4 — Relationship Memory
Remember who you met, what you shared, and help plan the second date — with full user control.

**Long-Term Vision:** Bring dating back into the real world — matched on who people are, not how they look.

---

## 14. Hackathon Build Strategy

**Holly — Product, UX, frontend, and demo**
- End-to-end experience and state transitions
- Values questions, match, mutual yes, hunt, spark screens
- Consent and safety UX
- Visual identity and presentation
- Acceptance testing and final demo

**Will — Hardware, backend, and integrations**
- Vexo Bluetooth connection and tap events
- LED control and microphone flow
- Gemini/Mastra values matching
- ElevenLabs integration
- WebSocket state and consent logic

**Integration checkpoint:** Before polishing the camera, confirm a real band tap triggers an actual spoken opener.

### Submission Definition of Done

A judge answers a few values questions, gets a real AI match with reasons, both sides say yes, the judge finds the wearer, confirms the meeting through the band, and hears a personal opener.

---

## Final Product Statement

**Wingman doesn't help you swipe more. It helps you meet the person who actually fits — in real life.**
