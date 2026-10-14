"""Exact and source-backed inflection lookup, separate from catalogue substring search."""
import json
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from . import cet6_learning as learning
from . import cet6_vocabulary as vocabulary
from . import reading_dictionary

DATA = Path(__file__).parents[1] / "data"
LABELS = {"p": "过去式", "d": "过去分词", "i": "-ing 形式", "3": "第三人称单数",
          "s": "复数", "r": "比较级", "t": "最高级", "present": "现在时形式"}
TOKEN = re.compile(r"[a-z]+(?:['-][a-z]+)*(?:(?<=s)')?")


def normalize(text):
    return text.strip().casefold().replace("’", "'").replace("‐", "-").replace("‑", "-")


def contains_form(context, surface):
    return normalize(surface) in TOKEN.findall(normalize(context))


def senses_for_form(entry, codes):
    patterns = []
    if any(c in codes for c in ("p", "d", "i", "3", "present")):
        patterns.append(r"^v[ti]?\.")
    if "s" in codes:
        patterns.append(r"^n\.")
    if any(c in codes for c in ("r", "t")):
        patterns.append(r"^(a|adj|adv)\.")
    compatible = [s for s in entry["senses"] if any(re.match(p, s["definition"], re.I) for p in patterns)]
    return compatible or entry["senses"]


@lru_cache(maxsize=1)
def index():
    data = json.loads((DATA / "cet6_word_forms_v1.json").read_text(encoding="utf-8"))
    exact, by_word = {}, {}
    for entry in vocabulary.entries().values():
        by_word[entry["word"]] = entry["id"]
        for text in [entry["word"], *entry.get("variants", [])]:
            exact.setdefault(normalize(text), []).append(entry["id"])
    for extra in json.loads((DATA / "cet6_word_forms_supplement.json").read_text(encoding="utf-8"))["entries"]:
        for surface, codes in extra["forms"].items():
            data["forms"].setdefault(surface, []).append({"entry_id": by_word[extra["word"]], "codes": codes, "source_url": extra["source_url"]})
    return data, exact


def resolve(query, include_reading=True):
    """Pure lookup; no model, database or guessed suffixes. Keeps ambiguous lemmas."""
    data, exact = index()
    normalized = normalize(query)
    key, possessive = normalized, False
    if key not in exact and key not in data["forms"] and not (include_reading and reading_dictionary.matches(key)):
        # Don't interpret he's/it's/that's as possessives of pronouns.
        stem = key[:-2] if key.endswith("'s") else key[:-1] if key.endswith("s'") else ""
        if stem and stem not in {"he", "she", "it", "there", "that", "what", "who", "how", "where", "when", "why", "let"}:
            if stem in exact or stem in data["forms"] or (include_reading and reading_dictionary.matches(stem)):
                key, possessive = stem, True
    matches = {}
    for entry_id in exact.get(key, []):
        entry = vocabulary.entries()[entry_id]
        matches[entry_id] = {"entry_id": entry_id, "word": entry["word"], "codes": [],
                             "match_kind": "exact" if normalize(entry["word"]) == key else "spelling",
                             "source_url": entry["dictionary_url"]}
    for form in data["forms"].get(key, []):
        entry_id = form["entry_id"]
        entry = vocabulary.entries().get(entry_id)
        if not entry:
            continue
        match = matches.setdefault(entry_id, {"entry_id": entry_id, "word": entry["word"], "codes": [],
                                               "match_kind": "inflection", "source_url": form.get("source_url", data["source_url"])})
        match["codes"] = sorted(set(match["codes"] + form["codes"]))
    if include_reading:
        for word, codes in reading_dictionary.matches(key):
            # Reuse existing study IDs (including aliases), never duplicate cards.
            ids = exact.get(word, []) or [reading_dictionary.entry_id(word)]
            for entry_id in ids:
                if entry_id in matches:
                    continue  # The reviewed study index has priority over noisy reverse labels.
                entry = vocabulary.entry(entry_id)
                matches[entry_id] = {"entry_id": entry_id, "word": entry["word"], "codes": codes,
                    "match_kind": "inflection" if word != key else "spelling" if entry["word"] != key and query == key else "exact",
                    "source_url": entry["dictionary_url"]}
    values = list(matches.values())
    for match in values:
        entry = vocabulary.entry(match["entry_id"])
        senses = senses_for_form(entry, match["codes"])
        match["meaning"] = "；".join(s["definition"] for s in senses[:2])
        match["suggested_sense_id"] = senses[0]["id"] if match["codes"] and senses else None
        match["forms"] = [LABELS[c] for c in match["codes"] if c in LABELS]
        if possessive:
            match["forms"].append("所有格")
        match["collectible"] = bool(entry["senses"])
        match["in_study_list"] = entry["level"] != "reading"
    # A homograph outside the study list is displayed but cannot create a fake
    # syllabus entry/audio/learning record (e.g. saw, the independent verb).
    if not include_reading and key in data["homographs"]:
        values.append({"entry_id": None, "word": key, "codes": [], "forms": ["独立词义"],
                       "meaning": data["homographs"][key], "match_kind": "dictionary",
                       "source_url": data["source_url"], "collectible": False})
    values.sort(key=lambda m: (m["match_kind"] != "exact", m["match_kind"] == "dictionary", m["word"]))
    return values


def lookup(user, notebook, query, context=""):
    learning.check(user, notebook)
    matches = resolve(query)
    # British/American spelling aliases can point to two existing learning IDs.
    # Prefer the exact spelling; never merge or migrate existing records.
    canonical = [m for m in matches if m["entry_id"] and m["match_kind"] != "spelling"]
    auto = canonical[0]["entry_id"] if len(canonical) == 1 and canonical[0]["collectible"] else None
    if not canonical and len(matches) == 1 and matches[0]["collectible"]:
        auto = matches[0]["entry_id"]
    if any(m["match_kind"] == "dictionary" for m in matches):
        auto = None
    hint = ""
    if auto:
        selected = next(m for m in matches if m["entry_id"] == auto)
        occurrence = next((m for m in TOKEN.finditer(normalize(context)) if m.group() == normalize(query)), None)
        before = normalize(context)[:occurrence.start()] if occurrence else ""
        if "d" in selected["codes"] and re.search(r"\b(?:be|am|is|are|was|were|been|being)\s+(?:not\s+)?$", before):
            hint = "这里位于 be 动词之后，可按过去分词理解；be + 过去分词常用于被动语态，也可能描述状态。"
            transitive = next((s for s in vocabulary.entry(auto)["senses"] if re.match(r"^vt\.", s["definition"], re.I)), None)
            if transitive:
                selected["suggested_sense_id"] = transitive["id"]
        elif "d" in selected["codes"] and re.search(r"\b(?:have|has|had)\s+(?:not\s+)?$", before):
            hint = "这里位于 have / has / had 之后，过去分词可构成完成时。"
    return {"query": query.strip(), "normalized": normalize(query), "matches": matches,
            "auto_entry_id": auto, "status": "matched" if auto else "ambiguous" if matches else "not_found",
            "usage_hint": hint, "dictionary_url": "https://en.wiktionary.org/w/index.php?title=Special:Search&search=" + quote(query.strip(), safe=""),
            "note": "词形依据固定版本词典；具体词性与义项需结合原句。"}
