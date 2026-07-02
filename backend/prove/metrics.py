"""The metrics to define and SELL — computed, not asserted.

Run:  FORCE_MOCK=1 python prove/metrics.py
"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.memory import InMemoryBaselineStore
from agent.orchestrator import run_agent
from agent.schemas import Baseline, FeatureVector


def data_minimisation() -> dict:
    """Raw waveform bytes per window vs the derived payload that actually leaves the wrist."""
    ppg_hz, imu_hz, window_s, bytes_per_sample = 100, 50, 4, 4
    raw_bytes = (ppg_hz * 2 + imu_hz * 6) * window_s * bytes_per_sample  # 2 PPG ch + 6 IMU ch
    feats = FeatureVector(hr=68, prv_rmssd=46, prv_sdnn=58, spo2=98, still=True, activity="rest",
                          motion_index=0.05, steadiness=0.9, skin_temp_c=33.5, ambient_temp_c=22.0,
                          humidity=45)
    derived_bytes = len(json.dumps(feats.model_dump(exclude_none=True)).encode())
    return {"raw_bytes": raw_bytes, "derived_bytes": derived_bytes,
            "ratio": round(raw_bytes / derived_bytes, 1)}


def latency(n: int = 5) -> dict:
    store = InMemoryBaselineStore()
    tok = "m"
    for _ in range(30):
        store.update(tok, FeatureVector(hr=68, prv_rmssd=46, spo2=98, still=True, activity="rest",
                                        motion_index=0.05, steadiness=0.9))
    base = store.get(tok)
    feats = FeatureVector(hr=78, prv_rmssd=30, spo2=97, still=True, activity="rest",
                          motion_index=0.05, steadiness=0.88)
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        run_agent(feats, base, context={}, allow_clarify=True)
        ts.append((time.perf_counter() - t0) * 1000)
    return {"runs": n, "mean_ms": round(sum(ts) / n, 1), "min_ms": round(min(ts), 1),
            "max_ms": round(max(ts), 1), "note": "offline-mock path (no network)"}


def offline_fallback() -> dict:
    from agent.local_rule import local_flag
    store = InMemoryBaselineStore(); tok = "o"
    for _ in range(30):
        store.update(tok, FeatureVector(hr=68, prv_rmssd=46, still=True, activity="rest", motion_index=0.05))
    base = store.get(tok)
    feats = FeatureVector(hr=95, prv_rmssd=22, still=True, activity="rest", motion_index=0.05)
    t0 = time.perf_counter()
    flag, _ = local_flag(feats, base)
    dt = (time.perf_counter() - t0) * 1000
    return {"local_rule_flag": flag, "fallback_ms": round(dt, 3),
            "note": "deterministic on-device rule; runs with no network and no model"}


def personalisation() -> dict:
    """Same window, two different people -> different flags (memory working)."""
    feats = FeatureVector(hr=82, prv_rmssd=30, spo2=98, still=True, activity="rest",
                          motion_index=0.05, steadiness=0.9)
    athlete = Baseline(means={"hr": 82, "prv_rmssd": 30}, sds={"hr": 4, "prv_rmssd": 6}, n=40)
    calm = Baseline(means={"hr": 62, "prv_rmssd": 55}, sds={"hr": 3, "prv_rmssd": 7}, n=40)
    ra = run_agent(feats, athlete, allow_clarify=False)
    rc = run_agent(feats, calm, allow_clarify=False)
    return {"same_features": "HR 82, HRV 30",
            "athlete_baseline_flag": ra.flag, "calm_baseline_flag": rc.flag,
            "different": ra.flag != rc.flag}


def main():
    os.environ.setdefault("FORCE_MOCK", "1")
    dm = data_minimisation()
    print("METRICS — lift these into the Story and say them in the video\n")
    print(f"Data minimisation : {dm['raw_bytes']:,} B raw/window -> {dm['derived_bytes']} B derived "
          f"= ~{dm['ratio']}x less data ever leaves the wrist")
    lat = latency(); print(f"Latency           : {lat['mean_ms']} ms mean ({lat['min_ms']}-{lat['max_ms']} ms), {lat['note']}")
    off = offline_fallback(); print(f"Offline fallback  : {off['fallback_ms']} ms, flag='{off['local_rule_flag']}' — {off['note']}")
    per = personalisation()
    print(f"Personalisation   : {per['same_features']} -> athlete='{per['athlete_baseline_flag']}', "
          f"calm='{per['calm_baseline_flag']}' (different={per['different']}) — memory working")


if __name__ == "__main__":
    main()
