# Aevum Edge Sentinel

**A privacy-first wearable that senses at the edge, reasons in the cloud with Qwen, and acts locally — without ever making a diagnosis.**

> Qwen Cloud Global AI Hackathon · **Track 5: EdgeAgent** · by [Aevum Foundry AI Ltd](https://aevumfoundry.ai)

Aevum Edge Sentinel is a screenless, wrist-worn health-sensing node. Cheap, no-solder sensors read your body and your surroundings; the device extracts features **on-device**, and Qwen (running on Alibaba Cloud) interprets them against *your own baseline* to return a gentle, explainable wellbeing nudge. Raw sensor data never leaves the wrist, consent is enforced fail-closed, and the system keeps working — with a simpler local rule — when the network drops.

It deliberately **never diagnoses**. It tells you whether your signals are **steady**, worth a **watch**, or **elevated** versus your baseline, explains why in plain language, and — if something is persistently off — signposts you to a real clinician. It never names or infers a condition, and never tries to treat one you've declared.

---

## Why it fits EdgeAgent

| Track requirement | How Aevum Edge Sentinel does it |
|---|---|
| **Perceive** via edge sensors | PPG (heart rate), motion (accelerometer/gyro), skin-contact temperature and ambient temp/humidity over one I²C bus |
| **Reason** via cloud APIs | Qwen `qwen3.7-plus` on Alibaba Cloud turns features + your personal baseline into a structured wellbeing flag |
| **Act** locally | The device surfaces the flag and nudge; an on-device rule keeps acting when offline |
| **Privacy-aware data handling** | Only **derived features** leave the device; **fail-closed consent gate**; stateless backend; no identity logged |
| **Graceful offline degradation** | If Wi-Fi or the cloud is unavailable, the device falls back to a transparent local threshold rule and never goes dark |

---

## Architecture

A polished diagram lives in [`docs/architecture.png`](docs/architecture.png). In brief:

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
   ┌──────────────────── Alibaba Cloud (Function Compute) ───────────────────────┐
   │  FastAPI ─► Qwen qwen3.7-plus (DashScope) ─► structured wellbeing flag       │
   │            diagnosis-free system prompt + server-side guard                  │
   └─────────────────────────────────────────────────────────────────────────────┘
                                                                          │
                                          status · nudge · explanation    ▼
                                                          companion app + the wrist
```

---

## The companion app

The wearable is screenless; a companion phone app handles personalisation and the human-readable side.

**Onboarding & profile** (one-time, editable) — height, weight, age range; activity frequency, type and intensity; diet type, patterns and hydration; any physical or mental health context you *choose* to share (per-category consent); and your goals (move more, sleep, stress, routine, understanding your own signals). This builds your **personal baseline + context**, stored on the device, so interpretations are tuned to *you* rather than to an average.

**What the app shows** — your flag (steady / watch / elevated vs baseline); a plain-language explanation that cites your own numbers; general recommendations across food, movement and rest; a signpost to *"consider seeing a clinician if this continues or you feel unwell"*; and optional product links (e.g. supplements) with a clear affiliate disclosure. It never names or infers a condition, and never treats a declared one.

---

## What's in here

```
Edge-Sentinel-v1.0/
├── LICENSE                     MIT
├── README.md                   this file
├── firmware/
│   └── edge_sentinel.ino       ESP32 sketch: read sensors → features → POST → act
├── backend/
│   ├── app.py                  FastAPI service: features → Qwen → diagnosis-free flag
│   ├── requirements.txt
│   └── DEPLOY.md               deploy on Alibaba Cloud (Function Compute or ECS)
└── docs/
    ├── architecture.png        system diagram
    └── architecture.svg
```

---

## Hardware (no-solder, ~£45–49)

XIAO ESP32-S3 + Seeed expansion board · MAX30102 (PPG) · MPU-6050 (motion) · BME280 (ambient temp/humidity) · LiPo · mesh wristband. All sensors share one **3.3 V** I²C bus at distinct addresses: `0x57`, `0x68`, `0x76`. An optional TMP117 (`0x48`) adds clinical-grade skin temperature with zero firmware rework — the address slot is already reserved.

The whole build is deliberately solder-free: a small breadboard and jumper wires only, so it's accessible to makers who can't (or shouldn't) solder.

---

## Quick start

**1. Backend (Alibaba Cloud)** — see [`backend/DEPLOY.md`](backend/DEPLOY.md). In short: deploy `app.py` as a Function Compute web function, set `DASHSCOPE_API_KEY`, enable the HTTP trigger, and copy the public URL. Visiting `/` returns a health JSON — **this URL is your proof of Alibaba Cloud deployment.**

**2. Firmware** — open `firmware/edge_sentinel.ino` in the Arduino IDE (board: `XIAO_ESP32S3`). Install the libraries listed in the sketch header, set your Wi-Fi and the backend URL, and flash.

**3. Run** — the device samples every ~15 s and prints the flag, nudge and explanation to the Serial Monitor. Pull the network and watch it fall back to the local rule.

---

## Privacy & safety

- **Data minimisation** — only derived features (a handful of numbers) are sent; raw PPG and motion waveforms never leave the device.
- **Consent, fail-closed** — the backend refuses to interpret anything without a valid consent token; withdraw consent and processing stops. Health and mental-health context is special-category data, captured per-category, stored on-device, and deletable.
- **Diagnosis-free by construction** — the model is constrained to a wellbeing vocabulary, and a server-side guard strips any output that drifts toward a medical claim.
- **Not a medical device** — output is general wellbeing context only, never a diagnosis or treatment. If you feel unwell, speak to a healthcare professional.

---

## About

Built by **Aevum Foundry AI Ltd**, a UK AI-tools company. The first real-world pilot is planned for **Terra**, a rural cooperative wellness community in the Algarve, Portugal — a setting where privacy matters and reliable connectivity can't be assumed, which is exactly what an edge-first design is for.

## Licence

MIT — see [`LICENSE`](LICENSE). Copyright (c) 2026 Aevum Foundry AI Ltd.
