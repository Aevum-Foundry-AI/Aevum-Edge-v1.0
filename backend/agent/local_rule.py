"""Transparent, deterministic local rule.

This is the logic the *firmware* falls back to when the network drops, and the
backend's safe default if the model is unavailable. Intentionally simple and
explainable, and it encodes the physiology honestly:

- Heart rate is only judged against the (resting) baseline when the user is
  STILL — an elevated pulse while moving/exercising is expected, not a concern.
- Pulse-rate variability is only present when still (the device gates it), so it
  is always compared personally.
- Movement quality (steadiness, gait regularity) is judged only when walking,
  against a documented generic "steady-walk" reference band — NOT the resting
  baseline (comparing a walk to sitting still would be meaningless). This is a
  general reference, never a diagnosis.
- A standard-deviation floor per feature stops tiny early baselines from
  producing absurd z-scores.
- Hard safety flags (a fall) override everything.

No black box, no condition names, no diagnosis.
"""
from __future__ import annotations

from .schemas import Baseline, FeatureVector

# personal-baseline cardiac drivers, and which direction is the concern
_CARDIAC = {"hr": "high", "prv_rmssd": "low", "prv_sdnn": "low"}
# minimum sensible SD per feature (avoid divide-by-tiny-baseline)
_FLOORS = {"hr": 2.0, "prv_rmssd": 4.0, "prv_sdnn": 5.0}
# generic "steady walk" reference band for movement quality (documented, not personal)
_WALK_REF = {"steadiness": (0.85, 0.12), "gait_regularity": (0.85, 0.12)}

WATCH_AT, ELEVATED_AT = 1.5, 2.5


def cardiac_deviations(features: FeatureVector, baseline: Baseline) -> dict[str, float]:
    fv = features.model_dump()
    out: dict[str, float] = {}
    for field in _CARDIAC:
        x, mu, sd = fv.get(field), baseline.means.get(field), baseline.sds.get(field)
        if x is None or mu is None or sd is None:
            continue
        if field == "hr" and not features.still:
            continue  # movement explains a raised pulse; not a concern
        out[field] = (float(x) - mu) / max(sd, _FLOORS[field])
    return out


def movement_deviations(features: FeatureVector) -> dict[str, float]:
    out: dict[str, float] = {}
    if (features.activity or "") == "walk":
        fv = features.model_dump()
        for field, (mu, sd) in _WALK_REF.items():
            x = fv.get(field)
            if x is not None:
                out[field] = (float(x) - mu) / sd
    return out


def deviations(features: FeatureVector, baseline: Baseline) -> dict[str, float]:
    """Combined signed z-scores for transparency (personal cardiac + walk-reference movement)."""
    d = cardiac_deviations(features, baseline)
    d.update(movement_deviations(features))
    return d


def _concern(devs: dict[str, float]) -> float:
    worst = 0.0
    for field, z in devs.items():
        direction = _CARDIAC.get(field, "low")  # movement quality: lower is the concern
        signed = z if direction == "high" else -z
        worst = max(worst, signed)
    return worst


def local_flag(features: FeatureVector, baseline: Baseline) -> tuple[str, dict[str, float]]:
    devs = deviations(features, baseline)
    if features.fall_flag:
        return "elevated", devs
    if not devs:  # cold start — still learning this user
        return "steady", devs
    c = _concern(devs)
    if c >= ELEVATED_AT:
        return "elevated", devs
    if c >= WATCH_AT:
        return "watch", devs
    return "steady", devs
