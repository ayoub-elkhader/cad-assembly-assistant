"""Router, tools and evaluation on the bundled example facts (no CAD kernel, no network)."""
from pathlib import Path

import pytest

from cad_assistant import tools
from cad_assistant.assistant import Assistant, is_interpretive, main, rule_route
from cad_assistant.evaluate import run
from cad_assistant.facts import AssemblyIndex
from cad_assistant.llm import extract_json

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture(scope="module")
def idx():
    return AssemblyIndex.from_folder(EXAMPLES)


@pytest.fixture(scope="module")
def bot(idx):
    return Assistant(idx, use_llm=False)


def test_index_loads_examples(idx):
    assert idx.ids() == ["automate_d0582033", "caged_cube", "pin_in_plate", "shaft_stack"]
    a = idx.get("shaft_stack")
    assert a["nb_parts"] == 5
    assert a["coaxial_groups"] == [sorted(a["part_ids"])]


@pytest.mark.parametrize("q,tool", [
    ("How many parts are there?", "part_count"),
    ("Show the bill of materials", "bom"),
    ("Which parts share the same axis?", "coaxial_groups"),
    ("How can I take it apart?", "disassembly"),
    ("What is the assembly order?", "assembly_order"),
    ("Which parts touch each other?", "contact_graph"),
    ("Give me an overview", "summary"),
    ("Any revolute joints?", "joints"),
])
def test_rule_router(q, tool):
    assert rule_route(q, ["shaft", "ring_1"])["tool"] == tool


def test_router_picks_quoted_part():
    r = rule_route("which parts are in contact with ring_1?", ["ring_1", "ring_10"])
    assert r == {"tool": "neighbors", "args": {"part": "ring_1"}}


def test_answers_are_grounded(bot):
    r = bot.ask("shaft_stack", "How many parts does it have?")
    assert r["routing"] == "rules" and "5 parts" in r["answer"]
    r = bot.ask("shaft_stack", "In which order can I take it apart?")
    assert "FOUND" in r["answer"] and "ring_3" in r["answer"]
    r = bot.ask("caged_cube", "In which order can I take it apart?")
    assert "no straight-line disassembly" in r["answer"]
    r = bot.ask("caged_cube", "What is the assembly order?")
    assert r["evidence"]["data"]["order"] is None


def test_joints_are_not_invented(bot):
    r = bot.ask("pin_in_plate", "What are the joints?")
    assert "no annotated mechanical joint" in r["answer"]


def test_annotated_mates_are_reported(bot):
    r = bot.ask("automate_d0582033", "Which joints are there?")
    assert "14 annotated joint(s)" in r["answer"] and "cylindrical" in r["answer"]


def test_router_handles_automate_part_ids(bot, idx):
    pid = "MwxoMc+KWiB+9ipBD"
    r = bot.ask("automate_d0582033", f"What is the size of {pid}?")
    assert r["tool"] == "part_info" and r["evidence"]["data"]["id"] == pid


def test_interpretive_question_offline(bot):
    assert is_interpretive("What is it for?")
    r = bot.ask("pin_in_plate", "What is it for?")
    assert r["tool"] == "interpretation" and "no function is recorded" in r["answer"]


def test_unknown_assembly_and_part(idx):
    assert not tools.call(idx, "summary", aid="nope")["ok"]
    assert not tools.call(idx, "part_info", aid="shaft_stack", part="nope")["ok"]
    assert not tools.call(idx, "bogus", aid="shaft_stack")["ok"]
    assert not tools.call(idx, "neighbors", aid="shaft_stack")["ok"]   # missing argument


def test_offline_evaluation_is_complete(idx):
    r_ok, r_tot, f_ok, f_tot = run(idx)
    assert r_tot == 40 and r_ok == r_tot
    assert f_ok == f_tot


def test_extract_json():
    assert extract_json('```json\n{"tool": "bom", "args": {}}\n```') == {"tool": "bom", "args": {}}
    assert extract_json('Sure! {"tool": "summary"} done') == {"tool": "summary"}
    assert extract_json("nothing") is None


def test_cli(capsys):
    assert main(["--facts", str(EXAMPLES), "-a", "shaft_stack", "-q", "how many parts?", "--no-llm"]) == 0
    assert "5 parts" in capsys.readouterr().out


def test_llm_is_skipped_without_key(monkeypatch, idx):
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    assert Assistant(idx, use_llm=True).use_llm is False
