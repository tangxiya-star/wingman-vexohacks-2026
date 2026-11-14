# Wingman — Product & Hackathon Execution PRD v5 (Dating · Two Bands)

**Event:** VexoHacks @ Y Combinator — November 14, 2026  
**Team:** Xiya (Holly) Tang, Will Li  
**Experience:** Ambient + Voice + Gesture  
**Hardware:** 2 Vexo Open bands + 1 laptop (+ phones as optional companions)  
**AI:** Gemini 4, ElevenLabs, Deepgram, Mastra

---

## 1. Product Vision

### One-liner

**Two bands light up when two people's values match. Find each other across the room, make the same gesture together, and the light turns green. No swiping, no photos.**

### Tagline

*Values first. Then you meet.*

Wingman is an offline-first AI dating copilot. At real-world events, it matches people on what actually lasts — values, lifestyle, what they want in a relationship — instead of photos. When two people match, their bands glow the same color, and they find each other by the light.

Dating apps end at a match. **Wingman ends at a real conversation.**

### Core Product Principles

- **Offline first:** The product ends in a face-to-face conversation, not a chat thread.
- **Values over looks:** Matching never uses photos or appearance.
- **Mutual yes:** Nobody is pursued unless both people agree first.
- **Symmetric:** Nobody "hunts" anybody. Two people find each other.
- **Reasons, not scores:** Every match explains *why* you fit. No ratings.
- **Ambient, not addictive:** No feed, no swiping — just a light on your wrist.

---

## 2. Problem Statement

**1. Everything happens online, and nothing follows through.**
People swipe, match, chat for a few days, and never meet.

**2. Matching is based on looks, not on what actually matters.**
A swipe is decided by a photo in half a second. Nobody knows whether two people share the same values or life goals — the things that decide whether a relationship works.

| Problem | Dating apps today | Wingman |
|---|---|---|
| Discovery | Swipe through photos | AI matches on values, no photos |
| Signal | Endless notifications | Your band glows when it matters |
| Meeting | Weeks of chat, often never | Look up, find the matching light, walk over |
| First line | "hey" | A personal opener based on what you share |
| Follow-through | Ghosting | Both people choose to stay in touch |

### Key Insight

**The best person for you might be ten feet away. What's missing is a reason to walk over — and the confidence to say the first sentence.**

---

## 3. Target Users & Primary Wedge

**Users:** Singles aged 22–35 who are tired of dating apps, want to meet in real life, and care more about compatibility than looks.

**Job to be done:** "When I'm at an event full of strangers, show me who shares my values, tell me they're open to meeting too, and make walking over feel natural."

**Wedge:** Singles mixers, community events, and social nights at hackathons and universities. Hosts hand out bands at the door.

**Future customers:** Event hosts, singles-event organizers, run clubs, universities, venues.

---

## 4. Core Experience — Six Moments

### Stage 01 — Join the Room

Each person puts on a band and tells Wingman who they are — by speaking into the band for ~30 seconds, or by answering on their phone:

- What does a perfect weekend look like?
- What matters most to you right now?
- What are you looking for? (something serious / open to see / new friends)
- One thing you can't compromise on.

**No photos are collected.** Each person consents to being matched at this event.

**Output:** Two consented values profiles, each tied to a band.

### Stage 02 — The Glow (Match)

Gemini compares the profiles on core values, lifestyle, relationship intent (must be compatible), and dealbreakers (any conflict blocks the match).

When there's a real fit, **both bands start a slow purple glow.**

Each person can see *why* on their phone or the console:

> "You both put family first, you'd both rather spend Saturday on a trail than at a club, and you're both looking for something real."

No compatibility percentage is shown.

### Stage 03 — Mutual Yes

- **Single tap** on your band = I'm open to meeting
- **Double tap** = pass — your band turns off

When **both** people tap yes, both bands switch to a **fast purple blink**: you're both looking for each other now.

If either person passes, or nobody responds in 2 minutes, both bands simply turn off. A pass looks exactly like a match that expired — nobody knows they were declined.

### Stage 04 — Find Each Other

