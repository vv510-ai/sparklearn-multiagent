"""Reviewed catalogue with official Bilibili search and click-to-load embeds.

Catalogue results are never represented as live Bilibili search results.
Only fixed, validated video identifiers can produce a player URL.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlencode
from concurrent.futures import ThreadPoolExecutor

from ..config import is_demo
from .video_metadata import fetch_metadata, youtube_urls

from .knowledge_graph import all_kp_ids, kp_name
from .profile_service import get_profile
from .learning_scope import current_space


def video_urls(bvid: str) -> dict:
    if not re.fullmatch(r"BV[0-9A-Za-z]{10}", bvid):
        raise ValueError("invalid Bilibili video identifier")
    return {"watch_url": f"https://www.bilibili.com/video/{bvid}/?p=1",
            "preview_url": "https://player.bilibili.com/player.html?" + urlencode({"bvid": bvid, "p": 1, "autoplay": 0, "poster": 1, "danmaku": 0})}


def recommend(user_id: str, query: str = "", kp: str = "", platform: str = "", topic: str = "") -> dict:
    profile = get_profile(user_id)
    known = all_kp_ids()
    if kp not in known:
        kp = ""
    weak = [s for s in profile.get("baseline_assessment", {}).get("skills", []) if s["status"] in ("gap", "developing")]
    target = kp or (weak[0]["kp"] if weak else "")
    reason = f"你选择了{kp_name(kp)}" if kp else f"本次摸底建议先巩固{kp_name(target)}" if target else "先从课程基础开始，完成起点测评后可按薄弱点筛选"
    query = query.strip()[:120]
    search_text = query or (f"数据结构 {kp_name(target)}" if target else topic.strip()[:120] or "数据结构与算法 入门")
    catalog = json.loads((Path(__file__).resolve().parents[1] / "data" / "course_catalog.json").read_text(encoding="utf-8"))
    if current_space() and current_space()["course"].get("kind") != "ds_algo":
        catalog = []
        search_text = query or f"{current_space()['course']['title']} {kp_name(target) if target else '入门'}"
    results = []
    for item in catalog:
        item = dict(item)
        item.setdefault("platform", "bilibili")
        item.setdefault("language", "中文" if item["platform"] == "bilibili" else "英文")
        if platform and item["platform"] != platform:
            continue
        haystack = " ".join([item["title"], item["author"], *[kp_name(k) for k in item["kps"]]]).casefold()
        if query and not all(token in haystack for token in query.casefold().split()):
            continue
        if kp and kp not in item["kps"]:
            continue
        matched = bool(target and target in item["kps"])
        urls = video_urls(item["bvid"]) if item["platform"] == "bilibili" else youtube_urls(item["video_id"])
        results.append({"cover_url": None, "duration_seconds": None, "published_at": None,
                        "chapters": [], "subtitle_status": "未确认，请在播放器查看", **item, **urls, "topics": [kp_name(k) for k in item["kps"]],
                        "reason": reason if matched else "课程资料库中的补充课程；按目录确认适合自己的章节",
                        "match": matched})
    def enrich(item):
        if not is_demo():
            try:
                item.update(fetch_metadata(item["platform"], item.get("bvid") or item["video_id"]))
            except Exception:
                item["metadata_notice"] = "本次未刷新完整信息；保留已核验快照，缺失项以原站为准"
        return item
    if results:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(enrich, results))
    results.sort(key=lambda item: (not item["match"], len(item["kps"])))
    return {"items": results, "query": query, "target_kp": target, "reason": reason,
            "search_url": "https://search.bilibili.com/all?" + urlencode({"keyword": search_text}),
            "youtube_search_url": "https://www.youtube.com/results?" + urlencode({"search_query": search_text}),
            "search_text": search_text, "source": "curated_catalog",
            "notice": ("当前课程尚无人工核验的视频条目，可按本课程主题在 B站 / YouTube 搜索。" if current_space() and current_space()["course"].get("kind") != "ds_algo" else "精选 B站 / YouTube 课程目录，非全站实时搜索。封面、时长、日期和章节来自公开元数据；缺失字段不补造。字幕状态不代表已取得字幕全文。播放、登录及地区可用性以原站为准。"),
            "topics": [{"id": k, "name": kp_name(k)} for k in known]}
