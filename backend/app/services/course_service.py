"""Relevant course snapshots plus bounded, explicitly labelled public search."""
import json
import re
from pathlib import Path
from urllib.parse import urlencode

from ..config import is_demo
from .course_search import search_bilibili
from .video_metadata import youtube_urls
from .knowledge_graph import all_kp_ids, kp_name
from .profile_service import get_profile
from .learning_scope import current_space


def video_urls(bvid: str) -> dict:
    if not re.fullmatch(r"BV[0-9A-Za-z]{10}", bvid):
        raise ValueError("invalid Bilibili video identifier")
    return {"watch_url": f"https://www.bilibili.com/video/{bvid}/?p=1",
            "preview_url": "https://player.bilibili.com/player.html?" + urlencode({"bvid": bvid, "p": 1, "autoplay": 0, "poster": 1, "danmaku": 0})}


def _normalized(value: str) -> str:
    value = re.sub(r"[\s_\-·]+", "", value.casefold())
    return value.replace("大学英语六级", "六级").replace("英语六级", "六级").replace("cet6", "六级").replace("高等数学", "高数")


def _matches(query: str, item: dict) -> bool:
    haystack = _normalized(" ".join([item["title"], item["author"], *item.get("aliases", []),
                                     *[kp_name(k) for k in item.get("kps", [])]]))
    return all(_normalized(token) in haystack for token in query.split())


def recommend(user_id: str, query: str = "", kp: str = "", platform: str = "", topic: str = "") -> dict:
    profile = get_profile(user_id)
    known = all_kp_ids()
    kp = kp if kp in known else ""
    weak = [s for s in (profile.get("baseline_assessment") or {}).get("skills", [])
            if s.get("status") in ("gap", "developing") and s.get("kp") in known]
    target = kp or (weak[0]["kp"] if weak else "")
    query, topic = query.strip()[:120], topic.strip()[:120]
    course = (current_space() or {}).get("course") or {}
    course_kind = course.get("kind", "ds_algo" if not topic else "")
    course_title = course.get("title") or topic or "数据结构与算法"
    search_text = (query or f"{course_title} {kp_name(target) if target else '入门'}")[:120]
    reason = f"搜索：{query}" if query else f"先巩固：{kp_name(target)}" if target else f"适合「{course_title}」的课程"
    catalog = json.loads((Path(__file__).resolve().parents[1] / "data" / "course_catalog.json").read_text(encoding="utf-8"))
    results = []
    for original in catalog:
        item = dict(original)
        item.setdefault("platform", "bilibili")
        item.setdefault("language", "中文" if item["platform"] == "bilibili" else "英文")
        if platform and item["platform"] != platform:
            continue
        if query:
            if not _matches(query, item):
                continue
        elif course_kind:
            if item.get("course_kind", "ds_algo") != course_kind:
                continue
        elif topic and not _matches(topic, item):
            continue
        if kp and not query and kp not in item.get("kps", []):
            continue
        matched = bool(target and target in item.get("kps", []))
        urls = video_urls(item["bvid"]) if item["platform"] == "bilibili" else youtube_urls(item["video_id"])
        results.append({"cover_url": None, "duration_seconds": None, "published_at": None,
                        "chapters": [], "subtitle_status": "未确认", **item, **urls,
                        "source": "curated_catalog", "topics": [kp_name(k) for k in item.get("kps", []) if k in known],
                        "reason": reason if matched else "已收录课程，可按原站目录选择章节", "match": matched})
    results.sort(key=lambda item: (not item["match"], len(item.get("kps", []))))
    # Any explicit query can search outside the current notebook's subject.
    # Default recommendations load immediately from verified snapshots.
    live = {"status": "not_requested", "items": [], "cached": False}
    if platform != "youtube" and (query or topic or target or course_kind != "ds_algo"):
        live = {"status": "offline", "items": [], "cached": False} if is_demo() else search_bilibili(search_text)
    seen = {item["watch_url"] for item in results}
    results.extend(item for item in live["items"] if item["watch_url"] not in seen)
    notice = "B 站结果来自公开搜索；已收录课程为核验快照。YouTube 可搜索已收录课程或打开原站搜索。"
    if live["status"] == "unavailable":
        notice = "B 站实时搜索暂不可用，已保留匹配的收录课程；也可以直接去原站搜索。"
    elif live["status"] == "offline":
        notice = "离线演示仅搜索已收录课程；全站搜索请打开原站。"
    return {"items": results, "query": query, "target_kp": target, "reason": reason,
            "search_url": "https://search.bilibili.com/all?" + urlencode({"keyword": search_text}),
            "youtube_search_url": "https://www.youtube.com/results?" + urlencode({"search_query": search_text}),
            "search_text": search_text, "source": "catalog_and_search" if live["status"] == "ok" else "curated_catalog",
            "search_status": live["status"], "search_cached": live["cached"], "notice": notice,
            "topics": [{"id": k, "name": kp_name(k)} for k in known]}
