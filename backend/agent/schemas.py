"""Pydantic schemas for Aevum Edge Sentinel.

Only DERIVED features ever reach this backend — never raw PPG/motion waveforms.
The output contract is deliberately constrained so the agent can only ever
return a wellbeing read (steady / watch / elevated vs the user's own baseline),
never a diagnosis or a condition name.
"""
from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field

Flag = Literal["steady", "watch", "elevated"]


class FeatureVector(BaseModel):
    """The compact, privacy-safe payload the wrist device sends per window.

    These are features, not signals. A handful of numbers — this is the whole
    point of the edge design and the data-minimisation metric.
    """
    # cardiac (from PPG / MAX30102)
    hr: float = Field(..., description="mean heart rate, bpm")
    prv_rmssd: Optional[float] = Field(None, description="pulse-rate variability RMSSD, ms (only when still)")
    prv_sdnn: Optional[float] = Field(None, description="pulse-rate variability SDNN, ms (only when still)")
    spo2: Optional[float] = Field(None, description="blood-oxygen saturation, %")
    # movement (from IMU / MPU-6050)
    still: bool = Field(False, description="device reports the user was still this window")
    activity: Optional[str] = Field(None, description="rest | walk | active (on-device activity class)")
    motion_index: float = Field(0.0, description="scalar motion intensity for the window")
    cadence: Optional[float] = Field(None, description="steps/min when walking")
    gait_regularity: Optional[float] = Field(None, description="0..1, stride regularity when walking")
    steadiness: Optional[float] = Field(None, description="0..1, higher = steadier (tremor proxy)")
    sedentary_min: Optional[float] = Field(None, description="minutes sedentary in the trailing window")
    fall_flag: bool = Field(False, description="on-device fall/safety flag")
    # thermal
    skin_temp_c: Optional[float] = Field(None, description="skin-contact temperature, C (MAX30102 on-die)")
    ambient_temp_c: Optional[float] = Field(None, description="ambient temperature, C (BME280)")
    humidity: Optional[float] = Field(None, description="ambient relative humidity, %")
    # meta
    window_s: float = Field(4.0, description="length of the sampling window, seconds")
    ts: Optional[float] = Field(None, description="device timestamp (epoch seconds)")


class Baseline(BaseModel):
    """Per-user rolling baseline. Keyed by an OPAQUE token — never identity."""
    means: dict[str, float] = Field(default_factory=dict)
    sds: dict[str, float] = Field(default_factory=dict)
    n: int = 0
    updated_at: Optional[float] = None


class InterpretRequest(BaseModel):
    consent_token: str = Field(..., description="fail-closed: no valid token, no processing")
    device_token: str = Field(..., description="opaque per-device id for the baseline; carries no identity")
    features: FeatureVector
    context: dict = Field(default_factory=dict, description="e.g. {'answer': 'yes, I was exercising'} for multi-turn")
    allow_clarify: bool = True
    supplied_baseline: Optional[Baseline] = Field(
        None, description="privacy mode: device supplies its own baseline; backend stays stateless"
    )


class ToolCall(BaseModel):
    name: str
    args: dict = Field(default_factory=dict)
    result_summary: str = ""


class InterpretResponse(BaseModel):
    flag: Flag
    headline: str
    why: str
    cited_numbers: list[str] = Field(default_factory=list)
    suggestion: str
    signpost: bool = False
    clarify_question: Optional[str] = None
    tool_trace: list[ToolCall] = Field(default_factory=list)
    model: str = ""
    degraded: bool = False
    scrubbed: bool = False
    disclaimer: str = (
        "Wellbeing information only. This is not a medical device and does not "
        "diagnose, treat, or name any condition. If something persists or you feel "
        "unwell, please see a qualified professional."
    )
