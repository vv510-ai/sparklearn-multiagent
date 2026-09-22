"""Bounded public Bilibili search. Provider failures never mean zero matches."""
from __future__ import annotations

import copy
import datetime as dt
import html
import re
import time
from threading import Lock

import requests

from .video_metadata import _cover

_CACHE: dict[str, tuple[float, dict]] = {}
_LOCK = Lock()


def _text(value: object, limit: int = 240) -> str:
    return html.unescape(re.sub(r"<[^>]*>", "", str(value or ""))).strip()[:limit]


def _duration(value: object) -> int | None:
    parts = str(value or "").split(":")
    if not 2 <= len(parts) <= 3 or not all(p.isdigit() for p in parts):
        return None
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds or None


def parse_results(rows: list[dict]) -> list[dict]:
    from .course_service import video_urls
    items, seen = [], set()
    checked_at = dt.datetime.now(dt.timezone.utc).isoformat()
    for row in rows:
        bvid = str(row.get("bvid") or "")
        if not re.fullmatch(r"BV[0-9A-Za-z]{10}", bvid) or bvid in seen:
            continue
        title = _text(row.get("title"))
        if not title:
            continue
        seen.add(bvid)
        cover = str(row.get("pic") or "")
        if cover.startswith("//"):
            cover = "https:" + cover
        items.append({"id": f"bilibili-{bvid}", "bvid": bvid, "platform": "bilibili",
                      "title": title, "author": _text(row.get("author"), 100),
                      "format": "搜索结果", "language": "", "topics": [], "kps": [],
                      "reason": "与搜索词相关，打开课程确认目录与适用基础", "note": "",
                      "cover_url": _cover(cover), "duration_seconds": _duration(row.get("duration")),
                      "published_at": None, "chapters": [], "subtitle_status": "未确认",
                      "source": "bilibili_search", "retrieved_at": checked_at,
                      "match": False, **video_urls(bvid)})
        if len(items) >= 12:
            break
    return items


def search_bilibili(query: str) -> dict:
    query = " ".join(query.split())[:120]
    now = time.monotonic()
    with _LOCK:
        cached = _CACHE.get(query)
        if cached and cached[0] > now:
            return {**copy.deepcopy(cached[1]), "cached": True}
    try:
        response = requests.get("https://api.bilibili.com/x/web-interface/search/type",
                                params={"search_type": "video", "keyword": query},
                                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://search.bilibili.com/"},
                                timeout=(3, 5), allow_redirects=False)
        response.raise_for_status()
        data = response.json()
        rows = (data.get("data") or {}).get("result")
        if data.get("code") != 0 or not isinstance(rows, list):
            raise ValueError("search unavailable")
        items = parse_results(rows)
        if rows and not items:
            raise ValueError("no usable video results")
        result = {"status": "ok", "items": items, "cached": False}
    except (requests.RequestException, ValueError, KeyError, TypeError, AttributeError):
        result = {"status": "unavailable", "items": [], "cached": False}
    with _LOCK:
        if len(_CACHE) >= 128:
            _CACHE.pop(next(iter(_CACHE)))
        _CACHE[query] = (time.monotonic() + (600 if result["status"] == "ok" else 30), copy.deepcopy(result))
    return result
