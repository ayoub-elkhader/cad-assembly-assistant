"""Offline evaluation of the rule router and of answer grounding.

For every indexed assembly, a fixed set of English questions is asked; the expected tool
and an expected fact (computed independently from the facts) are known. Two numbers:

* routing: the assistant chose the expected tool;
* grounding: the answer contains the expected fact.

The question set is small and was written by the author together with the router, so the
result measures consistency, not generalisation to unseen phrasings.

    python -m cad_assistant.evaluate --facts examples/
"""
from __future__ import annotations

import argparse
import sys

from .assistant import Assistant
from .facts import AssemblyIndex


def cases(a):
    p0 = a["part_ids"][0]
    nb0 = a["adj"].get(p0, [])
    d = a["disassembly"]
    return [
        ("How many parts does this assembly have?", "part_count", str(a["nb_parts"])),
        ("Give me the bill of materials.", "bom", p0),
        ("Give me an overview of the assembly.", "summary", str(a["nb_parts"])),
        ("Which parts touch each other?", "contact_graph", None),
        ("Which parts share the same axis?", "coaxial_groups", None),
        ("What are the mechanical joints?", "joints", None),
        ("In which order can I take it apart?", "disassembly", "FOUND" if d.get("feasible") else None),
        ("What is the assembly order?", "assembly_order", None),
        (f"What is the size of {p0}?", "part_info", p0),
        (f"Which parts are in contact with {p0}?", "neighbors", nb0[0] if nb0 else None),
    ]


def run(index: AssemblyIndex, verbose=False):
    bot = Assistant(index, use_llm=False)
    r_ok = r_tot = f_ok = f_tot = 0
    for aid in index.ids():
        for q, tool, needle in cases(index.get(aid)):
            res = bot.ask(aid, q)
            hit = res["tool"] == tool
            r_ok += hit
            r_tot += 1
            if needle is not None:
                f_tot += 1
                f_ok += hit and needle.lower() in res["evidence"].get("text", "").lower()
            if verbose or not hit:
                print(f"[{'ok' if hit else 'XX'}] {aid}: {q!r} expected {tool}, got {res['tool']}")
    return r_ok, r_tot, f_ok, f_tot


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--facts", default="examples")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)
    idx = AssemblyIndex.from_folder(a.facts)
    r_ok, r_tot, f_ok, f_tot = run(idx, a.verbose)
    print(f"assemblies: {len(idx.ids())}")
    print(f"routing:   {r_ok}/{r_tot}")
    print(f"grounding: {f_ok}/{f_tot}")
    return 0 if r_ok == r_tot else 1


if __name__ == "__main__":
    sys.exit(main())
