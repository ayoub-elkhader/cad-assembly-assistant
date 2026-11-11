"""Facts computed from geometry (needs pythonocc-core and exploded-view-verifier)."""
import json
from pathlib import Path

import pytest

pytest.importorskip("OCC")
pytest.importorskip("exploded_view_verifier")

from exploded_view_verifier import samples  # noqa: E402

from cad_assistant.facts import facts_from_assembly, facts_from_step  # noqa: E402

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.mark.parametrize("name", sorted(samples.SAMPLES))
def test_examples_are_up_to_date(name):
    facts = facts_from_assembly(name, samples.build(name))
    assert facts == json.loads((EXAMPLES / f"{name}.json").read_text(encoding="utf-8"))


def test_facts_from_step_file(tmp_path):
    from exploded_view_verifier.cli import main
    main(["--write-samples", str(tmp_path)])
    f = facts_from_step(tmp_path / "pin_in_plate.step")
    assert f["id"] == "pin_in_plate" and len(f["parts"]) == 2
    assert {p["type"] for p in f["parts"]} == {"box", "cylinder"}
    assert f["contacts"] == [["part_01", "part_02", "coaxial"]]
    assert f["verified"] is True and f["disassembly"]["feasible"] is True
