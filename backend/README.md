# Aevum Edge — agentic backend

The cloud reasoning core for Aevum Edge. Not a single LLM call — a real **agent**:
a Qwen orchestrator that plans, calls specialised tools, grounds itself with retrieval, remembers
your baseline, asks a clarifying question when genuinely unsure, and is bounded by a diagnosis-free
safety layer. Runs on the hosted Qwen Cloud API on Alibaba Cloud.

## The Aevum Edge agent

```
features ─▶ consent gate (fail-closed) ─▶ baseline/memory ─▶ Qwen orchestrator ─▶ diagnosis-free scrub ─▶ read
                                                              │  plans + calls tools (ReAct loop)
                                                              ▼
   compute_cardiac_features · analyse_movement · thermal_context
   compare_to_baseline · retrieve_wellbeing_context (RAG) · safety_signpost
```

- **compute_cardiac_features** — HR + pulse-rate variability, **gated on stillness** (PPG HRV is
  motion-sensitive, so it's only trusted when the IMU says you were still).
- **analyse_movement** — two-stage: recognise the activity, *then* describe movement quality
  (cadence, regularity, steadiness) + fall flag.
- **thermal_context** — skin-vs-ambient temperature difference.
- **compare_to_baseline** — z-scores vs *your own* rolling baseline (the memory pattern).
- **retrieve_wellbeing_context** — RAG over a licence-clean wellbeing knowledge base, so advice is
  grounded, not invented.
- **safety_signpost** — decides whether to prompt you to see a professional (escalation, never a diagnosis).

Governing guards around the loop: **fail-closed consent** and a **diagnosis-free scrubber** that
neutralises any drift toward naming or inferring a condition. Every tool call is logged — the trace
is the agentic evidence.

## Diagnosis-free by construction
The output can only ever be **steady / watch / elevated vs your own baseline**, with a plain-language
why, a general wellbeing suggestion, and an optional signpost. It never names or infers a condition.
The depth is in the engineering; the words stay wellbeing.

## Run it
```
pip install -r requirements.txt

# offline mock agent — no key needed (also the resilience story)
FORCE_MOCK=1 uvicorn app:app --reload

# real Qwen Cloud
export DASHSCOPE_API_KEY=sk-...
uvicorn app:app --reload
```

## Prove it (before any hardware)
```
FORCE_MOCK=1 python prove/simulate.py     # runs 6 realistic scenarios through the full agent
FORCE_MOCK=1 python prove/metrics.py      # data-minimisation, latency, offline, personalisation
```

## API
- `GET /` → health JSON (**the Alibaba Cloud deployment-proof URL**; keep it live for judging).
- `POST /interpret` → `InterpretRequest` → `InterpretResponse` (fail-closed on consent).
- `POST /baseline` → dev helper to advance a baseline.

Mint a dev consent token:
```
python -c "from agent.consent import mint_consent_token; print(mint_consent_token())"
```

## Privacy
Only derived features are received (never raw waveforms). Consent is fail-closed. The baseline is keyed
by a hash of an opaque device token — no identity stored or logged — or supplied by the device for a fully
stateless backend. See `DEPLOY.md` for Alibaba Cloud deployment.

## Layout
```
app.py                    FastAPI: / health, /interpret, /baseline
agent/
  orchestrator.py         the ReAct plan->act->synthesise loop
  client.py               Qwen (DashScope) client + deterministic offline mock
  tools.py                the 6 model-callable tools + schemas
  schemas.py              feature vector, baseline, request/response contracts
  safety.py               diagnosis-free system prompt + scrubber
  consent.py              fail-closed consent tokens
  memory.py               rolling per-user baseline (opaque-token keyed)
  rag.py                  lightweight BM25 retriever over the KB
  local_rule.py           transparent offline fallback (mirrors firmware)
kb/wellbeing/*.md         licence-clean wellbeing knowledge cards
prove/                    simulate.py + metrics.py
DEPLOY.md                 Alibaba Cloud (Function Compute / ECS / SAS)
```

MIT © Aevum Foundry AI Ltd
