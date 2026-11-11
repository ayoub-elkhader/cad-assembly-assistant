"""Assembly *facts*: the deterministic data the assistant answers from.

A facts file is a JSON object::

    {
      "id": "shaft_stack",
      "parts":    [{"id": "shaft", "type": "cylinder", "dims": [10, 10, 60], "center": [0, 0, 28]}, ...],
      "contacts": [["base", "shaft", "coaxial"], ["ring_1", "ring_2", "contact"], ...],
      "joints":   [{"name": "...", "type": "Revolute"}, ...],        # optional, annotated data only
      "plan":     {"shaft": [0, 0, 120], ...},                       # verified exploded view
      "disassembly": {"feasible": true, "order": ["ring_3", ...], "stuck": []},
      "verified": true                                               # plan accepted by the verifier
    }

:func:`facts_from_step` computes such a file from a STEP assembly with
``exploded_view_verifier`` (contact graph, shared cylinder axes, verified exploded view,
straight-line disassembly order). :class:`AssemblyIndex` loads facts files and derives
the graph quantities used by the tools. Nothing is computed by a language model.
"""
from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional


# ----------------------------------------------------------------------------- index
class AssemblyIndex:
    """In-memory, read-only index of assembly facts."""

    def __init__(self, facts: Iterable[dict] = ()):
        self.by_id: Dict[str, dict] = {}
        for f in facts:
            self.add(f)

    @classmethod
    def from_folder(cls, folder) -> "AssemblyIndex":
        files = sorted(Path(folder).glob("*.json"))
        return cls(json.loads(p.read_text(encoding="utf-8")) for p in files)

    def add(self, facts: dict) -> None:
        a = {
            "id": facts["id"],
            "parts": list(facts.get("parts", [])),
            "contacts": list(facts.get("contacts", [])),
            "joints": list(facts.get("joints", [])),
            "plan": dict(facts.get("plan", {})),
            "disassembly": dict(facts.get("disassembly") or {}),
            "verified": facts.get("verified"),
        }
        a["nb_parts"] = len(a["parts"])
        self._derive(a)
        self.by_id[a["id"]] = a

    @staticmethod
    def _derive(a: dict) -> None:
        ids = [p["id"] for p in a["parts"]]
        idset = set(ids)
        a["part_ids"] = ids
        adj, edges = defaultdict(set), []
        for c in a["contacts"]:
            if len(c) < 2 or c[0] not in idset or c[1] not in idset or c[0] == c[1]:
                continue
            rel = c[2] if len(c) >= 3 else "contact"
            adj[c[0]].add(c[1])
            adj[c[1]].add(c[0])
            edges.append((c[0], c[1], rel))
        a["adj"] = {k: sorted(v) for k, v in adj.items()}
        a["edges"] = edges
        a["degree"] = {p: len(adj.get(p, ())) for p in ids}
        a["components"] = _components(ids, adj)
        cadj = defaultdict(set)
        for i, j, rel in edges:
            if rel == "coaxial":
                cadj[i].add(j)
                cadj[j].add(i)
        a["coaxial_groups"] = [g for g in _components(ids, cadj) if len(g) >= 2]

    def get(self, aid: str) -> Optional[dict]:
        return self.by_id.get(aid)

    def ids(self) -> List[str]:
        return sorted(self.by_id)


def _components(nodes, adj):
    seen, comps = set(), []
    for n in nodes:
        if n in seen:
            continue
        stack, comp = [n], []
        while stack:
            x = stack.pop()
            if x in seen:
                continue
            seen.add(x)
            comp.append(x)
            stack.extend(adj.get(x, set()) - seen)
        comps.append(sorted(comp))
    return comps


# ----------------------------------------------------------------------------- from STEP
def _cylinder_axes(shapes):
    """(point, unit direction, area) of the cylindrical faces of a part."""
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.GeomAbs import GeomAbs_Cylinder
    from OCC.Core.GProp import GProp_GProps
    from OCC.Core.TopAbs import TopAbs_FACE
    from OCC.Core.TopExp import TopExp_Explorer
    from OCC.Core.TopoDS import topods
    out = []
    for s in shapes:
        ex = TopExp_Explorer(s, TopAbs_FACE)
        while ex.More():
            f = topods.Face(ex.Current())
            surf = BRepAdaptor_Surface(f)
            if surf.GetType() == GeomAbs_Cylinder:
                ax = surf.Cylinder().Axis()
                p, d = ax.Location(), ax.Direction()
                g = GProp_GProps()
                brepgprop.SurfaceProperties(f, g)
                out.append(((p.X(), p.Y(), p.Z()), (d.X(), d.Y(), d.Z()), g.Mass()))
            ex.Next()
    return out


def _total_area(shapes):
    from OCC.Core.BRepGProp import brepgprop
    from OCC.Core.GProp import GProp_GProps
    t = 0.0
    for s in shapes:
        g = GProp_GProps()
        brepgprop.SurfaceProperties(s, g)
        t += g.Mass()
    return t


def _same_axis(a, b, tol=0.05):
    (p1, d1, _), (p2, d2, _) = a, b
    if abs(abs(sum(x * y for x, y in zip(d1, d2))) - 1.0) > 1e-4:
        return False
    w = [p2[k] - p1[k] for k in range(3)]
    cross = [w[1] * d1[2] - w[2] * d1[1], w[2] * d1[0] - w[0] * d1[2], w[0] * d1[1] - w[1] * d1[0]]
    return math.sqrt(sum(c * c for c in cross)) <= tol


