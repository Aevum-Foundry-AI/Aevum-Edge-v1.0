"""The Sentinel Agent's tools.

Each is a genuine function the orchestrator can call. Together they turn a raw
feature vector into a grounded, personalised, diagnosis-free wellbeing read.
The functions operate over a shared context (features + baseline) so the model
only needs to pass light arguments.

Model-callable tools (1-6):
    compute_cardiac_features, analyse_movement, thermal_context,
    compare_to_baseline, retrieve_wellbeing_context, safety_signpost
Governing (non-model) guards: consent (fail-closed) + diagnosis-free scrub —
    enforced around the loop, see app.py / safety.py. Together = the 7-part suite.
"""
from __future__ import annotations

from typing import Any

from . import rag
from .local_rule import deviations
from .schemas import Baseline, FeatureVector


# ---- the tools -------------------------------------------------------------

def compute_cardiac_features(features: FeatureVector) -> dict:
    """HR + pulse-rate variability, with an honest reliability gate on stillness."""
    reliable = bool(features.still) and features.prv_rmssd is not None
    out: dict[str, Any] = {
        "hr_bpm": features.hr,
        "spo2_pct": features.spo2,
        "prv_rmssd_ms": features.prv_rmssd,
        "prv_sdnn_ms": features.prv_sdnn,
        "hrv_reliable": reliable,
    }
    if not reliable:
        out["note"] = ("HRV/PRV not treated as reliable this window because the user was not still "
                       "(PPG variability is motion-sensitive); using heart rate only.")
    else:
        out["note"] = "User was still, so pulse-rate variability is usable as a recovery/arousal proxy."
    return out


def analyse_movement(features: FeatureVector) -> dict:
    """Two-stage: recognise the activity, THEN describe movement quality on it."""
    activity = features.activity or ("rest" if features.motion_index < 0.15 else
                                     "walk" if features.motion_index < 0.6 else "active")
    out: dict[str, Any] = {"activity": activity, "motion_index": features.motion_index,
                           "fall_flag": features.fall_flag}
    if activity == "walk":
        out.update({
            "cadence_spm": features.cadence,
            "gait_regularity": features.gait_regularity,
            "steadiness": features.steadiness,
            "quality_note": "Walking detected; describing rhythm/steadiness vs the user's usual pattern.",
        })
    elif activity == "rest":
        out["sedentary_min"] = features.sedentary_min
        out["quality_note"] = "At rest; movement-quality metrics not applicable this window."
    else:
        out["quality_note"] = "Active (non-walking); reporting intensity only."
    return out


def thermal_context(features: FeatureVector) -> dict:
    diff = None
    if features.skin_temp_c is not None and features.ambient_temp_c is not None:
        diff = round(features.skin_temp_c - features.ambient_temp_c, 2)
    return {
        "skin_temp_c": features.skin_temp_c,
        "ambient_temp_c": features.ambient_temp_c,
        "humidity_pct": features.humidity,
        "skin_minus_ambient_c": diff,
        "note": "Thermal context only; not a body-temperature measurement.",
    }


def compare_to_baseline(features: FeatureVector, baseline: Baseline) -> dict:
    devs = deviations(features, baseline)
    if not devs:
        return {"have_baseline": False,
                "note": "Still learning this user's baseline; treat as steady while learning.",
                "deviations_z": {}}
    readable = {k: round(v, 2) for k, v in devs.items()}
    return {
        "have_baseline": True,
        "baseline_n": baseline.n,
        "deviations_z": readable,
        "note": "Positive z = above the user's own usual; negative = below. |z|>=2 is well outside usual.",
    }


def retrieve_wellbeing_context(query: str) -> dict:
    cards = rag.retrieve(query, k=3)
    return {"cards": cards, "count": len(cards)}


def safety_signpost(persistent: bool = False, feels_unwell: bool = False,
                    worst_z: float = 0.0) -> dict:
    signpost = bool(persistent or feels_unwell or abs(worst_z) >= 3.0)
    return {
        "signpost": signpost,
        "reason": ("A reading is persistently or markedly outside the user's usual range, or they may "
                   "feel unwell — prompt them to talk to a professional." if signpost else
                   "Nothing that warrants a professional prompt this window."),
    }


# ---- dispatch + schemas ----------------------------------------------------

def build_dispatch(features: FeatureVector, baseline: Baseline) -> dict[str, Any]:
    """Bind the shared context so the model passes only light args."""
    return {
        "compute_cardiac_features": lambda **_: compute_cardiac_features(features),
        "analyse_movement": lambda **_: analyse_movement(features),
        "thermal_context": lambda **_: thermal_context(features),
        "compare_to_baseline": lambda **_: compare_to_baseline(features, baseline),
        "retrieve_wellbeing_context": lambda query="wellbeing recovery movement", **_:
            retrieve_wellbeing_context(query),
        "safety_signpost": lambda persistent=False, feels_unwell=False, worst_z=0.0, **_:
            safety_signpost(persistent, feels_unwell, worst_z),
    }


TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "compute_cardiac_features",
        "description": "Heart rate and pulse-rate variability (HRV proxy) from the window; marks HRV "
                       "reliable only if the user was still.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "analyse_movement",
        "description": "Recognise the activity (rest/walk/active) then describe movement quality "
                       "(cadence, regularity, steadiness) and any fall flag.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "thermal_context",
        "description": "Skin-contact vs ambient temperature difference for thermal/comfort context.",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "compare_to_baseline",
        "description": "Compare this window's features to the user's own rolling baseline (z-scores).",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "retrieve_wellbeing_context",
        "description": "Retrieve general wellbeing/movement/recovery guidance to ground the explanation.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "what to look up, e.g. 'low HRV recovery'"}
        }},
    }},
    {"type": "function", "function": {
        "name": "safety_signpost",
        "description": "Decide whether to prompt the user to see a professional (escalation, not diagnosis).",
        "parameters": {"type": "object", "properties": {
            "persistent": {"type": "boolean"},
            "feels_unwell": {"type": "boolean"},
            "worst_z": {"type": "number"},
        }},
    }},
]
