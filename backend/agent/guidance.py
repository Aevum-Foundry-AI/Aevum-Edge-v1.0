"""Guidance engine — card-grounded, dose-free, citation-locked wellbeing guidance.

The agent writes the warm connective prose, but under a CLOSED-SYSTEM contract:
- it may only draw on cards actually retrieved from the knowledge base;
- links are re-attached by US from those cards — never authored by the model —
  so the citation-lock is structural, not a promise the model has to keep;
- a dose / condition scrubber neutralises any drift before anything leaves here.

This mirrors the diagnosis-free posture of /interpret: the line is a sentence,
so we own every sentence — in code, not just in the prompt.
"""
from __future__ import annotations

import json
import os

from . import rag
from .client import DASHSCOPE_BASE_URL, DEFAULT_MODEL
from .safety import clean_guidance

DISCLAIMER = (
    "Wellbeing information only. This is not a medical device and does not "
    "diagnose, treat, or name any condition. Guidance is general and drawn from "
    "the cited wellbeing sources; if something persists or you feel unwell, "
    "please see a qualified professional."
)

# topic -> retrieval query, each tuned to land on the intended card
_TOPIC_QUERIES = {
    "hydration": "hydration heat electrolytes sweat water salts warm temperature",
    "warmth":    "cold weather warm layers circulation keep moving",
    "movement":  "movement mood anxious low walk outdoors activity break up sitting",
    "sleep":     "sleep wind down light consistent screens caffeine recovery",
    "recovery":  "heart rate variability recovery rested fatigue earlier night",
    "stress":    "stress calm breathing arousal settle",
}

_GUIDANCE_SYSTEM = """You are the guidance voice of Aevum Edge Sentinel, a privacy-first WELLBEING wearable.
You write short, warm, plain-language wellbeing guidance for ONE person, tied to their day.

You are given a set of CARDS retrieved from a vetted wellbeing knowledge base. These cards are the
ONLY source you may draw on. Absolute rules — never break these:
- Only recommend things that appear in the provided cards. Never introduce advice that is not in a card.
- NEVER state a dose, quantity, number of milligrams / IU / grams, or any supplement amount.
- NEVER name, infer, or hint at any medical or psychological condition or disease. No diagnosis.
- Do NOT invent citations, studies, or links. You are given no URLs and must not produce any.
- Be calm, kind, specific to their situation, and brief: 2-3 sentences per card.

Return STRICT JSON only, no prose around it:
{
  "lead": "one warm sentence tying today's situation together",
  "items": [ { "topic": "<the card's topic id>", "guidance": "2-3 sentence guidance grounded in that card" } ]
}
Use only the topic ids you are given. Return only the JSON object."""


# --------------------------------------------------------------------------- #
# context -> topics -> retrieved cards
# --------------------------------------------------------------------------- #
def _build_topics(ctx: dict) -> list[str]:
    weather = (ctx.get("weather") or "mild").lower()
    moods = [str(m).lower() for m in (ctx.get("moods") or [])]
    tags = [str(t).lower() for t in (ctx.get("tags") or [])]
    rec = ctx.get("recovery_pct")

    topics: list[str] = []
    if weather == "hot":
        topics.append("hydration")
    elif weather == "cold":
        topics.append("warmth")
    if isinstance(rec, (int, float)) and rec < 60:
        topics.append("recovery")
    if any(m in ("anxious", "low", "overworked", "tired") for m in moods):
        topics.append("movement")
    if any(m in ("anxious", "overworked") for m in moods):
        topics.append("stress")
    # sleep is a near-universal lever; include if logged, else as a gentle staple
    if any(("late" in t or "caffeine" in t or "slept" in t) for t in tags):
        topics.insert(0 if not topics else 1, "sleep")
    else:
        topics.append("sleep")

    seen: set[str] = set()
    ordered = [t for t in topics if not (t in seen or seen.add(t))]
    return ordered[:4] or ["sleep", "movement"]


def _retrieve_cards(topics: list[str]) -> list[dict]:
    cards: list[dict] = []
    seen_titles: set[str] = set()
    for t in topics:
        hits = rag.retrieve(_TOPIC_QUERIES.get(t, t), k=1)
        if not hits:
            continue
        c = dict(hits[0])
        c["topic"] = t
        if c["title"] in seen_titles:
            continue
        seen_titles.add(c["title"])
        cards.append(c)
    return cards


# --------------------------------------------------------------------------- #
# situation description / lead
# --------------------------------------------------------------------------- #
def _situation_line(ctx: dict, lead: bool = False) -> str:
    weather = (ctx.get("weather") or "mild").lower()
    moods = [str(m).lower() for m in (ctx.get("moods") or [])]
    tags = [str(t).lower() for t in (ctx.get("tags") or [])]
    rec = ctx.get("recovery_pct")
    bits = []
    if weather == "hot":
        bits.append("it's warm out")
    elif weather == "cold":
        bits.append("it's cold out")
    if isinstance(rec, (int, float)):
        if rec < 60:
            bits.append("your recovery's been running below your usual")
        elif rec >= 75:
            bits.append("your recovery looks strong")
    if moods:
        bits.append("you've logged feeling " + " and ".join(moods[:2]))
    if tags:
        bits.append("you noted " + ", ".join(tags[:2]))
    if not bits:
        return ("Here's what's worth a gentle bit of attention today." if lead
                else "a fairly typical day, nothing standing out")
    joined = "; ".join(bits)
    if lead:
        return "Given that " + joined + ", here's what's most worth your attention today."
    return joined