No camera, no map. Look around the room. **Only two bands are blinking the same purple — yours and theirs.**

You walk toward each other. The light keeps blinking until you meet.

### Stage 05 — The Spark (Same Gesture)

**A match only counts when both people make the same gesture at the same time.**

When the two people meet, they face each other and make the match gesture together. Each band's motion sensor (accelerometer + gyroscope) recognizes the gesture. The backend confirms that:

1. Both bands detected **the same gesture**, and
2. The two gestures happened **within ~1 second** of each other.

When confirmed:

- **Both bands stop blinking and turn solid green**
- The console / phones show **"You found each other."**
- ElevenLabs speaks a personal opener for each person

Why a shared gesture:

- **It's a mutual act.** One person can't confirm a match alone — it takes both, in sync. It's the physical version of "we both said yes."
- **No touching required.** Nobody has to make physical contact with a stranger.
- **It's a moment.** Two people mirroring each other is a natural icebreaker and reads beautifully on stage.

**The match gesture is TBD — chosen after testing what the Vexo band can reliably detect.** Criteria:

1. Clearly distinguishable in the motion data from everyday movement (walking, drinking, talking, checking a phone)
2. Two different people produce similar motion curves, so "same gesture" can be judged
3. Looks cool in a flirty moment — no touching, nothing cheesy

Candidates to test include wrist flick, wrist twist, finger snap, and "showing" the band. Future versions can assign a random "secret gesture" to each match.

The blinking only stops when you both make the gesture — or when you choose to pass. Fallback if gesture detection is unreliable: both bands tapped within ~1 second.

### Stage 06 — The Whisper & Stay in Touch

ElevenLabs speaks a short opener built on shared values:

- To guest: "Ask Holly about the best hike she's ever done — you both live for weekends outside."
- To Holly: "He just moved here and wants something real. Ask him what he misses most about home."

After talking, each person privately chooses whether to stay in touch. Both yes → contacts are exchanged plus a second-date idea. Otherwise nothing is shared, and nobody learns who said no.

---

## 5. Physical Interaction System

### Hardware capabilities (current)

| Capability | Available | Used for |
|---|---|---|
| LED | Yes | All signals |
| Tap detection | Yes | Yes / pass / the Spark |
| Microphone | Yes | Spoken values profile |
| Motion (accelerometer + gyroscope) | Yes | **The Spark — recognizing the shared match gesture** |
| Vibration | **Not yet** | Future: haptic nudge when matched |

### Band LED State Machine (both bands mirror each other)

| State | LED | Meaning |
|---|---|---|
| Idle | Off / subtle white | Ready |
| Listening | Solid blue | Microphone active; firmware-controlled |
| Matched | **Slow purple glow** | Someone here shares your values — tap to say yes |
| Waiting | Slow purple glow | You said yes; waiting on them (looks the same on purpose) |
| Mutual / Finding | **Fast purple blink** | You both said yes — find the other light |
| Confirmed | **Solid green** | You met |
| Passed / Expired / Hidden | Off | No active match |
| Disconnected | Console error | Requires reconnect |

**Hardware constraint:** The microphone locks the LED to blue. Recording must finish before matching starts.

### Gesture Mapping

| State | Gesture | Action |
|---|---|---|
| Matched | Single tap | Yes |
| Matched | Double tap | Pass |
| Mutual | **Both people make the same gesture within ~1s** | The Spark |
| Mutual | Only one person gestures, or gestures differ | Ignored — keep blinking |
| Mutual | Both bands tapped within ~1s | Spark fallback |
| Mutual | Double tap | Leave — both bands turn off |
| Any | Spoken intro | Update values profile |

---

## 6. Companion Phone UX (optional, per person)

The bands carry the core experience. The phone page (QR code, `?band=A` or `?band=B`) is a companion for reading and listening.

### Screen A — Join

    WINGMAN
    No photos. Just you.

    A perfect weekend looks like:   [__________]
    What matters most right now:    [__________]
    I'm looking for:  ( serious ) ( open ) ( friends )
    One thing I can't compromise on: [__________]

    [ ✓ I agree to be matched at this event ]
    [ JOIN ]

