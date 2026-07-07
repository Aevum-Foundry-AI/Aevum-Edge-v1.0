"""The Aevum Edge agent orchestrator — the plan -> act -> synthesise loop.

Qwen plans which tools to call, we execute them, feed results back, and it
synthesises a strict, diagnosis-free JSON read. Every tool call is recorded as
the trace — the trace IS the agentic evidence.
"""
from __future__ import annotations

import json

from .client import make_client
from .local_rule import deviations, local_flag
from .safety import SYSTEM_PROMPT, scrub
from .schemas import Baseline, FeatureVector, InterpretResponse, ToolCall
from .tools import TOOL_SCHEMAS, build_dispatch

MAX_STEPS = 5


def _features_brief(f: FeatureVector, b: Baseline, context: dict) -> str:
    lines = [
        "Interpret this window against the user's own baseline. Use the tools, then return the JSON.",
        f"Features: HR={f.hr} bpm, still={f.still}, activity={f.activity}, motion_index={f.motion_index}, "
        f"HRV_RMSSD={f.prv_rmssd}, HRV_SDNN={f.prv_sdnn}, SpO2={f.spo2}, cadence={f.cadence}, "
        f"gait_regularity={f.gait_regularity}, steadiness={f.steadiness}, fall_flag={f.fall_flag}, "
        f"skin_temp={f.skin_temp_c}, ambient_temp={f.ambient_temp_c}.",
        f"Baseline available: {'yes, n=' + str(b.n) if b.n else 'no (still learning this user)'}.",
    ]
    if context.get("answer"):
        lines.append(f"User answered a prior clarification: {context['answer']}")
    return "\n".join(lines)


def run_agent(features: FeatureVector, baseline: Baseline, context: dict | None = None,
              allow_clarify: bool = True) -> InterpretResponse:
    context = context or {}
    client = make_client(features, baseline, context)
    dispatch = build_dispatch(features, baseline)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _features_brief(features, baseline, context)},
    ]
    trace: list[ToolCall] = []
    final_content = None

    for _ in range(MAX_STEPS):
        resp = client.chat(messages, TOOL_SCHEMAS, tool_choice="auto")
        if resp.tool_calls:
            messages.append({
                "role": "assistant", "content": resp.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                    for tc in resp.tool_calls
                ],
            })
            for tc in resp.tool_calls:
                fn = dispatch.get(tc.name)
                result = fn(**tc.arguments) if fn else {"error": f"unknown tool {tc.name}"}
                trace.append(ToolCall(name=tc.name, args=tc.arguments,
                                      result_summary=_summarise(tc.name, result)))
                messages.append({"role": "tool", "tool_call_id": tc.id,
                                 "content": json.dumps(result)})
            continue
        final_content = resp.content
        break

    degraded = client.model.startswith("mock")
    obj = _parse(final_content)
    if obj is None:
        obj = _fallback(features, baseline)
        degraded = True

    obj, scrubbed = scrub(obj)
    if not allow_clarify:
        obj["clarify_question"] = None

    return InterpretResponse(
        flag=obj.get("flag", "steady"),
        headline=obj.get("headline", ""),
        why=obj.get("why", ""),
        cited_numbers=obj.get("cited_numbers", []) or [],
        suggestion=obj.get("suggestion", ""),
        signpost=bool(obj.get("signpost", False)),
        clarify_question=obj.get("clarify_question"),
        tool_trace=trace,
        model=client.model,
        degraded=degraded,
        scrubbed=scrubbed,
    )


def _summarise(name: str, result: dict) -> str:
    if name == "compare_to_baseline":
        return f"z-scores: {result.get('deviations_z', {})}" if result.get("have_baseline") else "no baseline yet"
    if name == "compute_cardiac_features":
        return f"HR {result.get('hr_bpm')} bpm, HRV reliable={result.get('hrv_reliable')}"
    if name == "analyse_movement":
        return f"activity={result.get('activity')}, fall={result.get('fall_flag')}"
    if name == "thermal_context":
        return f"skin-ambient diff={result.get('skin_minus_ambient_c')}"
    if name == "retrieve_wellbeing_context":
        return f"{result.get('count', 0)} card(s): " + ", ".join(c['title'] for c in result.get('cards', []))
    if name == "safety_signpost":
        return f"signpost={result.get('signpost')}"
    return "ok"


def _parse(content):
    if not content:
        return None
    txt = content.strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        txt = txt[txt.find("{"):]
    try:
        start, end = txt.find("{"), txt.rfind("}")
        return json.loads(txt[start:end + 1]) if start >= 0 else None
    except Exception:
        return None


def _fallback(features: FeatureVector, baseline: Baseline) -> dict:
    flag, devs = local_flag(features, baseline)
    return {
        "flag": flag,
        "headline": "Here's a gentle read against your baseline.",
        "why": "Based on how this window compares to your own usual range.",
        "cited_numbers": [f"HR {features.hr:.0f} bpm"],
        "suggestion": "Take a calm moment, hydrate, and see how the next readings look.",
        "signpost": bool(abs(max(devs.values(), default=0.0)) >= 3.0 or features.fall_flag),
        "clarify_question": None,
    }
