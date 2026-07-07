"""Retrieval over a small, licence-clean wellbeing knowledge base.

The agent grounds its explanations and suggestions in retrieved cards rather
than inventing advice — the inspectable-RAG pattern for trust-critical output.

Deliberately lightweight: a pure-Python BM25 over a handful of markdown cards.
No vector database, no heavy ML dependency, deploys anywhere. (If you later want
embedding retrieval, the Qwen Cloud text-embedding endpoint slots in behind the
same `retrieve()` signature.)

CONTENT RULE: general wellbeing / movement / recovery only. NEVER clinical
guidelines or physiotherapy treatment protocols — that would breach both the
diagnosis-free line and licensing.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field

_KB_DIR = os.environ.get("KB_DIR", os.path.join(os.path.dirname(__file__), "..", "kb", "wellbeing"))
_TOKEN = re.compile(r"[a-z0-9]+")


def _tok(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


@dataclass
class Card:
    title: str
    text: str
    source: str
    tokens: list[str]
    links: list = field(default_factory=list)  # list of [label, url]
    care: str = ""


class KnowledgeBase:
    def __init__(self, cards: list[Card]):
        self.cards = cards
        self.N = len(cards)
        self.avgdl = (sum(len(c.tokens) for c in cards) / self.N) if self.N else 0.0
        self.df: dict[str, int] = {}
        for c in cards:
            for t in set(c.tokens):
                self.df[t] = self.df.get(t, 0) + 1

    def _idf(self, term: str) -> float:
        n = self.df.get(term, 0)
        return math.log(1 + (self.N - n + 0.5) / (n + 0.5))

    def retrieve(self, query: str, k: int = 3, k1: float = 1.5, b: float = 0.75) -> list[Card]:
        q = _tok(query)
        scored = []
        for c in self.cards:
            tf: dict[str, int] = {}
            for t in c.tokens:
                tf[t] = tf.get(t, 0) + 1
            dl = len(c.tokens) or 1
            score = 0.0
            for term in q:
                if term not in tf:
                    continue
                f = tf[term]
                score += self._idf(term) * (f * (k1 + 1)) / (f + k1 * (1 - b + b * dl / (self.avgdl or 1)))
            if score > 0:
                scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in scored[:k]]


def _parse_card(path: str) -> Card:
    with open(path) as f:
        raw = f.read()
    title, source = os.path.basename(path), "general wellbeing guidance"
    links: list = []
    care = ""
    body = raw
    # optional front-matter: title/source/links/care lines before a blank line
    m = re.match(r"^(?:(title|source|links|care):.*\n)+\n", raw, re.IGNORECASE)
    if m:
        head, body = raw[: m.end()], raw[m.end():]
        for line in head.splitlines():
            if ":" not in line:
                continue
            key, val = line.split(":", 1)
            key, val = key.strip().lower(), val.strip()
            if key == "title":
                title = val
            elif key == "source":
                source = val
            elif key == "care":
                care = val
            elif key == "links":
                # entries: "Label | https://url ;; Label2 | https://url2"
                for entry in val.split(";;"):
                    entry = entry.strip()
                    if "|" in entry:
                        label, url = entry.split("|", 1)
                        if url.strip().startswith("http"):
                            links.append([label.strip(), url.strip()])
    return Card(title=title, text=body.strip(), source=source,
                tokens=_tok(title + " " + body), links=links, care=care)


def load_kb(kb_dir: str = _KB_DIR) -> KnowledgeBase:
    cards: list[Card] = []
    if os.path.isdir(kb_dir):
        for fn in sorted(os.listdir(kb_dir)):
            if fn.endswith(".md"):
                cards.append(_parse_card(os.path.join(kb_dir, fn)))
    return KnowledgeBase(cards)


_KB: KnowledgeBase | None = None


def retrieve(query: str, k: int = 3) -> list[dict]:
    global _KB
    if _KB is None:
        _KB = load_kb()
    return [{"title": c.title, "text": c.text, "source": c.source,
             "links": c.links, "care": c.care} for c in _KB.retrieve(query, k)]