### Screen B — Glow

    YOUR BAND IS GLOWING ✦

    Someone here shares your values.

    You both put family first.
    You'd both pick a trail over a club.
    You both want something real.

    Tap your band once to say yes.
    Double tap to pass.

### Screen C — Find

    ✦ YOU BOTH SAID YES ✦

    Look around for the other purple light.
    When you meet, make the gesture
    together. [ gesture animation ]

### Screen D — The Spark

    ✦ YOU FOUND EACH OTHER ✦
         [ Green Halo ]
    Meet Holly.
    ▶ HEAR YOUR OPENER

### Screen E — Stay in Touch

    Want to stay in touch?
    [ YES ]   No thanks

**UX direction:** Warm, editorial, intimate, premium. Dark background, soft gradients, circular motion, purple for discovery, green for connection. Nothing that looks like a swipe deck.

---

## 7. AI Agent Architecture

### Profile Agent — Gemini 4
Inputs: values answers or spoken transcript. Outputs: `{ core_values, lifestyle, relationship_intent, dealbreakers, about, evidence }`

### Match Agent — Gemini 4 + Mastra
Inputs: two values profiles. Outputs: `{ compatible, shared_values, reasons_for_each, evidence, uncertainty, opener_for_each }`

Rules: relationship intent must be compatible; any dealbreaker conflict → no match; prioritize deep values over surface interests; never use or infer appearance; sensitive traits only if the person wrote them as values; no scores.

### Gesture Recognizer — deterministic, on each band's motion stream
Inputs: accelerometer + gyroscope samples from each band. Output: `{ gesture: <gesture_id>, confidence, ts }` (gesture set TBD after hardware test). Rule-based thresholds, calibrated on site with both wearers — no ML training needed for the hackathon.

### Spark Detector — deterministic
Inputs: gesture events from band A and band B. Output: confirmed when both bands report **the same gesture** within the tolerance window during `mutual`. Fallback: two taps within the window.

### Whisper Tool — ElevenLabs
Inputs: evidence-grounded openers. Outputs: two short audio clips.

### Follow-Through Agent — Gemini 4
Inputs: shared values (only when both chose to stay in touch). Output: one second-date idea.

---

## 8. System Architecture

    BAND A          BAND B
      |  LED + tap + mic  |
      +--------+---------+
               | Web Bluetooth (one laptop; fallback: one laptop per band)
               v
       LAPTOP / CHROME CONSOLE
       | Deepgram (spoken profiles)
       | WebSocket
               v
         MASTRA BACKEND
         |-- Profile Agent (Gemini 4)
         |-- Match Agent (Gemini 4)
         |-- Spark Detector
         |-- Whisper Tool (ElevenLabs)
         |-- Consent + Session State
               |
               | WebSocket
               v
       PHONE COMPANION PAGES (optional)
       | Join form · reasons · opener audio · stay in touch

Hackathon scope: in-memory session, two bands, one active match, no accounts.

### Core States

`idle → profiling → matched → mutual → meeting_confirmed → whisper → stay_in_touch`

Additional: `no_match`, `passed`, `expired`, `hidden`, `band_disconnected`

Every stage has a retry or fallback.

---

## 9. MVP Priorities

| Priority | Feature | Acceptance criteria |
|---|---|---|
| P0 | Connect both bands | Receive real tap events from A and B at the same time |
| P0 | LED control on both | Slow glow, fast blink, green, off all work on both |
| P0 | Values profiles + consent | Two profiles, no photos |
| P0 | Gemini values matching | Distinct, evidence-grounded reasons for each side |
| P0 | Mutual yes | Both single taps required before fast blink |
| P0 | Gesture recognition | Each band recognizes the chosen match gesture from motion data |
| P0 | The Spark | Same gesture on both bands within ~1s turns both green (tap fallback works) |
| P0 | ElevenLabs | Plays an actual generated opener |
| P0.5 | Deepgram | Spoken intro builds a values profile |
| P1 | Phone companion pages | Reasons + opener on each person's phone |
| P1 | More gestures | A second gesture recognized; random "secret gesture" per match |
| P1 | Stay in touch | Mutual contact exchange + second-date idea |
| P2 | Room view | Big-screen view of both bands' states for the audience |
| Future | Vibration | Haptic nudge when matched, once firmware supports it |

