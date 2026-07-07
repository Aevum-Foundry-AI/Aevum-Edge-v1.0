"""Per-user baseline memory.

This is the MemoryAgent pattern: the agent's read is always *relative to this
user's own history*, which is what makes "vs your baseline" rigorous.

Privacy posture:
- keyed by a hash of the opaque device token — the raw token is never stored,
  and no identity is stored;
- for a fully stateless backend (e.g. serverless Function Compute), the device
  can instead supply its own baseline in the request (privacy mode), and this
  store is bypassed entirely;
- the file store here is for local dev / a single ECS or Simple Application
  Server instance. In production swap `FileBaselineStore` for Alibaba Cloud
  Table Store or Redis behind the same tiny interface.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import threading
import time
from typing import Optional

from .schemas import Baseline, FeatureVector

# Features we track a baseline for (numeric, meaningful to compare)
BASELINE_FIELDS = [
    "hr", "prv_rmssd", "prv_sdnn", "spo2", "motion_index",
    "cadence", "gait_regularity", "steadiness",
]


def _key(device_token: str) -> str:
    return hashlib.sha256(device_token.encode()).hexdigest()[:32]


class BaselineStore:
    def get(self, device_token: str) -> Baseline:  # pragma: no cover - interface
        raise NotImplementedError

    def update(self, device_token: str, features: FeatureVector) -> Baseline:  # pragma: no cover
        raise NotImplementedError


class InMemoryBaselineStore(BaselineStore):
    def __init__(self) -> None:
        self._d: dict[str, dict] = {}
        self._lock = threading.Lock()

    def get(self, device_token: str) -> Baseline:
        with self._lock:
            return Baseline(**self._d.get(_key(device_token), {}))

    def update(self, device_token: str, features: FeatureVector) -> Baseline:
        with self._lock:
            k = _key(device_token)
            state = self._d.get(k, {"means": {}, "sds": {}, "n": 0, "_m2": {}})
            _welford(state, features)
            self._d[k] = state
            return _to_baseline(state)


class FileBaselineStore(BaselineStore):
    def __init__(self, path: str = "/tmp/edge_baselines.json") -> None:
        self.path = path
        self._lock = threading.Lock()

    def _load(self) -> dict:
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path) as f:
                return json.load(f)
        except Exception:
            return {}

    def _save(self, d: dict) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(d, f)
        os.replace(tmp, self.path)

    def get(self, device_token: str) -> Baseline:
        with self._lock:
            return Baseline(**{k: v for k, v in self._load().get(_key(device_token), {}).items()
                               if k in {"means", "sds", "n", "updated_at"}})

    def update(self, device_token: str, features: FeatureVector) -> Baseline:
        with self._lock:
            d = self._load()
            k = _key(device_token)
            state = d.get(k, {"means": {}, "sds": {}, "n": 0, "_m2": {}})
            _welford(state, features)
            d[k] = state
            self._save(d)
            return _to_baseline(state)


def _welford(state: dict, features: FeatureVector) -> None:
    """Online mean/variance update, per field (Welford's algorithm)."""
    fv = features.model_dump()
    state["n"] = state.get("n", 0) + 1
    n = state["n"]
    means = state.setdefault("means", {})
    m2 = state.setdefault("_m2", {})
    for field in BASELINE_FIELDS:
        x = fv.get(field)
        if x is None:
            continue
        x = float(x)
        prev = means.get(field, x)
        delta = x - prev
        means[field] = prev + delta / n
        m2[field] = m2.get(field, 0.0) + delta * (x - means[field])
    sds = state.setdefault("sds", {})
    for field, m2v in m2.items():
        sds[field] = math.sqrt(m2v / n) if n > 1 else 0.0
    state["updated_at"] = time.time()


def _to_baseline(state: dict) -> Baseline:
    return Baseline(
        means=state.get("means", {}),
        sds=state.get("sds", {}),
        n=state.get("n", 0),
        updated_at=state.get("updated_at"),
    )


def make_store() -> BaselineStore:
    kind = os.environ.get("BASELINE_STORE", "file").lower()
    if kind == "memory":
        return InMemoryBaselineStore()
    return FileBaselineStore(os.environ.get("BASELINE_PATH", "/tmp/edge_baselines.json"))
