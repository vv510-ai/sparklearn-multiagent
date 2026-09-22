"""Public metadata only; no media downloading or subtitle access bypass."""
from __future__ import annotations

import datetime as dt
import json
import re
import time
from urllib.parse import urlencode, urlparse

import requests

_CACHE: dict[tuple[str, str], tuple[float, dict]] = {}


def youtube_urls(video_id: str) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("invalid YouTube identifier")
    return {"watch_url": f"https://www.youtube.com/watch?v={video_id}",
            "preview_url": f"https://www.youtube-nocookie.com/embed/{video_id}?autoplay=0"}


def _cover(url: str) -> str | None:
    value = str(url or "").replace("http://", "https://", 1)
    host = urlparse(value).hostname or ""
    return value if value.startswith("https://") and (host.endswith(".hdslb.com") or host.endswith(".ytimg.com")) else None


def parse_bilibili(data: dict, bvid: str) -> dict:
    from .course_service import video_urls
    video_urls(bvid)
    chapters = [{"title": str(p.get("part", "")), "duration_seconds": int(p.get("duration", 0)),
                 "url": f"https://www.bilibili.com/video/{bvid}/?p={int(p['page'])}"}
                for p in data.get("pages", []) if p.get("page")][:200]
    subtitles = data.get("subtitle", {}).get("list")
    return {"title": data["title"], "cover_url": _cover(data.get("pic", "")),
            "duration_seconds": data.get("duration"),
            "published_at": dt.datetime.fromtimestamp(data["pubdate"], dt.timezone.utc).date().isoformat() if data.get("pubdate") else None,
            "chapters": chapters, "subtitle_status": "、".join(str(s.get("lan_doc", "")) for s in subtitles) if subtitles else "未确认，请在播放器查看",
            "metadata_source": "B站公开视频信息", "metadata_checked_at": dt.datetime.now(dt.timezone.utc).date().isoformat()}


def parse_youtube(data: dict, video_id: str) -> dict:
    youtube_urls(video_id)
    details = data.get("videoDetails", {})
    micro = data.get("microformat", {}).get("playerMicroformatRenderer", {})
    tracks = data.get("captions", {}).get("playerCaptionsTracklistRenderer", {}).get("captionTracks", [])
    chapters = []
    for line in str(details.get("shortDescription", "")).splitlines():
        match = re.match(r"\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\s+(.+)", line)
        if match:
            seconds = int(match[1] or 0)*3600 + int(match[2])*60 + int(match[3])
            chapters.append({"title": match[4][:180], "start_seconds": seconds,
                             "url": f"https://www.youtube.com/watch?v={video_id}&t={seconds}s"})
    thumbnails = details.get("thumbnail", {}).get("thumbnails", [])
    return {"title": details["title"], "author": details.get("author", ""),
            "cover_url": _cover(thumbnails[-1].get("url", "")) if thumbnails else None,
            "duration_seconds": int(details["lengthSeconds"]) if details.get("lengthSeconds") else None,
            "published_at": micro.get("publishDate"), "chapters": chapters[:100],
            "subtitle_status": "、".join(t.get("languageCode", "") + ("（自动）" if t.get("kind") == "asr" else "") for t in tracks) if tracks else "未确认，请在播放器查看",
            "metadata_source": "YouTube公开页面", "metadata_checked_at": dt.datetime.now(dt.timezone.utc).date().isoformat()}


def fetch_metadata(platform: str, identifier: str) -> dict:
    key = (platform, identifier)
    cached = _CACHE.get(key)
    if cached and time.monotonic() - cached[0] < 21600:
        return dict(cached[1])
    headers = {"User-Agent": "Mozilla/5.0"}
    if platform == "bilibili":
        from .course_service import video_urls
        video_urls(identifier)
        response = requests.get("https://api.bilibili.com/x/web-interface/view", params={"bvid": identifier}, headers=headers, timeout=5)
        response.raise_for_status()
        data = response.json()
        if data.get("code") != 0:
            raise ValueError("video metadata unavailable")
        result = parse_bilibili(data["data"], identifier)
    elif platform == "youtube":
        urls = youtube_urls(identifier)
        try:
            response = requests.get(urls["watch_url"], headers=headers, timeout=5)
            response.raise_for_status()
            match = re.search(r"ytInitialPlayerResponse\s*=\s*", response.text)
            if not match:
                raise ValueError("public player metadata unavailable")
            data, _ = json.JSONDecoder().raw_decode(response.text[match.end():])
            result = parse_youtube(data, identifier)
        except (requests.RequestException, ValueError, KeyError, TypeError):
            response = requests.get("https://www.youtube.com/oembed", params={"url": urls["watch_url"], "format": "json"}, headers=headers, timeout=5)
            response.raise_for_status()
            data = response.json()
            result = {"title": data["title"], "author": data.get("author_name", ""),
                      "cover_url": _cover(data.get("thumbnail_url", "")),
                      "metadata_source": "YouTube oEmbed（标题与封面）", "metadata_checked_at": dt.datetime.now(dt.timezone.utc).date().isoformat(),
                      "metadata_notice": "当前未取得时长、日期、字幕与章节，打开原视频查看"}
    else:
        raise ValueError("unsupported video platform")
    if len(_CACHE) >= 128:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = (time.monotonic(), result)
    return dict(result)
