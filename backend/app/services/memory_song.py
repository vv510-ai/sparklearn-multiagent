"""Memory songs: key points → mnemonic → model-chosen music plan → lyrics → review → Suno.

The text model (Kimi/ChatGPT subscription through ``llm_complete``) decides the
genre, tempo and vocal from the shape of the content. Lyrics are checked against
the key points before any paid music request, so a catchy song cannot teach a
wrong fact. Audio and covers are stored locally because provider links expire.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re

from ..agents.emitter import emit
from ..config import GEN_DIR, is_demo
from ..llm import suno_client
from ..llm.spark_client import llm_complete, parse_json
from ..prompt_templates import invoke_learning_prompt

GENRES_FALLBACK = {
    "rap": ("说唱", "Mandopop, hip hop, rap, catchy hook, 96 bpm, male vocal", 96, "male"),
    "pop": ("流行", "Mandopop, pop, bright piano, catchy chorus, 108 bpm, female vocal", 108, "female"),
}


def _clean_lines(values, limit: int, width: int) -> list[str]:
    out = []
    for value in values if isinstance(values, list) else []:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if text:
            out.append(text[:width])
    return out[:limit]


def _normalize_plan(value: dict, topic: str) -> dict:
    value = value if isinstance(value, dict) else {}
    plan = value.get("plan") if isinstance(value.get("plan"), dict) else {}
    key_points = _clean_lines(value.get("key_points"), 8, 60)
    mnemonic = []
    for item in value.get("mnemonic") or []:
        if isinstance(item, dict) and str(item.get("line") or "").strip():
            mnemonic.append({"line": str(item["line"]).strip()[:24], "meaning": str(item.get("meaning") or "").strip()[:80]})
    if len(key_points) < 2 or len(mnemonic) < 2:
        raise ValueError("music plan lacks key points or mnemonic")
    genre, tags, bpm, gender = GENRES_FALLBACK["rap" if len(key_points) >= 5 else "pop"]
    style_tags = re.sub(r"\s+", " ", str(plan.get("style_tags") or "")).strip()[:180] or tags
    try:
        bpm = max(60, min(180, int(plan.get("bpm") or bpm)))
    except (TypeError, ValueError):
        pass
    gender = str(plan.get("vocal_gender") or gender).lower()
    return {
        "title": str(value.get("title") or f"{topic}记忆歌").strip()[:14],
        "key_points": key_points,
        "mnemonic": mnemonic[:8],
        "plan": {
            "genre": str(plan.get("genre") or genre).strip()[:20],
            "style_tags": style_tags,
            "bpm": bpm,
            "mood": str(plan.get("mood") or "").strip()[:12],
            "vocal_gender": "female" if gender.startswith("f") else "male",
            "structure": _clean_lines(plan.get("structure"), 10, 20),
            "reason": str(plan.get("reason") or "").strip()[:120],
        },
    }


def _normalize_lyrics(value: dict) -> dict:
    value = value if isinstance(value, dict) else {}
    lyrics = str(value.get("lyrics") or "").replace("\r", "").strip()
    lines = [line.strip() for line in lyrics.splitlines() if line.strip()]
    sung = [line for line in lines if not re.fullmatch(r"\[[^\]]{1,24}\]", line)]
    if len(sung) < 8 or len(lyrics) > 3000:
        raise ValueError("lyrics too short or too long")
    lyrics = "\n".join(lines)
    cloze = []
    for item in value.get("cloze") or []:
        if not isinstance(item, dict):
            continue
        line, answer = str(item.get("line") or "").strip(), str(item.get("answer") or "").strip()
        # Only keep blanks that really occur in a sung line.
        if line and answer and answer in line and line in sung and len(answer) <= 12:
            cloze.append({"line": line, "answer": answer})
    return {"lyrics": lyrics, "negative_tags": str(value.get("negative_tags") or "").strip()[:300], "cloze": cloze[:8]}


async def _json_call(capability: str, **values) -> dict:
    call = invoke_learning_prompt(capability, **values)
    raw = await asyncio.wait_for(llm_complete(call.prompt, system=call.system, role="reasoner", temperature=0.7,
        max_tokens=3200, json_object=True, reasoning_mode="disabled", allow_mock_fallback=False), timeout=150)
    value = parse_json(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{capability} returned no JSON object")
    return value


async def compose(topic: str, *, goal: str, persona: str, context: str) -> dict:
    """Write the mnemonic, choose the music, write and review the lyrics."""
    await emit({"type": "progress", "agent": "music", "stage": "mnemonic", "text": "正在提炼要点并编口诀…"})
    plan = _normalize_plan(await _json_call("music.plan", topic=topic, goal=goal or f"记住{topic}的核心知识",
                                            persona=persona, context=context or "（没有选资料，使用公认的通用知识）"), topic)
    await emit({"type": "progress", "agent": "music", "stage": "music_plan",
                "text": f"模型选择了「{plan['plan']['genre']}」·{plan['plan']['bpm']} BPM，正在写歌词…"})
    values = {"topic": topic, "key_points": "\n".join(f"- {item}" for item in plan["key_points"]),
              "mnemonic": "\n".join(f"- {item['line']}（{item['meaning']}）" for item in plan["mnemonic"]),
              "plan": json.dumps(plan["plan"], ensure_ascii=False)}
    lyrics = _normalize_lyrics(await _json_call("music.lyrics", **values, revision_notes=""))
    await emit({"type": "progress", "agent": "music", "stage": "lyrics_review", "text": "正在逐句核对歌词有没有会让人记错的地方…"})
    review = await review_lyrics(topic, plan["key_points"], lyrics["lyrics"])
    if review["status"] == "failed":
        notes = "上一版歌词的审校意见（必须全部修正，其余保持）：\n" + "\n".join(f"- {issue}" for issue in review["issues"])
        try:
            repaired = _normalize_lyrics(await _json_call("music.lyrics", **values, revision_notes=notes))
            second = await review_lyrics(topic, plan["key_points"], repaired["lyrics"])
            lyrics, review = repaired, {**second, "repaired": True}
        except Exception:
            review = {**review, "repair_failed": True}
    return {**plan, **lyrics, "review": review}


async def review_lyrics(topic: str, key_points: list[str], lyrics: str) -> dict:
    try:
        value = await _json_call("music.review", topic=topic, key_points="\n".join(f"- {item}" for item in key_points),
                                 lyrics=lyrics)
        status = "failed" if value.get("status") == "failed" else "passed"
        issues = _clean_lines(value.get("issues"), 8, 160)
        if status == "failed" and not issues:
            status = "passed"
        return {"status": status, "issues": issues}
    except Exception:
        return {"status": "unverified", "issues": ["歌词自动核对暂未完成，请对照口诀与讲解阅读。"]}


def _store(content: bytes, name: str) -> str:
    GEN_DIR.mkdir(parents=True, exist_ok=True)
    target = GEN_DIR / name
    partial = GEN_DIR / ("." + name + ".part")
    try:
        partial.write_bytes(content)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return f"/static/gen/{target.name}"


def _timeline(segments: list[dict]) -> list[dict]:
    """Merge word segments into sung lines, dropping section and instrument markers."""
    lines: list[dict] = []
    current, start, last_end = "", None, 0.0

    def flush(at: float):
        text = current.strip()
        if text and not re.match(r"^\[|^Instrumental:", text):
            lines.append({"text": text, "start": round(start if start is not None else at, 2), "end": round(at, 2)})

    for segment in segments:
        if not segment.get("success", True):
            continue
        try:
            begin, end = float(segment.get("start_s") or 0), float(segment.get("end_s") or 0)
        except (TypeError, ValueError):
            continue
        pieces = str(segment.get("word") or "").split("\n")
        for index, piece in enumerate(pieces):
            if index > 0:
                # A line that ends inside this segment ends when the segment does.
                flush(end if any(part.strip() for part in pieces[:index]) else begin)
                current, start = "", None
            if piece.strip():
                start = begin if start is None else start
                current += piece
        last_end = max(last_end, end)
    flush(last_end)
    return lines[:120]


async def render(song: dict, *, job_key: str) -> dict:
    """Submit to Suno once (idempotent key), wait, then store audio and covers locally."""
    plan = song["plan"]
    idempotency = hashlib.sha256(json.dumps([job_key, song["lyrics"], plan["style_tags"], song["title"]],
                                            ensure_ascii=False).encode()).hexdigest()
    await emit({"type": "progress", "agent": "music", "stage": "music_submit", "text": "歌词已核对，正在请 AI 歌手演唱（通常 1~3 分钟）…"})
    request_id = await suno_client.create_custom(lyrics=song["lyrics"], style_tags=plan["style_tags"], title=song["title"],
        vocal_gender=plan.get("vocal_gender", ""), negative_tags=song.get("negative_tags", ""), idempotency_key=idempotency)

    async def progress(state, tasks):
        done = sum(1 for task in tasks if task.get("status") == "completed")
        await emit({"type": "progress", "agent": "music", "stage": "music_render",
                    "text": f"AI 正在演唱与编曲（{done}/2 个版本完成）…" if state in {"processing", "partial"} else "已进入演唱队列…"})

    songs = await suno_client.wait_for_songs(request_id, on_progress=progress)
    versions = []
    for index, item in enumerate(songs[:2], 1):
        song_id = str(item.get("song_id") or item.get("id") or "")
        stem = "song_" + hashlib.sha256(f"{request_id}:{song_id}".encode()).hexdigest()[:24]
        try:
            audio = _store(await suno_client.download(str(item["audio_url"]), limit=suno_client.MAX_AUDIO_BYTES), stem + ".mp3")
        except Exception:
            continue
        cover = ""
        if item.get("cover_url") or item.get("image_url"):
            try:
                cover = _store(await suno_client.download(str(item.get("cover_url") or item.get("image_url")),
                                                          limit=suno_client.MAX_COVER_BYTES), stem + ".jpg")
            except Exception:
                cover = ""
        versions.append({"song_id": song_id, "title": str(item.get("song_title") or item.get("title") or song["title"])[:60],
                         "audio_url": audio, "cover_url": cover, "duration": item.get("duration"),
                         "status": "ready", "timeline": _timeline(await suno_client.timeline(song_id)) if song_id else []})
    if not versions:
        raise suno_client.SunoError("download_failed", "歌曲已生成，但音频没有保存成功，请稍后重试。")
    return {"request_id": request_id, "versions": versions}


async def generate(topic: str, *, goal: str, persona: str, context: str, job_key: str) -> dict:
    """Full pipeline. Returns the ``song`` payload; never raises for provider errors."""
    if is_demo():
        return {"status": "blocked", "topic": topic, "error": "演示模式不调用真实模型与音乐服务。"}
    try:
        song = await compose(topic, goal=goal, persona=persona, context=context)
    except Exception:
        return {"status": "failed", "topic": topic, "error": "口诀与歌词没有生成成功，请稍后重试。"}
    payload = {"status": "lyrics_only", "topic": topic, "title": song["title"], "mnemonic": song["mnemonic"],
               "key_points": song["key_points"], "plan": song["plan"], "lyrics": song["lyrics"],
               "cloze": song["cloze"], "review": song["review"], "provider": "suno", "model": suno_client.config().model}
    if song["review"]["status"] == "failed":
        payload["error"] = "歌词核对仍发现问题，为避免唱错知识，本次没有生成音乐。请先阅读口诀，或重新生成。"
        return payload
    if not suno_client.available():
        payload["error"] = "未配置音乐服务（SUNO_API_KEY），已生成口诀与歌词。"
        return payload
    try:
        rendered = await render(song, job_key=job_key)
    except suno_client.SunoError as exc:
        payload["error"] = exc.detail
        return payload
    except Exception:
        payload["error"] = "音乐生成没有完成，口诀与歌词已保存，可稍后重试。"
        return payload
    return {**payload, "status": "ready", "versions": rendered["versions"], "request_id": rendered["request_id"]}
