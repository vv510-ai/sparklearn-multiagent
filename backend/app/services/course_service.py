"""Reviewed catalogue with official Bilibili search and click-to-load embeds.

Catalogue results are never represented as live Bilibili search results.
Only fixed, validated video identifiers can produce a player URL.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlencode

from .knowledge_graph import all_kp_ids, kp_name
from .profile_service import get_profile
from .learning_scope import current_space


def video_urls(bvid: str) -> dict:
    if not re.fullmatch(r"BV[0-9A-Za-z]{10}", bvid):
        raise ValueError("invalid Bilibili video identifier")
    return {"watch_url": f"https://www.bilibili.com/video/{bvid}/?p=1",
            "preview_url": "https://player.bilibili.com/player.html?" + urlencode({"bvid": bvid, "p": 1, "autoplay": 0, "poster": 1, "danmaku": 0})}


def recommend(user_id: str, query: str = "", kp: str = "") -> dict:
    profile = get_profile(user_id)
    known = all_kp_ids()
    if kp not in known:
        kp = ""
    weak = [s for s in profile.get("baseline_assessment", {}).get("skills", []) if s["status"] in ("gap", "developing")]
    target = kp or (weak[0]["kp"] if weak else "")
    reason = f"你选择了{kp_name(kp)}" if kp else f"本次摸底建议先巩固{kp_name(target)}" if target else "先从课程基础开始，完成起点测评后可按薄弱点筛选"
    query = query.strip()[:120]
    search_text = query or (f"数据结构 {kp_name(target)}" if target else "数据结构与算法 入门")
    catalog = json.loads((Path(__file__).resolve().parents[1] / "data" / "course_catalog.json").read_text(encoding="utf-8"))
    if current_space() and current_space()["course"].get("kind") != "ds_algo":
        catalog = []
        search_text = query or f"{current_space()['course']['title']} {kp_name(target) if target else '入门'}"
    results = []
    for item in catalog:
        haystack = " ".join([item["title"], item["author"], *[kp_name(k) for k in item["kps"]]]).casefold()
        if query and not all(token in haystack for token in query.casefold().split()):
            continue
        if kp and kp not in item["kps"]:
            continue
        matched = bool(target and target in item["kps"])
        results.append({**item, **video_urls(item["bvid"]), "topics": [kp_name(k) for k in item["kps"]],
                        "reason": reason if matched else "课程资料库中的补充课程；按目录确认适合自己的章节",
                        "match": matched, "cover_url": None, "duration_seconds": None})
    results.sort(key=lambda item: (not item["match"], len(item["kps"])))
    return {"items": results, "query": query, "target_kp": target, "reason": reason,
            "search_url": "https://search.bilibili.com/all?" + urlencode({"keyword": search_text}),
            "search_text": search_text, "source": "curated_catalog",
            "notice": ("当前课程尚无人工核验的视频条目，可按本课程主题在 B 站搜索。" if current_space() and current_space()["course"].get("kind") != "ds_algo" else "当前展示已核验公开页面的课程资料库，并非 B 站实时搜索结果。内容质量需试听确认；播放、登录与可用性由 B 站决定。"),
            "topics": [{"id": k, "name": kp_name(k)} for k in known]}
