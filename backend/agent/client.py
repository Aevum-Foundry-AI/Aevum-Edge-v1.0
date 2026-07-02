"""LLM client abstraction.

Two implementations behind one tiny interface so the orchestrator is
client-agnostic:

- DashScopeClient: the real path — Qwen on Alibaba Cloud via the OpenAI-compatible
  DashScope endpoint, with function/tool calling. THIS is what the hackathon
  requires (hosted Qwen Cloud API, base URL visible below).
- MockClient: a deterministic offline stand-in that drives the same tool loop and
  produces a safe read via the transparent local rule — so you can build and prove
  the agent with no key (and it doubles as a resilience story).
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

from . import rag
from .local_rule import deviations, local_flag
from .schemas import Baseline, FeatureVector

# The hosted Qwen Cloud base URL — REQUIRED to be visible in-repo for eligibility.
DASHSCOPE_BASE_URL = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
DEFAULT_MODEL = os.environ.get("QWEN_MODEL", "qwen3.7-plus")   # confirm exact id in the Qwen Cloud console
FAST_MODEL = os.environ.get("QWEN_FAST_MODEL", "qwen3.6-flash")


@dataclass
class ToolCallReq:
    id: str
    name: str
    arguments: dict = field(default_factory=dict)


@dataclass
class LLMResp:
    content: Optional[str] = None
    tool_calls: list[ToolCallReq] = field(default_factory=list)


class DashScopeClient:
    def __init__(self, model: str = DEFAULT_MODEL):
        from openai import OpenAI  # imported lazily so the mock path needs no dep
        self.model = model
        self.client = OpenAI(
            base_url=DASHSCOPE_BASE_URL,
            api_key=os.environ["DASHSCOPE_API_KEY"],
        )

    def chat(self, messages: list[dict], tools: list[dict], tool_choice: str = "auto") -> LLMResp:
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
            temperature=0.2,
        )
        msg = resp.choices[0].message
        calls = []
        for tc in (msg.tool_calls or []):
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            calls.append(ToolCallReq(id=tc.id, name=tc.function.name, arguments=args))
        return LLMResp(content=msg.content, tool_calls=calls)


class MockClient:
    """Deterministic offline agent. Not an LLM — a transparent stand-in."""
    model = "mock-local-rule"

    def __init__(self, features: FeatureVector, baseline: Baseline):
        self.features = features
        self.baseline = baseline

    def chat(self, messages: list[dict], tools: list[dict], tool_choice: str = "auto") -> LLMResp:
        already_ran = any(m.get("role") == "tool" for m in messages)
        if not already_ran:
            # first turn: "call" every tool once
            return LLMResp(tool_calls=[
                ToolCallReq(id=f"mock-{i}", name=t["function"]["name"],
                            arguments={"query": "wellbeing recovery movement"}
                            if t["function"]["name"] == "retrieve_wellbeing_context" else {})
                for i, t in enumerate(tools)
            ])
        # second turn: synthesise the final JSON from the real tool logic
        return LLMResp(content=json.dumps(self._final()))

    _LABELS = {"hr": "heart rate", "prv_rmssd": "HRV", "prv_sdnn": "HRV (SDNN)",
               "steadiness": "steadiness", "gait_regularity": "gait regularity"}
    _MOVEMENT = {"steadiness", "gait_regularity"}

    def _final(self) -> dict:
        f, b = self.features, self.baseline
        flag, devs = local_flag(f, b)

        if f.fall_flag:
            return {"flag": "elevated",
                    "headline": "A possible fall was detected.",
                    "why": "The device flagged a sudden movement that may be a fall. "
                           "This is a safety alert only.",
                    "cited_numbers": [f"motion index {f.motion_index:.1f}"],
                    "suggestion": "If you're hurt or unsure, please seek help; otherwise take a "
                                  "moment before continuing.",
                    "signpost": True, "clarify_question": None}

        cited = [f"HR {f.hr:.0f} bpm" + (f" (usually ~{b.means['hr']:.0f})"
                                         if f.still and b.means.get("hr") else "")]
        if f.still and f.prv_rmssd is not None:
            cited.append(f"HRV {f.prv_rmssd:.0f} ms"
                         + (f" (usually ~{b.means['prv_rmssd']:.0f})" if b.means.get("prv_rmssd") else ""))
        if f.activity == "walk" and f.cadence:
            cited.append(f"cadence {f.cadence:.0f} spm")
        if f.activity == "walk" and f.steadiness is not None:
            cited.append(f"steadiness {f.steadiness:.2f}")

        # ambiguity: raised resting pulse but no context yet -> ask before concluding
        clarify = None
        if flag != "steady" and f.still and devs.get("hr", 0) >= 1.0 and "answer" not in self._ctx():
            clarify = ("Your heart rate is above your usual for a still reading — "
                       "were you moving or exercising just now?")

        query = ("low HRV recovery sleep" if devs.get("prv_rmssd", 0) <= -1 else
                 "walking quality steadiness" if any(k in self._MOVEMENT and abs(v) >= 1 for k, v in devs.items()) else
                 "resting heart rate readiness" if devs.get("hr", 0) >= 1 else
                 "moving regularly wellbeing" if (f.sedentary_min or 0) > 120 else
                 "hydration temperature")
        cards = rag.retrieve(query, k=1)
        suggestion = _suggestion_from(cards[0]) if cards else \
            "Take a calm moment, hydrate, and see how the next readings look."

        if flag == "steady":
            headline, why = "You look steady versus your baseline.", \
                "Your readings sit within your own usual range this window."
        else:
            parts = []
            for k, z in devs.items():
                if abs(z) < 1.0:
                    continue
                ref = "vs a typical steady walk" if k in self._MOVEMENT else "vs your usual"
                parts.append(f"{self._LABELS.get(k, k)} {'+' if z > 0 else ''}{z:.1f}σ {ref}")
            drivers = "; ".join(parts)
            why = (f"Some readings are outside the expected range this window ({drivers}). "
                   "That can happen for everyday reasons like recent activity, caffeine, heat, "
                   "stress, or a short night.")
            headline = ("Worth a gentle watch versus your baseline." if flag == "watch"
                        else "This is elevated versus your baseline.")

        signpost = bool(flag == "elevated" or f.fall_flag)
        return {"flag": flag, "headline": headline, "why": why, "cited_numbers": cited,
                "suggestion": suggestion, "signpost": signpost, "clarify_question": clarify}

    def _ctx(self) -> dict:
        return getattr(self, "_context", {}) or {}


def _suggestion_from(card: dict) -> str:
    text = card.get("text", "")
    # take the last sentence of the card as a gentle, general nudge
    parts = [s.strip() for s in text.replace("\n", " ").split(".") if s.strip()]
    return (parts[-1] + ".") if parts else "Take a calm moment and see how the next readings look."


def make_client(features: FeatureVector, baseline: Baseline, context: Optional[dict] = None):
    force_mock = os.environ.get("FORCE_MOCK", "").lower() in ("1", "true", "yes")
    if not force_mock and os.environ.get("DASHSCOPE_API_KEY"):
        return DashScopeClient()
    mc = MockClient(features, baseline)
    mc._context = context or {}
    return mc