def _card_fallback(card: dict) -> str:
    """A safe, vetted sentence straight from the card body (used if the model
    drifts or returns nothing) — this is guaranteed on-source. We drop the
    trailing 'this is general guidance, not a measure' meta-sentences and surface
    the actionable part of the card."""
    text = (card.get("text") or "").replace("\n", " ")
    sents = [s.strip() for s in text.split(".") if s.strip()]
    if not sents:
        return "Take a calm moment and see how the next readings look."

    def _is_meta(s: str) -> bool:
        s = s.lower()
        return any(p in s for p in (
            "not a medical", "not a prescription", "not a measure",
            "general comfort guidance", "general wellbeing encouragement",
            "framed as", "encouragement, not", "not instruction", "not a diagnosis",
        ))

    core = [s for s in sents if not _is_meta(s)] or sents
    picked = core[-1]
    if len(picked) < 70 and len(core) >= 2:
        picked = core[-2] + ". " + picked
    return picked + "."


# --------------------------------------------------------------------------- #
# generation: live Qwen (primary) or deterministic offline stand-in
# --------------------------------------------------------------------------- #
def _parse_json(txt: str) -> dict:
    txt = (txt or "").strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        # drop an optional leading "json" language tag
        nl = txt.find("\n")
        if nl != -1 and txt[:nl].strip().lower() in ("json", ""):
            txt = txt[nl + 1:]
    try:
        obj = json.loads(txt)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        start, end = txt.find("{"), txt.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(txt[start:end + 1])
            except Exception:
                return {}
        return {}


def _generate_live(situation: str, payload_cards: list[dict]) -> dict:
    from openai import OpenAI  # lazy import so the mock path needs no dep
    client = OpenAI(base_url=DASHSCOPE_BASE_URL, api_key=os.environ["DASHSCOPE_API_KEY"])
    user = ("Today's situation: " + situation + "\n\nCARDS (your only source):\n"
            + json.dumps(payload_cards, ensure_ascii=False))
    resp = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=[
            {"role": "system", "content": _GUIDANCE_SYSTEM},
            {"role": "user", "content": user},
        ],
        temperature=0.3,
    )
    return _parse_json(resp.choices[0].message.content or "{}")


def _generate_mock(ctx: dict, cards: list[dict]) -> dict:
    """Deterministic offline stand-in: warm prose composed straight from card
    text. Not an LLM — a transparent, on-source fallback (and resilience story)."""
    items = []
    for c in cards:
        items.append({"topic": c["topic"], "guidance": _card_fallback(c)})
    return {"lead": _situation_line(ctx, lead=True), "items": items}


def _generate(ctx: dict, cards: list[dict]) -> tuple[dict, str]:
    payload_cards = [{"topic": c["topic"], "title": c["title"], "text": c["text"]} for c in cards]
    situation = _situation_line(ctx)
    force_mock = os.environ.get("FORCE_MOCK", "").lower() in ("1", "true", "yes")
    if not force_mock and os.environ.get("DASHSCOPE_API_KEY"):
        try:
            return _generate_live(situation, payload_cards), "live"
        except Exception:
            pass  # fail safe to the on-source stand-in rather than erroring
    return _generate_mock(ctx, cards), "offline-mock"


# --------------------------------------------------------------------------- #
# public entry point
# --------------------------------------------------------------------------- #
def guidance(ctx: dict | None = None) -> dict:
    ctx = ctx or {}
    topics = _build_topics(ctx)
    cards = _retrieve_cards(topics)
    by_topic = {c["topic"]: c for c in cards}

    gen, mode = _generate(ctx, cards)
    scrubbed_any = False
    out_cards: list[dict] = []

    for item in gen.get("items", []):
        card = by_topic.get(item.get("topic"))
        if not card:  # citation-lock: anything not grounded in a retrieved card is dropped
            continue
        text, sc = clean_guidance(item.get("guidance", ""), fallback=_card_fallback(card))
        scrubbed_any = scrubbed_any or sc
        out_cards.append({
            "topic": card["topic"],
            "title": card["title"],
            "guidance": text,
            "links": card.get("links", []),   # links come from the card, never the model
            "care": card.get("care", ""),
            "source": card.get("source", ""),
        })

    # if the model returned nothing usable, ground straight from the cards
    if not out_cards:
        for c in cards:
            text, _ = clean_guidance(_card_fallback(c))
            out_cards.append({
                "topic": c["topic"], "title": c["title"], "guidance": text,
                "links": c.get("links", []), "care": c.get("care", ""),
                "source": c.get("source", ""),
            })

    lead, sc_lead = clean_guidance(gen.get("lead") or _situation_line(ctx, lead=True))
    scrubbed_any = scrubbed_any or sc_lead

    return {
        "lead": lead,
        "cards": out_cards[:4],
        "grounded": True,
        "scrubbed": scrubbed_any,
        "mode": mode,
        "disclaimer": DISCLAIMER,
    }
