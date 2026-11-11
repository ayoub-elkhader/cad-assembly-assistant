"""Deterministic tools of the assistant.

Each tool reads the facts of one assembly and returns
``{"ok": bool, "tool": str, "data": {...}, "text": "..."}``. The assistant never answers
outside these facts: the geometry decides, the language model (if any) only rephrases.
"""
from __future__ import annotations

JOINT_LABEL = {
    "Revolute": "revolute (rotation)", "Slider": "slider (translation)",
    "Cylindrical": "cylindrical", "Planar": "planar", "Ball": "ball",
    "PinSlot": "pin-slot", "Rigid": "rigid (fixed)", "Fastened": "fastened (fixed)",
    "Parallel": "parallel",
}


def _need(idx, aid):
    a = idx.get(aid)
    if a is None:
        return None, {"ok": False, "tool": None, "error": f"Assembly '{aid}' not found."}
    return a, None


def _types(a):
    t = {}
    for p in a["parts"]:
        t[p.get("type", "?")] = t.get(p.get("type", "?"), 0) + 1
    return t


def _fmt_types(t):
    return ", ".join(f"{v} {k}" for k, v in t.items())


def _dims(d):
    return "x".join(f"{x:g}" for x in d) + " mm" if d else "n/a"


def _yes_no(v):
    return {True: "yes", False: "no"}.get(v, "unknown")


def list_assemblies(idx):
    ids = idx.ids()
    return {"ok": True, "tool": "list_assemblies", "data": {"count": len(ids), "ids": ids},
            "text": f"{len(ids)} assemblies indexed: " + ", ".join(ids)}


def summary(idx, aid):
    a, err = _need(idx, aid)
    if err:
        return err
    d = a["disassembly"]
    data = {"id": aid, "nb_parts": a["nb_parts"], "part_types": _types(a),
            "n_contacts": len(a["edges"]), "n_joints": len(a["joints"]),
            "n_components": len(a["components"]), "n_coaxial_groups": len(a["coaxial_groups"]),
            "verified_exploded_view": a["verified"], "disassembly_feasible": d.get("feasible")}
    txt = (f"Assembly {aid}: {a['nb_parts']} parts ({_fmt_types(data['part_types'])}), "
           f"{len(a['edges'])} contacts, {len(a['joints'])} annotated joints, "
           f"{len(a['components'])} connected group(s). "
           f"Verified exploded view: {_yes_no(a['verified'])}. "
           f"Straight-line disassembly found: {_yes_no(d.get('feasible'))}.")
    return {"ok": True, "tool": "summary", "data": data, "text": txt}


def part_count(idx, aid):
    a, err = _need(idx, aid)
    if err:
        return err
    return {"ok": True, "tool": "part_count", "data": {"nb_parts": a["nb_parts"]},
            "text": f"Assembly {aid} has {a['nb_parts']} parts."}


def bom(idx, aid):
    a, err = _need(idx, aid)
    if err:
        return err
    rows = [{"id": p["id"], "name": p.get("name"), "type": p.get("type"), "dims_mm": p.get("dims"),
             "n_contacts": a["degree"].get(p["id"], 0)} for p in a["parts"]]
    lines = [f"  - {r['id']}" + (f" ({r['name']})" if r["name"] else "")
             + f": {r['type']}, {_dims(r['dims_mm'])}, {r['n_contacts']} contact(s)" for r in rows]
    return {"ok": True, "tool": "bom", "data": {"parts": rows},
            "text": f"Bill of materials of {aid} ({len(rows)} parts):\n" + "\n".join(lines)}


def part_info(idx, aid, part):
    a, err = _need(idx, aid)
    if err:
        return err
    p = next((q for q in a["parts"] if q["id"] == part), None)
    if p is None:
        return {"ok": False, "tool": "part_info",
                "error": f"Part '{part}' is not in {aid}. Parts: {', '.join(a['part_ids'])}."}
    nb = a["adj"].get(part, [])
    txt = (f"Part {part} of {aid}: {p.get('type')}, {_dims(p.get('dims'))}, "
           f"in contact with {len(nb)} part(s)" + (f" ({', '.join(nb)})" if nb else "") + ".")
    return {"ok": True, "tool": "part_info",
            "data": {"id": part, "type": p.get("type"), "dims_mm": p.get("dims"),
                     "center": p.get("center"), "neighbors": nb}, "text": txt}


def contact_graph(idx, aid):
    a, err = _need(idx, aid)
    if err:
        return err
    edges = [{"a": i, "b": j, "relation": r} for i, j, r in a["edges"]]
    lines = [f"  - {e['a']} <-> {e['b']} ({e['relation']})" for e in edges]
    return {"ok": True, "tool": "contact_graph", "data": {"edges": edges, "adjacency": a["adj"]},
            "text": f"Contact graph of {aid}: {len(edges)} contact(s).\n"
                    + ("\n".join(lines) if lines else "  (no contact)")}


def neighbors(idx, aid, part):
    a, err = _need(idx, aid)
    if err:
        return err
    if part not in a["part_ids"]:
        return {"ok": False, "tool": "neighbors", "error": f"Part '{part}' is not in {aid}."}
    nb = a["adj"].get(part, [])
    return {"ok": True, "tool": "neighbors", "data": {"part": part, "neighbors": nb},
            "text": (f"Part {part} touches {len(nb)} part(s): {', '.join(nb)}." if nb
                     else f"Part {part} has no recorded contact.")}


