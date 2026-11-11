"""Regenerate examples/*.json from the synthetic samples of exploded-view-verifier.

    python scripts/build_examples.py
"""
import json
from pathlib import Path

from exploded_view_verifier import samples

from cad_assistant.facts import facts_from_assembly

OUT = Path(__file__).resolve().parent.parent / "examples"

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name in samples.SAMPLES:
        facts = facts_from_assembly(name, samples.build(name))
        (OUT / f"{name}.json").write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
        print(name, "verified:", facts["verified"], "disassembly:", facts["disassembly"]["feasible"])
