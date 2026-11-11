"""Optional language layer (any OpenAI-compatible chat endpoint).

The model has three reversible roles and never decides a geometric fact:

1. **routing** - turn a question into one tool call ``{"tool", "args"}``;
2. **phrasing** - write the answer from the facts returned by the tool;
3. **interpretation** - a cautious hypothesis on the function of an assembly, from the
   structural facts only, clearly marked as a hypothesis.

Configuration: ``LLM_API_KEY`` (required), ``LLM_BASE_URL`` (default NVIDIA NIM),
``LLM_MODEL`` (default ``google/gemma-4-31b-it``). Without a key the assistant works
offline with the rule router and the deterministic tool text. Hosted endpoints may bill
each call.
"""
from __future__ import annotations

import json
import os
from typing import Optional

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "google/gemma-4-31b-it"

ROUTER_PROMPT = (
    "You are the router of a CAD assistant. You receive a question about ONE assembly "
    "that is already loaded, the list of tools and the list of part ids. Choose EXACTLY one "
    "tool and its arguments. The 'aid' argument is already known: do not provide it. If a "
    "tool needs 'part', use the part id quoted in the question. Answer ONLY with compact "
    'JSON: {"tool": "...", "args": {...}}. No other text.'
)
PHRASE_PROMPT = (
    "You are a mechanical CAD assistant. Answer the question STRICTLY from the FACTS "
    "provided (computed by a geometric kernel). Do not add any number or claim that is not "
    "in the facts. If the facts are not enough, say so. Concise answer (2-5 sentences)."
)
INTERPRET_PROMPT = (
    "You are an experienced mechanical CAD engineer. From the STRUCTURAL FACTS provided "
    "(geometry only: number and shape of parts, sizes, contacts, shared axes), give a "
    "CAUTIOUS interpretation of the likely nature or function of the assembly. Parts are "
    "anonymous: reason only on shapes, sizes and contacts. State hypotheses explicitly "
    "('probably', 'this suggests'), do not invent named components, flag the uncertainty "
    "and end with what is missing to conclude. 4-6 sentences."
)


class LLM:
    def __init__(self, model: Optional[str] = None, base_url: Optional[str] = None,
                 api_key: Optional[str] = None):
        self.model = model or os.environ.get("LLM_MODEL", DEFAULT_MODEL)
        self.client = None
        self.error = None
        key = api_key or os.environ.get("LLM_API_KEY")
        if not key:
            self.error = "LLM_API_KEY is not set"
            return
        try:
            from openai import OpenAI
            self.client = OpenAI(base_url=base_url or os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL),
                                 api_key=key)
        except Exception as e:   # openai not installed, bad URL...
            self.error = f"client unavailable: {e}"

    @property
    def available(self) -> bool:
        return self.client is not None

    def _chat(self, system, user, max_tokens=400, temperature=0.2) -> str:
        resp = self.client.chat.completions.create(
            model=self.model, max_tokens=max_tokens, temperature=temperature,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        return (resp.choices[0].message.content or "").strip()

    def route(self, question, catalog, part_ids):
        if not self.available:
            return None
        cat = "\n".join(f"- {n}({', '.join(p)}): {d}" for n, (d, p) in catalog.items())
        user = f"TOOLS:\n{cat}\n\nPARTS: {', '.join(part_ids)}\n\nQUESTION: {question}"
        try:
            obj = extract_json(self._chat(ROUTER_PROMPT, user, 120, 0.0))
        except Exception:
            return None
        if not isinstance(obj, dict) or "tool" not in obj:
            return None
        args = obj.get("args") if isinstance(obj.get("args"), dict) else {}
        args.pop("aid", None)
        return {"tool": obj["tool"], "args": args}

    def phrase(self, question, facts):
        if not self.available:
            return None
        try:
            return self._chat(PHRASE_PROMPT, f"FACTS:\n{facts}\n\nQUESTION: {question}\n\nAnswer:") or None
        except Exception:
            return None

    def interpret(self, question, facts):
        if not self.available:
            return None
        try:
            return self._chat(INTERPRET_PROMPT, f"STRUCTURAL FACTS:\n{facts}\n\nQUESTION: {question}\n\n"
                                                "Cautious interpretation:", 500, 0.3) or None
        except Exception:
            return None


def extract_json(text: str):
    """First JSON object of a model answer (tolerates fences and chatter)."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except Exception:
        pass
    depth, start = 0, -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(text[start:i + 1])
                except Exception:
                    return None
    return None