**Hard MVP cut line:** Two bands, one values match, one mutual yes, one shared gesture, both turn green, one AI-spoken opener.

---

## 10. Privacy, Safety & Trust

- Only explicitly opted-in people can be matched.
- **Mutual yes before anyone looks for anyone.** A pass looks the same as an expired match.
- You can always stop the light by yourself (double tap). Confirming a match never requires touching anyone — it's a shared gesture.
- No photos, no face recognition, no camera, no location sharing.
- The microphone may capture nearby speech: short, intentional recording windows with clear notice.
- One-tap **Hide** on the console or phone removes you from matching.
- Contact info is shared only if both people choose to stay in touch.
- Designed for public venues and hosted events.
- All session data is deleted after the event.

---

## 11. Demo — Three-Minute Story

Holly wears band A. A judge (or Will) wears band B.

**0:00–0:30 — The Problem**
"We swipe on hundreds of photos and almost never meet. And when we do, we find out in five minutes that our values don't match."

**0:30–1:00 — Values, not photos**
Holly speaks into her band about what matters to her. The judge answers four questions on a phone. No photos.

**1:00–1:40 — The Glow**
Gemini finds a real fit. **Both bands start glowing purple.** The reasons appear on screen. Holly taps once. The judge taps once. Both bands switch to a fast blink.

**1:40–2:10 — Find each other**
Holly and the judge stand on opposite sides. Only two lights in the room are blinking purple. They walk toward each other.

**2:10–2:40 — The Spark**
Face to face, they make the match gesture together. **Both bands turn green at the same moment.** ElevenLabs speaks an opener built on what they share.

**2:40–3:00 — The Closing**
"Dating apps end at a match. Wingman ends at a real conversation — with someone who actually shares your values."

---

## 12. Success Metrics

**Technical:** both bands respond to real events; Gemini produces an evidence-grounded match; mutual yes gates the blink every time; the shared gesture is recognized on both bands and turns them green reliably (and a single person's gesture never does); the full demo repeats without backend repair.

**Product:** users understand why they matched; nobody felt pursued without agreeing; the opener made starting easier; users would come to another Wingman event.

**North Star:** Real conversations that turn into a second meeting.

---

## 13. Future Vision

- **Phase 1 — Hosted events:** Bands handed out at singles mixers and community nights.
- **Phase 2 — Haptics & private audio:** Vibration nudges and in-ear openers once the hardware supports them.
- **Phase 3 — Everyday serendipity:** Opt-in matching at cafés, run clubs, venues — still mutual yes, still offline first.
- **Phase 4 — Relationship memory:** Remember who you met and help plan the second date, with full user control.

**Long-Term Vision:** Bring dating back into the real world — matched on who people are, not how they look.

---

## 14. Hackathon Build Strategy

**Holly — Product, UX, frontend, and demo**
- Phone companion pages (join, glow, find, spark, stay in touch)
- Room view for the audience
- Visual identity, copy, and presentation
- Acceptance testing and final demo

**Will — Hardware, backend, and integrations**
- Connect both Vexo bands, tap events, LED control
- Motion streaming + gesture recognition, Spark detection from two bands
- Microphone + Deepgram profiles
- Gemini/Mastra values matching, ElevenLabs
- WebSocket state and consent logic

**Integration checkpoint 0 (do first):** Test which gestures the band can reliably detect, then pick the match gesture.

**Integration checkpoint 1:** Both bands connected; tapping both at once turns both green and plays a spoken opener.

**Integration checkpoint 2:** Motion data streams from both bands; the chosen match gesture is recognized on each; doing it together replaces the tap.

### Submission Definition of Done

A judge puts on a band, answers a few values questions, sees both bands glow with a real reason, both tap yes, they find each other by the light, make the same gesture together, both turn green, and the judge hears a personal opener.

---

## Final Product Statement

**Wingman doesn't help you swipe more. It lights the way to the person who actually fits — in real life.**
