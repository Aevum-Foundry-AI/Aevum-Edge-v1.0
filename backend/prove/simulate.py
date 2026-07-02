"""Prove the whole agent on synthetic / public-dataset features — no hardware needed.

Seeds a personal baseline, then runs a set of realistic scenarios through the
full Sentinel Agent and prints the flag, the tool-call trace, and the read.

Run:  FORCE_MOCK=1 python prove/simulate.py
(Drop FORCE_MOCK and set DASHSCOPE_API_KEY to run it through real Qwen.)

WESAD: if you have the public WESAD dataset, `from_wesad()` shows where to plug
derived cardiac features in; without it, we use realistic synthetic vectors.
"""
from __future__ import annotations

import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.memory import InMemoryBaselineStore
from agent.orchestrator import run_agent
from agent.schemas import FeatureVector

random.seed(7)


def seed_baseline(store: InMemoryBaselineStore, token: str, n: int = 40):
    """Feed typical resting windows so the user has a personal baseline."""
    for _ in range(n):
        store.update(token, FeatureVector(
            hr=random.gauss(68, 4), prv_rmssd=random.gauss(46, 7), prv_sdnn=random.gauss(58, 8),
            spo2=random.gauss(98, 0.6), still=True, activity="rest", motion_index=random.gauss(0.05, 0.02),
            steadiness=random.gauss(0.9, 0.03), gait_regularity=random.gauss(0.9, 0.03),
            skin_temp_c=random.gauss(33.5, 0.3), ambient_temp_c=random.gauss(22, 0.5), humidity=45,
        ))
    return store.get(token)


SCENARIOS: dict[str, FeatureVector] = {
    "resting_calm": FeatureVector(hr=67, prv_rmssd=47, prv_sdnn=59, spo2=98, still=True,
                                  activity="rest", motion_index=0.04, steadiness=0.91,
                                  skin_temp_c=33.6, ambient_temp_c=22.1, humidity=45),
    "post_exercise": FeatureVector(hr=96, prv_rmssd=None, prv_sdnn=None, spo2=97, still=False,
                                   activity="active", motion_index=0.82,
                                   skin_temp_c=34.6, ambient_temp_c=22.4, humidity=48),
    "tired_low_hrv": FeatureVector(hr=76, prv_rmssd=26, prv_sdnn=34, spo2=97, still=True,
                                   activity="rest", motion_index=0.05, steadiness=0.88,
                                   skin_temp_c=33.7, ambient_temp_c=22.0, humidity=44),
    "unsteady_walk": FeatureVector(hr=79, still=False, activity="walk", motion_index=0.45,
                                   cadence=88, gait_regularity=0.62, steadiness=0.55,
                                   skin_temp_c=33.9, ambient_temp_c=22.3, humidity=46),
    "sedentary_long": FeatureVector(hr=70, prv_rmssd=44, spo2=98, still=True, activity="rest",
                                    motion_index=0.03, sedentary_min=190, steadiness=0.9,
                                    skin_temp_c=33.4, ambient_temp_c=22.0, humidity=45),
    "fall_flag": FeatureVector(hr=101, still=False, activity="active", motion_index=1.4,
                               fall_flag=True, skin_temp_c=34.0, ambient_temp_c=22.2, humidity=46),
}


def from_wesad(path: str):  # pragma: no cover - optional
    """Placeholder: WESAD ships one pickle per subject (chest+wrist signals).
    Derive HR + PRV (RMSSD/SDNN) from the wrist BVP during a still baseline block
    and build a FeatureVector. Left as a documented seam; synthetic is the default."""
    raise NotImplementedError("Plug WESAD-derived cardiac features into a FeatureVector here.")


def main():
    os.environ.setdefault("FORCE_MOCK", "1")
    token = "sim-device-001"
    store = InMemoryBaselineStore()
    base = seed_baseline(store, token)
    print(f"Seeded baseline (n={base.n}): HR~{base.means['hr']:.0f}bpm, "
          f"HRV~{base.means['prv_rmssd']:.0f}ms, steadiness~{base.means.get('steadiness',0):.2f}\n")

    for name, feats in SCENARIOS.items():
        r = run_agent(feats, base, context={}, allow_clarify=True)
        print(f"── {name} ──────────────────────────────")
        print(f"  FLAG: {r.flag.upper()}   (model={r.model}, degraded={r.degraded}, scrubbed={r.scrubbed})")
        print(f"  headline : {r.headline}")
        print(f"  why      : {r.why}")
        print(f"  cited    : {', '.join(r.cited_numbers)}")
        print(f"  suggest  : {r.suggestion}")
        print(f"  signpost : {r.signpost}")
        if r.clarify_question:
            print(f"  CLARIFY  : {r.clarify_question}")
        print(f"  trace    : {' -> '.join(t.name for t in r.tool_trace)}")
        print()


if __name__ == "__main__":
    main()
