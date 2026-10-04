"""Syllabus-derived families and transparent, learner-selected vocabulary order."""
from __future__ import annotations

import hashlib
from collections import defaultdict
from functools import lru_cache

ORDERS = {"priority": "重点词优先", "family": "词族一起背", "alphabetical": "字母顺序", "random": "打乱顺序"}


def priority(entry):
    return (entry["level"] != "cet6", entry.get("frequency") or 999999, entry["word"].casefold())


@lru_cache(maxsize=1)
def families():
    from .cet6_vocabulary import entries
    catalog = entries()
    grouped = defaultdict(list)
    primary = {}
    for key, entry in catalog.items():
        # A spelling can occur in unrelated rows (tire: fatigue / tyre).
        # Keep one stable source row per study entry; never transitively join
        # different rows through a homograph. All other locators remain intact.
        primary[key] = min(entry["locators"], key=lambda loc: (loc["role"] != "headword", loc["row_id"]))
        grouped[primary[key]["row_id"]].append(key)
    result = {}
    for row_id, members in grouped.items():
        members.sort(key=lambda key: (primary[key]["role"] != "headword", catalog[key].get("frequency") or 999999, catalog[key]["word"].casefold()))
        first = catalog[members[0]]
        group = {"id": row_id, "label": first["word"], "entry_ids": members,
                 "words": [catalog[key]["word"] for key in members], "total": len(members),
                 "priority": min(priority(catalog[key]) for key in members)}
        for key in members:
            result[key] = group
    return result


def ordered(values, order="priority", seed=""):
    if order == "alphabetical":
        return sorted(values, key=lambda e: (e["word"].casefold(), e["id"]))
    if order == "random":
        return sorted(values, key=lambda e: hashlib.sha256(f"{seed}:{e['id']}".encode()).digest())
    if order == "family":
        groups = families()
        return sorted(values, key=lambda e: (groups[e["id"]]["priority"], groups[e["id"]]["id"],
            groups[e["id"]]["entry_ids"].index(e["id"])))
    return sorted(values, key=priority)


def family(entry_id, learnt=()):
    value = families()[entry_id]
    return {key: value[key] for key in ("id", "label", "entry_ids", "words", "total")} | {
        "learned": len(set(value["entry_ids"]) & set(learnt))}


def coverage(catalog, learnt):
    all_ids = set(catalog)
    learned = all_ids & set(learnt)
    priority_ids = {key for key, entry in catalog.items() if entry["level"] == "cet6"}
    return {"total": len(all_ids), "learned": len(learned), "remaining": len(all_ids - learned),
        "priority_total": len(priority_ids), "priority_learned": len(learned & priority_ids),
        "foundation_total": len(all_ids - priority_ids), "foundation_learned": len(learned - priority_ids)}
