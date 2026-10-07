"""Build a small, reproducible inflection index from the already pinned ECDICT CSV.

The study vocabulary/IDs remain unchanged. No network, models or suffix guessing.
"""
import argparse
import csv
import hashlib
import json
import re
from pathlib import Path

from build_cet6_vocabulary import COMMIT, DICT_SHA, ROOT

CODES = set("pdi3rts")


def exchange(text):
    return dict(part.split(":", 1) for part in text.split("/") if ":" in part)


def build(dictionary):
    if hashlib.sha256(dictionary.read_bytes()).hexdigest() != DICT_SHA:
        raise ValueError("Unreviewed ECDICT snapshot")
    data = ROOT / "backend/app/data"
    entries = json.loads((data / "cet6_vocabulary_v1.json").read_text(encoding="utf-8"))["entries"]
    fixes = json.loads((data / "cet6_vocabulary_corrections_v1.json").read_text(encoding="utf-8"))
    words = {fixes["spellings"].get(e["word"], e["word"]): e["id"] for e in entries if e["word"] not in fixes["aliases"]}
    records = {}
    with dictionary.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            word = row["word"].casefold()
            if word not in records or row["word"] == word:
                records[word] = row
    forms = {}

    def add(surface, lemma, codes):
        surface = surface.strip().casefold()
        if lemma not in words or surface == lemma or not re.fullmatch(r"[a-z]+(?:[' -][a-z]+)*", surface):
            return
        item = forms.setdefault(surface, {}).setdefault(words[lemma], set())
        item.update(c for c in codes if c in CODES)

    for word in words:
        for code, value in exchange(records.get(word, {}).get("exchange", "")).items():
            if code in CODES:
                for surface in value.split(","):
                    add(surface, word, code)
    forward_pairs = {(surface, entry_id) for surface, matches in forms.items() for entry_id in matches}
    # Reverse lemma records fill forms not enumerated on the headword itself.
    for surface, row in records.items():
        ex = exchange(row.get("exchange", ""))
        for lemma in ex.get("0", "").split(","):
            if ex.get("1") and (surface, words.get(lemma)) not in forward_pairs:
                add(surface, lemma, ex["1"])
    # Retain independent homographs outside the syllabus, e.g. saw (a tool).
    # An independent verb paradigm is evidence of a second headword; never
    # silently treat that word as only another verb's past tense.
    homographs = {}
    for surface in forms.keys() - words.keys():
        row = records.get(surface, {})
        ex = exchange(row.get("exchange", ""))
        meaning = row.get("translation", "").replace("\\n", "\n")
        if any(ex.get(code) and ex[code] != surface for code in ("p", "d", "3")) and re.search(r"(?m)^v(?:t|i)?\.", meaning):
            homographs[surface] = row["translation"].replace("\\n", "\n").strip()
    return {
        "version": "ecdict-bc015ed-forms-v1",
        "source_url": f"https://github.com/skywind3000/ECDICT/tree/{COMMIT}",
        "license_url": f"https://github.com/skywind3000/ECDICT/blob/{COMMIT}/LICENSE",
        "dictionary_sha256": DICT_SHA,
        "scope": "Fixed ECDICT inflections pointing to existing study entries; not an exhaustive English dictionary.",
        "forms": {form: [{"entry_id": key, "codes": sorted(codes)} for key, codes in sorted(matches.items()) if codes]
                  for form, matches in sorted(forms.items())},
        "homographs": dict(sorted(homographs.items())),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dictionary", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "backend/app/data/cet6_word_forms_v1.json")
    args = parser.parse_args()
    result = build(args.dictionary)
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(json.dumps({"forms": len(result["forms"]), "homographs": len(result["homographs"]), "bytes": args.output.stat().st_size}))
