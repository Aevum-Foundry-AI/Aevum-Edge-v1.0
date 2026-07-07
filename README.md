# Aevum Edge
 
**A privacy-first wearable that senses at the edge, reasons in the cloud with a Qwen agent, and acts locally, without ever making a diagnosis.**
> Qwen Cloud Global AI Hackathon · **Track 5: EdgeAgent** · by [Aevum Foundry AI Ltd](https://aevumfoundry.ai)
 
![Aevum Edge](proj-thumbnail.png)
 
Aevum Edge is a screenless, wrist-worn wellbeing-sensing node. Low-cost sensors read your body and your surroundings; the device extracts features **on-device**, and a **Qwen agent** running on Alibaba Cloud interprets them against *your own baseline* to return a gentle, explainable wellbeing nudge. Raw sensor data never leaves the wrist, consent is enforced fail-closed, and the system keeps working, on a simpler local rule, when the network drops.
 
It deliberately **never diagnoses**. It tells you whether your signals are **steady**, worth a **watch**, or **elevated** versus your baseline, explains why in plain language, and, if something is persistently off, signposts you to a real professional. It never names or infers a condition, and never tries to treat one you've declared.
 
Underneath the engineering is a simpler idea: a good wellbeing device gives you a way to be understood when you cannot find the words. That matters for anyone on a hard day, and most of all for children and teens with **SEND** (Special Educational Needs and Disabilities). Read with a trusted adult, with consent, the same three states become the child's own signpost, a live feelings card a teacher can read to adapt the lesson and the day. See [the trusted-adult view](#the-trusted-adult-view-the-send-signpost) below.
 
---
 
## Why it fits EdgeAgent
 
| Track requirement                | How Aevum Edge does it                                                                                                        |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| **Perceive** via edge sensors    | PPG (heart rate), motion (accelerometer/gyro), skin-contact temperature and ambient temp/humidity over one I²C bus                     |
| **Reason** via cloud APIs        | A **Qwen `qwen3.7-plus` agent** on Alibaba Cloud plans, calls specialised tools, grounds itself with retrieval, remembers your baseline, and synthesises a structured wellbeing flag |
| **Act** locally                  | The device surfaces the flag and nudge; an on-device rule keeps acting when offline                                                    |
| **Privacy-aware data handling**  | Only **derived features** leave the device; **fail-closed consent gate**; stateless backend; no identity logged                       |
| **Graceful offline degradation** | If Wi-Fi or the cloud is unavailable, the device falls back to a transparent local threshold rule and never goes dark                  |
 
---
 
## The Agent: not a single call
 
The cloud core is a real **agent**, not one LLM request. A Qwen orchestrator runs a **plan, act, synthesise** loop (ReAct-style): it decides which specialised tools to call, chains them, grounds itself in retrieval, remembers your baseline, asks a clarifying question when it is genuinely unsure, and is bounded by a diagnosis-free safety layer. **Every tool call is logged. The trace is the evidence that it reasons, rather than merely responds.**
 
```
features ─▶ consent gate (fail-closed) ─▶ baseline / memory ─▶ Qwen orchestrator ─▶ diagnosis-free scrub ─▶ read
                                                              │  plans + calls tools (ReAct loop)
                                                              ▼
   compute_cardiac_features · analyse_movement · thermal_context
   compare_to_baseline · retrieve_wellbeing_context (RAG) · safety_signpost
```
 
- **`compute_cardiac_features`**: heart rate + pulse-rate variability, **gated on stillness** (PPG variability is motion-sensitive, so it is only trusted when the device reports you were still).
- **`analyse_movement`**: two-stage: recognise the activity (rest / walk / active), *then* describe movement quality (cadence, regularity, steadiness) and any fall flag.
- **`thermal_context`**: skin-contact versus ambient temperature difference.
- **`compare_to_baseline`**: z-scores versus *your own* rolling baseline, the memory pattern that makes "vs your baseline" rigorous rather than rhetorical.
- **`retrieve_wellbeing_context`**: retrieval over a licence-clean wellbeing knowledge base, so advice is grounded, not invented.
- **`safety_signpost`**: decides whether to prompt you to see a professional (escalation, never a diagnosis).
Two governing guards wrap the loop: **fail-closed consent** (no valid token, no processing) and a **diagnosis-free scrubber** that neutralises any output drifting toward naming or inferring a condition.
Beyond the sensors, a reading can carry a little situational context: the weather where you are, any moods or notes you have logged, how recovered you feel today. The agent folds that into the guidance it grounds from the knowledge base, so the same body signals read differently on a warm day than a cold one, hydration and electrolytes when it is hot, keeping warm and moving when it is not. It is context, not a diagnosis, used the way a thoughtful friend would use it.
 
**Measured, not asserted** (run `backend/prove/metrics.py`):
 
- **~33× data minimisation**: a raw PPG + motion window is ~8 KB; the derived payload that actually leaves the wrist is ~240 bytes.
- **Sub-millisecond offline fallback**: the on-device rule returns instantly with no network and no model.
- **Personalisation**: the *same* readings produce *different* flags against two different baselines (e.g. HR 82 / HRV 30 reads **steady** for an athlete, **elevated** for a calm baseline).
---
 
## Architecture
 
![Architecture, device at the edge, Qwen agent in the cloud](docs/architecture.png)
 
In brief:
 
```
┌─────────────────────── on the wrist (XIAO ESP32-S3) ───────────────────────┐
│  MAX30102 ─┐                                                                │
│  MPU-6050 ─┼─ I²C · 3.3 V ─►  feature extraction ─► consent gate ─► POST    │
│  BME280  ──┘                  (HR, motion, temps)   (fail-closed)  features │
│                                       ▲                              │      │
│                              offline? └── local fallback rule ◄──────┘      │
└────────────────────────────────────────────────────────────────────│───────┘
                       derived features + personal context (consented)│ HTTPS
                                                                       ▼
┌──────────────────────────── Alibaba Cloud (ECS) ───────────────────────────┐
│  FastAPI ─► the Agent  (Qwen qwen3.7-plus via the DashScope API)   │
│            orchestrator · 6 tools · RAG · per-user memory · safety layer     │
│            diagnosis-free system prompt + server-side scrubber               │
└─────────────────────────────────────────────────────────────────────────────┘
                                                                       │
                                       status · nudge · explanation    ▼
                                                       companion app + the wrist
```
 
The reasoning runs on the **hosted Qwen Cloud API** on Alibaba Cloud, the base URL is visible in [`backend/agent/client.py`](backend/agent/client.py). Deployment is on **Alibaba Cloud ECS**; see [`backend/DEPLOY.md`](backend/DEPLOY.md).
 
---
 
## The companion app
 
The wearable is screenless; a companion phone app handles personalisation and the human-readable side.
 
**Onboarding & profile** (one-time, editable): height, weight, age range; activity frequency, type and intensity; diet type, patterns and hydration; any physical or mental health context you *choose* to share (per-category consent); and your goals (move more, sleep, stress, routine, understanding your own signals). This builds your **personal baseline + context**, so interpretations are tuned to *you* rather than to an average.
 
**What the app shows**: your flag (steady / watch / elevated vs baseline); a plain-language explanation that cites your own numbers; general recommendations across food, movement and rest; your daily step count; a signpost to *"consider seeing a professional if this continues or you feel unwell"*; and optional product links with a clear affiliate disclosure. It never names or infers a condition, and never treats a declared one.
 
---
 
## The trusted-adult view: the SEND signpost
 
Aevum Edge is a wellbeing wearable for anyone, and its sharpest use is giving a voice to the children and teens who most need one: those with SEND who cannot always find the words for how they feel.
 
Designed to sit inside the classroom learning app, the child's wrist becomes a live **feelings card** for the trusted adult in the room. The same three states, read against the child's own baseline and translated per child, tell the teacher how that child is arriving today, so they can adapt the lesson, the demands, and their own approach before the day tips rather than after. The child never has to announce that they are struggling.
 
The same state means different things for different children, so the Qwen agent turns one signal per child into the response agreed in advance with them and their family:
 
- **Steady:** a settled, regulated day. Meet them as usual; a full-demand lesson is fine.
- **Watch:** something is shifting. Soften the pace; a gentle check-in and a familiar routine can steady the day before it tips.
- **Elevated:** running high, or close to overload. Lower the demands, shorten the task, offer the quiet space. Let space do the talking.
It is done with dignity and never behind the child's back. Parental consent and the child's own assent, they can switch it off at any time, and only the single translated word ever leaves the wrist. The physiological detail stays on the device. It is a signpost the child owns, read with an adult who is on their side, not a monitor pointed at them.
 
Live: [the trusted-adult view](https://aevum-edge.netlify.app/trusted-adult-view.html).
 
---
 
## 🔗 Live
 
- **Companion app (the wrist):** https://aevum-edge.netlify.app
- **Trusted-adult view (the SEND signpost):** https://aevum-edge.netlify.app/trusted-adult-view.html
- **Agent API (live):** http://8.208.76.67/ returns live Qwen status
- **Qwen base URL (code proof):** [backend/agent/client.py](backend/agent/client.py)
---
 
## What's in here
 
```
Aevum-Edge-v1.0/
├── LICENSE                       MIT
├── README.md                     this file
├── firmware/
│   └── edge.ino                  ESP32 sketch: read sensors → features → POST → act
├── backend/                      the Agent (FastAPI + Qwen)
│   ├── app.py                    FastAPI: / health, /interpret, /baseline, /guidance
│   ├── requirements.txt
│   ├── .env.example              the environment variables the backend expects
│   ├── DEPLOY.md                 deploy on Alibaba Cloud (ECS / Simple App Server / Function Compute)
│   ├── agent/
│   │   ├── orchestrator.py       the ReAct plan → act → synthesise loop
│   │   ├── client.py             Qwen (DashScope) client + deterministic offline mock
│   │   ├── tools.py              the 6 model-callable tools + schemas
│   │   ├── schemas.py            feature vector, baseline, request/response contracts
│   │   ├── safety.py             diagnosis-free system prompt + scrubber
│   │   ├── consent.py            fail-closed consent tokens
│   │   ├── memory.py             rolling per-user baseline (opaque-token keyed)
│   │   ├── rag.py                BM25 retriever over the wellbeing KB
│   │   └── local_rule.py         transparent offline fallback (mirrors the firmware)
│   ├── kb/wellbeing/*.md         licence-clean wellbeing knowledge cards
│   └── prove/                    simulate.py + metrics.py, prove the agent with no hardware
├── companion/                    screenless companion app (also live on Netlify)
│   ├── index.html                today, vitals and guidance, with the agent trace
│   └── trusted-adult-view.html   the SEND trusted-adult signpost view
└── docs/
    ├── architecture.png          system diagram
    └── architecture.svg
```
 
---
 
## Hardware (solder-light, ~£45–49)
 
XIAO ESP32-S3 + Seeed expansion board · MAX30102 (PPG) · MPU-6050 (motion) · BME280 (ambient temp/humidity) · LiPo · mesh wristband. All sensors share one **3.3 V** I²C bus at distinct addresses: `0x57`, `0x68`, `0x76`. An optional TMP117 (`0x48`) adds **research-grade** skin temperature with zero firmware rework, the address slot is already reserved.
 
The build sits on the Seeed expansion board and a small breadboard, with the sensors wired by jumper. The only soldering is the header strips onto the XIAO and the pulse board. It stays accessible: solder-light, low-cost, and fully functional even unpaid.
 
---
 
## Quick start
 
**1. Backend (Alibaba Cloud)**: see [`backend/DEPLOY.md`](backend/DEPLOY.md). In short: deploy `app.py` on an **Alibaba Cloud ECS instance** (or Simple Application Server / Function Compute), set `DASHSCOPE_API_KEY` and `CONSENT_SECRET`, run it, and open the port. Visiting `/` returns a health JSON, this URL is your proof of Alibaba Cloud deployment. The hosted Qwen Cloud base URL is visible in [`backend/agent/client.py`](backend/agent/client.py).
 
**2. Firmware**: open `firmware/edge.ino` in the Arduino IDE (board: `XIAO_ESP32S3`). Install the libraries listed in the sketch header, set your Wi-Fi and the backend URL, and flash.
 
**3. Run**: the device samples every ~15 s and prints the flag, nudge and explanation to the Serial Monitor. Pull the network and watch it fall back to the local rule. To prove the whole agent **with no hardware**: `FORCE_MOCK=1 python backend/prove/simulate.py` and `FORCE_MOCK=1 python backend/prove/metrics.py`.
 
---
 
## Privacy & safety
 
- **Data minimisation**: only derived features (a handful of numbers) are sent; raw PPG and motion waveforms never leave the device.
- **Consent, fail-closed**: the backend refuses to interpret anything without a valid consent token; withdraw consent and processing stops. Health and mental-health context is special-category data, captured per-category, stored on-device, and deletable.
- **Diagnosis-free by construction**: the model is constrained to a wellbeing vocabulary, and a server-side scrubber strips any output that drifts toward a medical claim.
- **Not a medical device**: output is general wellbeing context only, never a diagnosis or treatment. If you feel unwell, speak to a healthcare professional.
---
 
## About
 
Built by **Aevum Foundry AI Ltd**, a UK AI-tools company. The first real-world pilot is planned for **Terra**, a rural cooperative wellness community we are developing in the Algarve, Portugal, and meant to take shape over the coming years, a setting where privacy matters and reliable connectivity can't be assumed, which is exactly what an edge-first design is for.
 
## Licence
 
MIT. See [`LICENSE`](LICENSE). Copyright (c) 2026 Aevum Foundry AI Ltd.
 