def coaxial_groups(idx, aid):
    a, err = _need(idx, aid)
    if err:
        return err
    g = a["coaxial_groups"]
    txt = (f"Assembly {aid}: {len(g)} coaxial group(s) (parts in contact sharing a cylinder axis):\n"
           + "\n".join("  - {" + ", ".join(x) + "}" for x in g)) if g else \
        f"Assembly {aid}: no coaxial group of two or more parts."
    return {"ok": True, "tool": "coaxial_groups", "data": {"groups": g}, "text": txt}


def joints(idx, aid):
    a, err = _need(idx, aid)
    if err:
        return err
    js = a["joints"]
    if not js:
        return {"ok": True, "tool": "joints", "data": {"joints": []},
                "text": f"Assembly {aid}: no annotated mechanical joint in the data "
                        "(joints are not inferred from geometry)."}
    lines = [f"  - {j.get('name') or '(unnamed)'}: {JOINT_LABEL.get(j['type'], j['type'])}"
             + (f" between {j['parts'][0]} and {j['parts'][1]}" if len(j.get("parts") or []) == 2 else "")
             for j in js]
    return {"ok": True, "tool": "joints", "data": {"joints": js},
            "text": f"Assembly {aid}: {len(js)} annotated joint(s):\n" + "\n".join(lines)}


def disassembly(idx, aid):
    a, err = _need(idx, aid)
    if err:
        return err
    d = a["disassembly"]
    feas = d.get("feasible")
    if feas:
        txt = (f"Assembly {aid}: straight-line disassembly FOUND. Removal order: "
               f"{' -> '.join(d.get('order', []))}.")
    elif feas is False:
        txt = (f"Assembly {aid}: no straight-line disassembly found along the plan directions"
               + (f"; parts removed first: {' -> '.join(d['order'])}" if d.get("order") else "")
               + (f"; stuck: {', '.join(d.get('stuck', []))}" if d.get("stuck") else "") + ".")
    else:
        txt = f"Assembly {aid}: disassembly not checked (no verified exploded view)."
    return {"ok": True, "tool": "disassembly", "data": d, "text": txt}


def assembly_order(idx, aid):
    a, err = _need(idx, aid)
    if err:
        return err
    d = a["disassembly"]
    if not d.get("feasible"):
        return {"ok": True, "tool": "assembly_order", "data": {"order": None},
                "text": f"Assembly {aid}: no assembly order, because no disassembly order was found."}
    order = list(reversed(d["order"]))
    return {"ok": True, "tool": "assembly_order", "data": {"order": order},
            "text": f"Assembly {aid}: assembly order (reverse of the disassembly order): "
                    f"{' -> '.join(order)}."}


def evidence_bundle(idx, aid):
    """All structural facts, used for cautious interpretation questions."""
    a, err = _need(idx, aid)
    if err:
        return err
    rels = {}
    for _, _, r in a["edges"]:
        rels[r] = rels.get(r, 0) + 1
    maxdim = max((float(x) for p in a["parts"] for x in (p.get("dims") or [])), default=0.0)
    data = {"id": aid, "nb_parts": a["nb_parts"], "part_types": _types(a), "contact_relations": rels,
            "coaxial_groups": a["coaxial_groups"], "max_dim_mm": round(maxdim, 1),
            "disassembly_feasible": a["disassembly"].get("feasible")}
    txt = (f"Assembly {aid} (geometry only, anonymous parts):\n"
           f"- {a['nb_parts']} parts: {_fmt_types(data['part_types'])}.\n"
           f"- Largest dimension: about {data['max_dim_mm']} mm.\n"
           f"- Contacts ({len(a['edges'])}): " + (", ".join(f"{v} {k}" for k, v in rels.items()) or "none") + ".\n"
           f"- Coaxial groups: {len(a['coaxial_groups'])}.\n"
           f"- Straight-line disassembly found: {_yes_no(data['disassembly_feasible'])}.\n"
           "- Parts: " + "; ".join(f"{p['id']} ({p.get('type')}, {_dims(p.get('dims'))})" for p in a["parts"]) + ".")
    return {"ok": True, "tool": "evidence_bundle", "data": data, "text": txt}


# name -> (function, description, parameters)
TOOLS = {
    "list_assemblies": (list_assemblies, "List the indexed assemblies.", []),
    "summary": (summary, "Overview of an assembly (parts, contacts, verified view, disassembly).", ["aid"]),
    "part_count": (part_count, "Number of parts.", ["aid"]),
    "bom": (bom, "Bill of materials: parts with type and size.", ["aid"]),
    "part_info": (part_info, "Details of one part (type, size, neighbours).", ["aid", "part"]),
    "contact_graph": (contact_graph, "Which parts touch which.", ["aid"]),
    "neighbors": (neighbors, "Parts in contact with a given part.", ["aid", "part"]),
    "coaxial_groups": (coaxial_groups, "Groups of parts sharing an axis.", ["aid"]),
    "joints": (joints, "Annotated mechanical joints.", ["aid"]),
    "disassembly": (disassembly, "Disassembly feasibility and removal order.", ["aid"]),
    "assembly_order": (assembly_order, "Assembly order (reverse of disassembly).", ["aid"]),
    "evidence_bundle": (evidence_bundle, "All structural facts (for interpretation).", ["aid"]),
}


def call(idx, name, **kwargs):
    if name not in TOOLS:
        return {"ok": False, "tool": name, "error": f"Unknown tool: {name}."}
    fn, _, params = TOOLS[name]
    args = {k: kwargs[k] for k in params if k in kwargs}
    missing = [p for p in params if p not in args]
    if missing:
        return {"ok": False, "tool": name, "error": f"Missing argument(s): {missing}."}
    try:
        return fn(idx, **args)
    except Exception as e:   # a tool must never crash the assistant
        return {"ok": False, "tool": name, "error": f"Tool error: {e}"}