def classify(dims, cyl_area_ratio):
    """Coarse shape label from bounding-box dimensions and cylindrical surface share."""
    if cyl_area_ratio >= 0.4:
        return "cylinder"
    s = sorted(dims)
    if s[2] > 0 and s[0] < 0.25 * s[2]:
        return "plate"
    return "box"


def _exact_box(shapes):
    from OCC.Core.Bnd import Bnd_Box
    from OCC.Core.BRepBndLib import brepbndlib
    box = Bnd_Box()
    for s in shapes:
        brepbndlib.AddOptimal(s, box, False, False)
    return box.Get()


def _r(x):
    return round(x, 2) + 0.0   # + 0.0 turns -0.0 into 0.0


def facts_from_assembly(aid, assembly, factor=2.0, proposer=None) -> dict:
    """Facts of an assembly ``{part: [meshed solids]}`` (see exploded_view_verifier)."""
    from exploded_view_verifier import oracle as O
    from exploded_view_verifier.disassembly import sequential_disassembly
    from exploded_view_verifier.repair import explode

    parts, axes = [], {}
    for pid, shapes in assembly.items():
        xmin, ymin, zmin, xmax, ymax, zmax = _exact_box(shapes)
        dims = [_r(xmax - xmin), _r(ymax - ymin), _r(zmax - zmin)]
        axes[pid] = _cylinder_axes(shapes)
        total = _total_area(shapes) or 1.0
        ratio = sum(a[2] for a in axes[pid]) / total
        parts.append({"id": pid, "type": classify(dims, ratio), "dims": dims,
                      "center": [_r((xmin + xmax) / 2), _r((ymin + ymax) / 2), _r((zmin + zmax) / 2)]})
    # contacts = pairs within the verifier tolerance in the assembled state
    details: dict = {}
    O.verify_plan(assembly, {}, details=details)
    contacts = []
    for (a, b), verdict in sorted(details.items()):
        coax = any(_same_axis(x, y) for x in axes[a] for y in axes[b])
        rel = "coaxial" if coax else ("undetermined" if verdict == O.UNDET else "contact")
        contacts.append([a, b, rel])
    res = explode(assembly, factor=factor, proposer=proposer)
    feas, order, stuck = sequential_disassembly(assembly, res.plan) if res.accepted else (None, [], [])
    return {
        "id": aid, "parts": parts, "contacts": contacts, "joints": [],
        "plan": {k: [round(x, 3) for x in v] for k, v in res.plan.items()},
        "verified": res.accepted,
        "disassembly": {"feasible": feas, "order": order, "stuck": stuck},
    }


def facts_from_step(path, factor=2.0) -> dict:
    from exploded_view_verifier.geometry import load_step_assembly
    return facts_from_assembly(Path(path).stem, load_step_assembly(str(path)), factor)


def _joint_type(raw: str) -> str:
    """'RevoluteJointType' (Fusion) or 'REVOLUTE' / 'PIN_SLOT' (AutoMate) -> 'Revolute', 'PinSlot'."""
    raw = (raw or "Unknown").replace("JointType", "")
    if raw.isupper() or "_" in raw:
        raw = "".join(w.capitalize() for w in raw.lower().split("_"))
    return raw


def _add_names(facts, names):
    for p in facts["parts"]:
        if names.get(p["id"]) and names[p["id"]] != p["id"]:
            p["name"] = names[p["id"]]
    return facts


def facts_from_fusion(assembly_json, factor=2.0) -> dict:
    """Facts of a Fusion 360 Gallery assembly, with the joints annotated in assembly.json."""
    from exploded_view_verifier.datasets import load_fusion
    asm, names = load_fusion(str(assembly_json))
    facts = _add_names(facts_from_assembly(Path(assembly_json).parent.name, asm, factor), names)
    data = json.loads(Path(assembly_json).read_text(encoding="utf-8"))
    joints = data.get("joints") or {}
    for j in (joints.values() if isinstance(joints, dict) else joints):
        a, b = j.get("occurrence_one"), j.get("occurrence_two")
        if a in asm and b in asm:
            facts["joints"].append({"name": j.get("name", ""), "parts": [a, b],
                                    "type": _joint_type((j.get("joint_motion") or {}).get("joint_type"))})
    return facts


def facts_from_automate(assembly_json, step_dir, factor=2.0) -> dict:
    """Facts of an AutoMate assembly, with its mates as annotated joints."""
    from exploded_view_verifier.datasets import load_automate
    asm, names = load_automate(str(assembly_json), str(step_dir))
    facts = _add_names(facts_from_assembly(Path(assembly_json).stem, asm, factor), names)
    data = json.loads(Path(assembly_json).read_text(encoding="utf-8"))
    occ_ids = [o.get("id") for o in data.get("occurrences", [])]
    for m in data.get("mates", []):
        idx = m.get("occurrences") or []
        ids = [occ_ids[k] for k in idx if isinstance(k, int) and 0 <= k < len(occ_ids)]
        if len(ids) == 2 and all(i in asm for i in ids):
            facts["joints"].append({"name": m.get("name", ""), "parts": ids,
                                    "type": _joint_type(m.get("mateType"))})
    return facts
