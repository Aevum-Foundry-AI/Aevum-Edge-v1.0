"""The diagnosis-free safety layer — the governing guard on everything the agent says.

Two lines of defence:
1. a tightly constrained system prompt (wellbeing vocabulary, explicit
   prohibitions, strict output contract);
2. a post-generation scrubber that catches any drift toward naming or inferring
   a condition and neutralises it, failing safe to a generic wellbeing message.

The line is a sentence, so we own every sentence — in code, not just in the prompt.
"""
from __future__ import annotations

import re

SYSTEM_PROMPT = """You are the reasoning core of Aevum Edge Sentinel, a privacy-first WELLBEING wearable.

You receive DERIVED features from a wrist device and tool results, and you return a calm,
plain-language WELLBEING read compared to THIS user's own baseline.

ABSOLUTE RULES — never break these:
- You are NOT a medical device. You NEVER diagnose, screen for, name, infer, or hint at any
  medical, psychiatric, physiotherapy, or musculoskeletal condition or disease.
- You NEVER say or imply "you have", "this indicates", "symptoms of", "signs of [condition]",
  or name any condition (e.g. do not use words like arrhythmia, afib, tachycardia, bradycardia,
  hypertension, diabetes, Parkinson's, apnoea, depression, anxiety disorder, sarcopenia, etc.).
- You describe observations and change relative to the user's OWN baseline only.
- Your only verdict is one of: "steady", "watch", or "elevated" (vs their baseline).
- You give GENERAL wellbeing suggestions (rest, hydration, movement, sleep, calm) grounded in the
  retrieved wellbeing context — never clinical or treatment advice.
- If something is persistently outside the user's range or they may feel unwell, set a signpost to
  "consider seeing a qualified professional" — a prompt to talk to a person, never a conclusion.
- Be calm and non-alarming. Cite the actual numbers you used.

Return STRICT JSON with exactly these keys:
{
  "flag": "steady" | "watch" | "elevated",
  "headline": short calm sentence,
  "why": plain-language explanation citing the numbers, comparing to baseline,
  "cited_numbers": [strings like "HR 82 bpm (usually ~68)"],
  "suggestion": one general wellbeing suggestion,
  "signpost": true | false,
  "clarify_question": a single question if genuinely ambiguous (e.g. recent exercise), else null
}
Return only the JSON object, no prose around it."""

# condition / diagnostic lexicon — presence of any of these in output is drift
_CONDITION_TERMS = [
    "arrhythmia", "afib", "a-fib", "atrial fibrillation", "tachycardia", "bradycardia",
    "hypertension", "hypotension", "diabetes", "diabetic", "parkinson", "epilep",
    "apnoea", "apnea", "sarcopenia", "osteopenia", "osteoporosis", "depression",
    "anxiety disorder", "ptsd", "adhd", "autism", "asd", "dementia", "alzheimer",
    "stroke", "infarction", "ischaem", "ischem", "sepsis", "covid", "influenza",
    "disease", "disorder", "syndrome", "pathology",
    # naming a specialty implies a specific problem -> not the allowed generic signpost
    "cardiologist", "neurologist", "psychiatrist", "physiotherapist",
    "dermatologist", "endocrinologist", "oncologist", "rheumatologist",
]
_DIAG_PATTERNS = [
    re.compile(r"\byou (?:have|may have|might have|likely have|could have)\b", re.I),
    re.compile(r"\b(?:symptom|symptoms|signs) of\b", re.I),
    re.compile(r"\bindicat(?:es|ive of)\b", re.I),
    re.compile(r"\bsuffer(?:ing)? from\b", re.I),
    re.compile(r"\bconsistent with\b", re.I),
    re.compile(r"\bsuggests? (?:a|an|the) (?:condition|disease|disorder)\b", re.I),
    re.compile(r"\bdiagnos(?:e|es|ing)\s+you\b", re.I),
    re.compile(r"\byour\s+diagnosis\b", re.I),
]

_SAFE_FALLBACK = {
    "headline": "Here's a gentle read against your baseline.",
    "why": "Some of your readings sit a little away from your own usual range this window. "
           "That can happen for everyday reasons like recent activity, caffeine, heat, stress, "
           "or a short night.",
    "suggestion": "Take a calm moment, hydrate, and see how the next readings look.",
}


def _hits(text: str) -> bool:
    low = text.lower()
    if any(term in low for term in _CONDITION_TERMS):
        return True
    return any(p.search(text) for p in _DIAG_PATTERNS)


def scrub(obj: dict) -> tuple[dict, bool]:
    """Neutralise any diagnostic/condition drift in the free-text fields.

    Returns (clean_obj, was_scrubbed). Text fields that trip the guard are
    replaced with safe generic wellbeing text and a signpost is raised.
    """
    scrubbed = False
    clean = dict(obj)
    for field in ("headline", "why", "suggestion"):
        val = str(clean.get(field, "") or "")
        if val and _hits(val):
            clean[field] = _SAFE_FALLBACK.get(field, "")
            scrubbed = True
    # a naming attempt is exactly when a human should be looped in
    if scrubbed:
        clean["signpost"] = True
        # scrub cited numbers of any stray condition words too
        cn = clean.get("cited_numbers") or []
        clean["cited_numbers"] = [c for c in cn if not _hits(str(c))]
        # never let a condition name survive in the clarify question
        cq = clean.get("clarify_question")
        if cq and _hits(str(cq)):
            clean["clarify_question"] = None
    return clean, scrubbed


# --- dose / quantity guard (guidance path) -------------------------------------
# The guidance voice gives foods and habits, never amounts. Any number followed by
# a dose unit is drift toward prescription and is neutralised.
_DOSE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s?(?:mg|mcg|µg|ug|g|kg|iu|ml|l|litres?|liters?|oz|ounces?|units?|"
    r"tablets?|capsules?|servings?|grams?|milligrams?|micrograms?)\b",
    re.I,
)


def strip_doses(text: str) -> tuple[str, bool]:
    """Replace any explicit dose/quantity with a neutral phrase."""
    new = _DOSE.sub("a sensible amount", text)
    return new, (new != text)


def clean_guidance(text: str, fallback: str = "") -> tuple[str, bool]:
    """Neutralise diagnostic drift and strip any dose from a guidance sentence.

    Returns (clean_text, was_scrubbed). Condition/diagnosis drift falls back to
    vetted card text; a dose is stripped in place.
    """
    scrubbed = False
    text = str(text or "")
    if _hits(text):
        text = fallback or _SAFE_FALLBACK["suggestion"]
        scrubbed = True
    text, d = strip_doses(text)
    return text, (scrubbed or d)
