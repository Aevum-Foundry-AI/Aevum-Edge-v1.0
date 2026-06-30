"""
Aevum Edge Sentinel - cloud reasoning backend
Qwen Cloud Global AI Hackathon - EdgeAgent track (Track 5)

Receives derived physiological features from the wearable, asks Qwen to
interpret them against the wearer's own baseline, and returns a structured,
*diagnosis-free* wellbeing flag. Deploys on Alibaba Cloud (Function Compute
web function or ECS) - see DEPLOY.md.

Privacy by design:
  * Only derived features arrive here; raw PPG / IMU waveforms never leave the device.
  * Fail-closed consent gate: no valid consent token -> request refused.
  * Stateless: nothing is persisted or logged against identity.

Environment variables:
  DASHSCOPE_API_KEY   your Qwen Cloud API key (required)
  QWEN_MODEL          model id, default "qwen3.7-plus"
  CONSENT_TOKEN       expected consent token, default "demo-consent-granted"
"""

import os
import json
from typing import List

from fastapi import FastAPI
from pydantic import BaseModel
from openai import OpenAI

QWEN_BASE_URL    = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
QWEN_MODEL       = os.environ.get("QWEN_MODEL", "qwen3.7-plus")
EXPECTED_CONSENT = os.environ.get("CONSENT_TOKEN", "demo-consent-granted")

client = OpenAI(
    api_key=os.environ.get("DASHSCOPE_API_KEY", ""),
    base_url=QWEN_BASE_URL,
)

app = FastAPI(title="Aevum Edge Sentinel", version="1.0")


# ------------------------------- data models -------------------------------
class Baseline(BaseModel):
    heart_rate_bpm: float
    skin_temp_c: float


class Features(BaseModel):
    consent_token: str
    heart_rate_bpm: float
    motion_index: float
    skin_temp_c: float
    ambient_temp_c: float
    ambient_hum_pct: float
    baseline: Baseline


class Signal(BaseModel):
    feature: str
    observation: str


class Assessment(BaseModel):
    status: str = "steady"            # "steady" | "watch" | "elevated"
    signals: List[Signal] = []
    nudge: str = ""
    explanation: str = ""
    confidence: str = "medium"        # "low" | "medium" | "high"
    source: str = "cloud"             # "cloud" | "refused"


# --------------------------- diagnosis-free prompt ---------------------------
SYSTEM_PROMPT = """You interpret wellbeing signals for a NON-MEDICAL wearable.
You receive derived physiological features and the wearer's personal baseline.
Return ONLY JSON with this exact shape:
{
  "status": "steady" | "watch" | "elevated",
  "signals": [{"feature": "...", "observation": "..."}],
  "nudge": "one short, gentle, non-medical suggestion",
  "explanation": "plain-language reasoning that refers to the actual numbers",
  "confidence": "low" | "medium" | "high"
}

HARD RULES - never break these:
- Never name, diagnose, or imply any disease, infection, or medical condition.
- Never tell the wearer they are ill; never mention medication or treatment.
- "status" describes deviation from baseline only:
    steady   = near baseline
    watch    = mild deviation
    elevated = larger deviation
- The nudge is general wellbeing only (rest, hydrate, breathe, check in later).
  If signals look notable, suggest resting and seeing a healthcare professional
  if the wearer personally feels unwell - framed as wellbeing, not diagnosis.
- Compare each feature to the baseline and cite the real values in "explanation".
"""

# Defensive server-side guard: strip any output that drifts toward a medical claim.
BANNED = ["diagnos", "disease", "infection", "illness", "you have", "sick",
          "medication", "prescri", "covid", "virus", "condition", "symptom"]


def sanitise(text: str) -> str:
    if any(b in text.lower() for b in BANNED):
        return ("Some readings sit above your usual baseline. Consider resting and "
                "checking in again later; if you personally feel unwell, speak to a "
                "healthcare professional.")
    return text


# --------------------------------- routes ---------------------------------
@app.get("/")
def health():
    # Public health check - also serves as the Alibaba Cloud deployment-proof URL.
    return {"service": "aevum-edge-sentinel", "status": "ok", "model": QWEN_MODEL}


@app.post("/assess", response_model=Assessment)
def assess(f: Features) -> Assessment:
    # Fail-closed consent gate.
    if f.consent_token != EXPECTED_CONSENT:
        return Assessment(
            status="steady",
            nudge="Consent not present - nothing was processed.",
            explanation="The device did not present a valid consent token, so no "
                        "interpretation was performed.",
            confidence="high",
            source="refused",
        )

    user = (
        f"heart_rate_bpm={f.heart_rate_bpm} (baseline {f.baseline.heart_rate_bpm}); "
        f"skin_temp_c={f.skin_temp_c} (baseline {f.baseline.skin_temp_c}); "
        f"ambient_temp_c={f.ambient_temp_c}; ambient_hum_pct={f.ambient_hum_pct}; "
        f"motion_index={f.motion_index}. Interpret against baseline and return JSON."
    )

    try:
        resp = client.chat.completions.create(
            model=QWEN_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        data = json.loads(resp.choices[0].message.content)
    except Exception as e:
        # Graceful degradation on the cloud side too.
        return Assessment(
            status="steady",
            nudge="Could not reason right now; readings noted.",
            explanation=f"Upstream model unavailable ({type(e).__name__}).",
            confidence="low",
            source="cloud",
        )

    # Guard the free-text fields, then validate.
    data["explanation"] = sanitise(str(data.get("explanation", "")))
    data["nudge"]       = sanitise(str(data.get("nudge", "")))
    data["source"]      = "cloud"

    try:
        return Assessment(**data)
    except Exception:
        return Assessment(
            status=str(data.get("status", "steady")),
            nudge=str(data.get("nudge", "")),
            explanation=str(data.get("explanation", "")),
            confidence=str(data.get("confidence", "medium")),
            source="cloud",
        )


# Local dev entrypoint:  python app.py   (Alibaba Cloud uses the start command in DEPLOY.md)
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "9000")))
