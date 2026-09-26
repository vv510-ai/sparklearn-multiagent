"""Small, attributed dictionary snapshot; no runtime network or model dependency."""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import json
import logging
from pathlib import Path
from urllib.parse import quote

CATALOG = Path(__file__).resolve().parents[1] / "data" / "english_dictionary_v1.json"
NOTICE = "以下是部分词典义项，请结合场景对照；不代表上方 AI 解释已核验。"


@lru_cache(maxsize=1)
def _catalog() -> dict:
    try:
        data = json.loads(CATALOG.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("entries"), dict):
            raise ValueError("invalid dictionary snapshot")
        return data
    except (OSError, ValueError):
        logging.getLogger(__name__).warning("english_dictionary snapshot_unavailable")
        return {}


def lookup(word: str) -> dict:
    headword = " ".join(word.split()).casefold()
    catalog = _catalog()
    entry = catalog.get("entries", {}).get(headword)
    if not entry:
        return {"status": "not_included", "headword": word,
                "search_url": "https://en.wiktionary.org/w/index.php?title=Special:Search&search=" + quote(word, safe="")}
    return deepcopy({**{k: v for k, v in catalog.items() if k != "entries"}, **entry,
                     "status": "included", "notice": NOTICE})


def with_sources(scene: dict) -> dict:
    """New scenes and legacy views use program-owned sources, never model URLs."""
    result = deepcopy(scene)
    for word in result.get("vocabulary", []):
        word["dictionary"] = lookup(word["word"])
    return result
