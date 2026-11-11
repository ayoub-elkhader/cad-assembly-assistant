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


def test_facts_from_automate_and_fusion_formats(tmp_path):
    from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
    from exploded_view_verifier.geometry import write_step
    from cad_assistant.facts import facts_from_automate, facts_from_fusion
    write_step([BRepPrimAPI_MakeBox(10, 10, 10).Shape()], tmp_path / "p.step")
    eye = lambda tx: [1, 0, 0, tx, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]  # noqa: E731
    (tmp_path / "a.json").write_text(json.dumps({
        "parts": [{"id": "p", "has_step": True, "name": "cube"}],
        "occurrences": [{"id": "o1", "part": 0, "transform": eye(0)},
                        {"id": "o2", "part": 0, "transform": eye(0.01)}],
        "mates": [{"name": "Revolute 1", "mateType": "REVOLUTE", "occurrences": [0, 1]},
                  {"name": "Pin 1", "mateType": "PIN_SLOT", "occurrences": [0, 1]}]}))
    f = facts_from_automate(tmp_path / "a.json", tmp_path)
    assert [j["type"] for j in f["joints"]] == ["Revolute", "PinSlot"]
    assert {p["name"] for p in f["parts"]} == {"cube"}
    assert f["contacts"] == [["o1", "o2", "contact"]]       # faces touching at x = 10 mm

    fus = tmp_path / "fus"
    fus.mkdir()
    write_step([BRepPrimAPI_MakeBox(10, 10, 10).Shape()], fus / "b.step")
    frame = lambda x: {"origin": {"x": x, "y": 0, "z": 0}, "x_axis": {"x": 1, "y": 0, "z": 0},  # noqa: E731
                       "y_axis": {"x": 0, "y": 1, "z": 0}, "z_axis": {"x": 0, "y": 0, "z": 1}}
    (fus / "assembly.json").write_text(json.dumps({
        "bodies": {"b": {"step": "b.step"}},
        "occurrences": {"o1": {"name": "A", "bodies": {"b": {}}, "transform": frame(0)},
                        "o2": {"name": "B", "bodies": {"b": {}}, "transform": frame(5.0)}},
        "tree": {"root": {"o1": {}, "o2": {}}},
        "joints": {"j": {"name": "Slider1", "occurrence_one": "o1", "occurrence_two": "o2",
                         "joint_motion": {"joint_type": "SliderJointType"}}}}))
    f = facts_from_fusion(fus / "assembly.json")
    assert f["id"] == "fus" and f["joints"] == [{"name": "Slider1", "parts": ["o1", "o2"], "type": "Slider"}]
    assert f["contacts"] == []                                # 50 mm apart
