"""Join audited visible syllabus rows to a pinned ECDICT snapshot (offline).

First run extract_cet6_official.py with the pinned official PDF. Then run:
python scripts/build_cet6_vocabulary.py --rows tmp/cet6-sources/audit-official-rows.json --dictionary tmp/cet6-sources/ecdict.csv
The two original counts are retained; extracted counts are never padded.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DICT_SHA = "1a6947e04785db63613a92e14903cdae7954f7e84860b10e68e5c7cbb3f9c3cf"
COMMIT = "bc015ed2e24a7abef49fc6dbbb7fe32c1dadaf8b"
SOURCE = "https://cet.neea.edu.cn/res/Home/1704/55b02330ac17274664f06d9d3db8249d.pdf"
DICTIONARY = f"https://github.com/skywind3000/ECDICT/tree/{COMMIT}"


def variants(form):
    """Expand only notations actually printed in this source, not inflections."""
    result = []
    base = ""
    for part in form.split("/"):
        if part.startswith("-") and base:
            suffix = part[1:]
            part = base[:-len(suffix)] + suffix
        if not base:
            base = part
        pending = [part]
        while any("(" in v and ")" in v for v in pending):
            expanded = []
            for v in pending:
                match = re.search(r"\(([^()]*)\)", v)
                if match:
                    expanded += [v[:match.start()] + v[match.end():], v[:match.start()] + match[1] + v[match.end():]]
                else:
                    expanded.append(v)
            pending = expanded
        result += [" ".join(v.split()).strip() for v in pending]
    return list(dict.fromkeys(v for v in result if v))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=Path, required=True)
    parser.add_argument("--dictionary", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "backend/app/data/cet6_vocabulary_v1.json")
    args = parser.parse_args()
    assert hashlib.sha256(args.dictionary.read_bytes()).hexdigest() == DICT_SHA, "Unreviewed ECDICT snapshot"
    rows = json.loads(args.rows.read_text(encoding="utf-8"))
    assert len(rows) == 5377 and len({r["source_id"] for r in rows}) == 5377
    assert sum(len(r["derivatives"]) for r in rows) == 2519
    words = {}

    def add(form, row, role, parent="", homograph=None):
        spellings = variants(form)
        for word in spellings:
            canonical = word.casefold()
            value = words.setdefault(canonical, {"id": "cet-" + hashlib.sha256(canonical.encode()).hexdigest()[:24], "word": word,
                "level": "foundation", "role": role, "variants": [], "derivatives": [], "parents": [], "source_pages": [], "locators": []})
            if row["starred"]:
                value["level"] = "cet6"
            if role == "headword":
                value["role"] = role
            value["variants"] = list(dict.fromkeys(value["variants"] + [s for s in spellings if s != word]))
            value["source_pages"] = sorted(set(value["source_pages"] + [row["source_pdf_page"]]))
            value["locators"].append({"row_id": row["source_id"], "role": role, "form": form, "homograph": homograph})
            if parent:
                value["parents"] = list(dict.fromkeys(value["parents"] + [parent]))
            elif role == "headword":
                value["derivatives"] = list(dict.fromkeys(value["derivatives"] + [d["normalized_form"] for d in row["derivatives"]]))

    for row in rows:
        add(row["normalized_head"], row, "headword", homograph=row["homograph_number"])
        for derivative in row["derivatives"]:
            add(derivative["normalized_form"], row, "derivative", row["normalized_head"], derivative["homograph_number"])
    dictionary = {}
    with args.dictionary.open(encoding="utf-8-sig", newline="") as source:
        for row in csv.DictReader(source):
            word = row["word"].casefold()
            if word in words and (word not in dictionary or row["word"] == words[word]["word"]):
                dictionary[word] = row
    missing = []
    for key, item in words.items():
        record = dictionary.get(key, {})
        item["phonetic"] = record.get("phonetic", "")
        item["frequency"] = int(record.get("frq") or 0)
        definitions = [s.strip() for s in record.get("translation", "").replace("\\n", "\n").splitlines() if s.strip()]
        item["senses"] = [{"id": "sense-" + hashlib.sha256((key + "\0" + definition).encode()).hexdigest()[:24], "definition": definition} for definition in dict.fromkeys(definitions)]
        item["source_url"] = SOURCE + "#page=" + str(item["source_pages"][0])
        item["dictionary_url"] = DICTIONARY
        if not item["senses"]:
            missing.append(item["word"])
    output = {"version": "cet2016-visible-ecdict-bc015ed-v1", "manifest": {
        "title": "2016 大纲可见词表与派生词", "entry_count": len(words), "headword_rows": 5377,
        "declared_headword_rows": 5418, "derivative_cells": 2519, "declared_derivative_cells": 2551,
        "starred_rows": 1263, "source_pdf_sha256": "9166d3c03b7bc43abd9d9df91bd2ef8085b4419286f1e5ca100dea68f3cfd1f1",
        "dictionary_sha256": DICT_SHA, "dictionary_commit": COMMIT, "missing_definitions": missing,
        "source_url": SOURCE, "dictionary_url": DICTIONARY, "license_url": f"https://github.com/skywind3000/ECDICT/blob/{COMMIT}/LICENSE",
        "scope": "覆盖官方 2016 版 PDF 词表的全部可见行：5,377 行词目、2,519 格派生词；拆开原表异体拼写并按词形去重，保留同形词的来源编号。",
        "notes": ["原 PDF 自报 5,418 个词目、2,551 个派生词，与按版面核对数量存在差异，原因待核验；没有虚构词条补齐数字。",
                  "六级标记来自原词表星号；基础词同样保留。派生词沿用所属词目的级别，不代表独立考频。",
                  "中文释义与读音来自固定版本 ECDICT 社区词典，不是官方大纲原文，也未经逐词人工审校。词库中的每一行释义用于学习卡，未冒充官方同形词编号的对应义项。",
                  f"当前 {len(missing)} 个词形尚无匹配释义，保留原页入口，不进入自动词卡队列。基础与六级星号是范围标签，不等于官方题目中已出现或个人已经掌握。"]},
        "entries": sorted(words.values(), key=lambda e: (e["word"].casefold(), e["id"]))}
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"entries": len(words), "missing_definitions": len(missing), "missing_words": missing, "bytes": args.output.stat().st_size}, ensure_ascii=False))


if __name__ == "__main__":
    main()
