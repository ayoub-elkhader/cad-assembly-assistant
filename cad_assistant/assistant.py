"""CAD assistant: natural-language question -> grounded answer.

Pipeline: ROUTING (LLM or keyword rules) -> deterministic TOOL -> PHRASING (LLM or the
tool text). The answer always comes from the tool facts. Without an LLM key everything
still works offline.

    cad-assistant --facts examples/ -a shaft_stack -q "in which order can I take it apart?"
    cad-assistant --step my_assembly.step            # computes the facts, then opens a REPL
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from . import tools
from .facts import AssemblyIndex
from .llm import LLM

# Questions about function or purpose have no deterministic answer: they go to the
# (optional) interpretation path, on top of the structural facts.
INTERPRET_KW = (
    "what is it for", "what is this for", "what does it do", "purpose", "function",
    "used for", "what kind of", "what type of mechanism", "how does it work", "guess",
    "interpret", "what could it be", "your opinion",
)


def is_interpretive(question: str) -> bool:
    q = question.lower()
    return any(k in q for k in INTERPRET_KW)


def rule_route(question: str, part_ids) -> dict:
    """Keyword router; always available, no network."""
    q = question.lower()
    part = next((p for p in sorted(part_ids, key=len, reverse=True)
                 if re.search(r"\b" + re.escape(p.lower()) + r"\b", q)), None)

    def has(*ks):
        return any(k in q for k in ks)

    if part and has("neighbo", "touch", "contact", "connected", "adjacent"):
        return {"tool": "neighbors", "args": {"part": part}}
    if part and has("size", "dimension", "type", "info", "detail", "what is", "describe"):
        return {"tool": "part_info", "args": {"part": part}}
    if has("how many") and has("part", "component", "piece"):
        return {"tool": "part_count", "args": {}}
    if has("coaxial", "same axis", "share an axis", "shared axis", "common axis", "stacked"):
        return {"tool": "coaxial_groups", "args": {}}
    if has("joint", "revolute", "slider", "hinge", "degree of freedom", "dof", "mating"):
        return {"tool": "joints", "args": {}}
    if has("disassembl", "take it apart", "take apart", "dismantl", "remove", "removal"):
        return {"tool": "disassembly", "args": {}}
    if has("assembly order", "assemble", "put together", "build order", "mount"):
        return {"tool": "assembly_order", "args": {}}
    if has("graph", "contact", "touch", "connected", "relation"):
        return {"tool": "contact_graph", "args": {}}
    if has("bill of material", "bom", "list the parts", "list of parts", "which parts", "inventory"):
        return {"tool": "bom", "args": {}}
    if has("summary", "summarize", "summarise", "overview", "describe"):
        return {"tool": "summary", "args": {}}
    if part:
        return {"tool": "part_info", "args": {"part": part}}
    return {"tool": "summary", "args": {}}


class Assistant:
    def __init__(self, index: AssemblyIndex, use_llm: bool = True, llm: LLM = None):
        self.idx = index
        self.llm = llm or (LLM() if use_llm else None)
        self.use_llm = bool(use_llm and self.llm and self.llm.available)

    def catalog(self):
        return {n: (desc, params) for n, (_, desc, params) in tools.TOOLS.items()}

    def route(self, question, aid):
        a = self.idx.get(aid)
        part_ids = a["part_ids"] if a else []
        if self.use_llm:
            r = self.llm.route(question, self.catalog(), part_ids)
            if r and r.get("tool") in tools.TOOLS:
                return r, "llm"
        return rule_route(question, part_ids), "rules"

    def ask(self, aid, question):
        if is_interpretive(question):
            bundle = tools.call(self.idx, "evidence_bundle", aid=aid)
            if not bundle.get("ok"):
                return {"answer": bundle["error"], "tool": "evidence_bundle", "routing": "rules",
                        "grounded": False, "evidence": bundle}
            if self.use_llm:
                guess = self.llm.interpret(question, bundle["text"])
                if guess:
                    return {"answer": "Interpretation (hypothesis from the geometry only, anonymous "
                                      "parts):\n\n" + guess,
                            "tool": "interpretation", "routing": "llm", "grounded": True,
                            "evidence": bundle}
            return {"answer": bundle["text"] + "\n\n(Interpretive question: no function is recorded "
                                               "in the data. Enable an LLM for a reasoned hypothesis.)",
                    "tool": "interpretation", "routing": "rules", "grounded": True, "evidence": bundle}

        route, how = self.route(question, aid)
        evidence = tools.call(self.idx, route["tool"], aid=aid, **route.get("args", {}))
        if not evidence.get("ok"):
            return {"answer": evidence.get("error", "I cannot answer."), "tool": route["tool"],
                    "routing": how, "grounded": False, "evidence": evidence}
        answer = evidence["text"]
        if self.use_llm:
            answer = self.llm.phrase(question, evidence["text"]) or answer
        return {"answer": answer, "tool": route["tool"], "routing": how, "grounded": True,
                "evidence": evidence}


def _load_index(a) -> AssemblyIndex:
    if a.step:
        from .facts import facts_from_step
        facts = facts_from_step(a.step)
        if a.save_facts:
            Path(a.save_facts).write_text(json.dumps(facts, indent=2), encoding="utf-8")
        return AssemblyIndex([facts])
    return AssemblyIndex.from_folder(a.facts)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cad-assistant", description="Questions about CAD assemblies.")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--facts", default="examples", help="folder of facts JSON files")
    src.add_argument("--step", help="compute the facts of a STEP file first (needs pythonocc-core)")
    ap.add_argument("--save-facts", help="with --step: also write the facts to this JSON file")
    ap.add_argument("-a", "--assembly", help="assembly id")
    ap.add_argument("-q", "--question", help="single question (otherwise interactive)")
    ap.add_argument("--no-llm", action="store_true", help="offline: rule router and tool text")
    a = ap.parse_args(argv)

    idx = _load_index(a)
    if not idx.ids():
        print("No assembly found.")
        return 1
    aid = a.assembly or idx.ids()[0]
    if idx.get(aid) is None:
        print(f"Unknown assembly '{aid}'. Available: {', '.join(idx.ids())}")
        return 1
    bot = Assistant(idx, use_llm=not a.no_llm)
    mode = "LLM + tools" if bot.use_llm else "tools only (offline)"
    if a.question:
        r = bot.ask(aid, a.question)
        print(f"[tool: {r['tool']} | routing: {r['routing']}]")
        print(r["answer"])
        return 0
    print(f"CAD assistant - {aid} ({idx.get(aid)['nb_parts']} parts) - {mode}. Type 'quit' to leave.")
    while True:
        try:
            q = input("Q> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if q.lower() in ("", "q", "quit", "exit"):
            break
        r = bot.ask(aid, q)
        print(f"[tool: {r['tool']} | routing: {r['routing']}]\n{r['answer']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
