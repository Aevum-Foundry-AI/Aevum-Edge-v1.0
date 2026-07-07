"""Aevum Edge — cloud reasoning service (FastAPI).

Endpoints:
  GET  /            health JSON — this is your Alibaba Cloud deployment-proof URL
  POST /interpret   features -> diagnosis-free wellbeing read (fail-closed on consent)
  POST /baseline    (dev) seed/advance a baseline from a feature vector

Privacy posture: stateless request handling, no identity stored or logged; only
derived features are ever received; consent is enforced fail-closed.
"""
from __future__ import annotations

import os
import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from agent.client import DEFAULT_MODEL
from agent.consent import ConsentError, validate_consent
from agent.guidance import guidance as run_guidance
from agent.memory import make_store
from agent.orchestrator import run_agent
from agent.schemas import Baseline, FeatureVector, GuidanceRequest, InterpretRequest, InterpretResponse

app = FastAPI(title="Aevum Edge", version="1.0",
              description="Privacy-first, diagnosis-free wellbeing reasoning at the edge.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

STORE = make_store()
STARTED = time.time()


@app.get("/")
def health():
    """Deployment-proof + liveness. Keep this reachable through judging."""
    return {
        "status": "ok",
        "service": "aevum-edge",
        "model": DEFAULT_MODEL,
        "mode": "live" if os.environ.get("DASHSCOPE_API_KEY") and not os.environ.get("FORCE_MOCK") else "offline-mock",
        "uptime_s": round(time.time() - STARTED, 1),
        "diagnosis_free": True,
    }


@app.post("/interpret", response_model=InterpretResponse)
def interpret(req: InterpretRequest):
    # 1. consent — fail closed
    try:
        validate_consent(req.consent_token)
    except ConsentError as exc:
        raise HTTPException(status_code=403, detail=f"consent invalid: {exc}")

    # 2. baseline (memory) — device-supplied (stateless privacy mode) or server rolling store
    if req.supplied_baseline is not None:
        baseline = req.supplied_baseline
    else:
        baseline = STORE.update(req.device_token, req.features)

    # 3. run the agent, 4. scrub happens inside, 5. return the safe read
    return run_agent(req.features, baseline, context=req.context, allow_clarify=req.allow_clarify)


@app.post("/baseline", response_model=Baseline)
def seed_baseline(device_token: str, features: FeatureVector):
    """Dev helper: advance a user's baseline from a feature vector."""
    return STORE.update(device_token, features)


@app.post("/guidance")
def guidance(req: GuidanceRequest):
    """Card-grounded, dose-free, citation-locked wellbeing guidance.

    The agent writes the connective prose, but may only draw on cards retrieved
    from the knowledge base; links are re-attached from those cards, and a
    dose/condition scrubber runs before anything is returned. Consent fail-closed.
    """
    try:
        validate_consent(req.consent_token)
    except ConsentError as exc:
        raise HTTPException(status_code=403, detail=f"consent invalid: {exc}")
    return run_guidance(req.context)
