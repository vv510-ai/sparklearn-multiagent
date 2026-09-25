"""Original English scene media contract, shared by publish validation and reads."""
from __future__ import annotations
import hashlib
import math
from pathlib import Path
import re
import wave

MEDIA_ROOT = Path(__file__).resolve().parents[1] / "data/course_media"


def media_file(audio: dict) -> Path:
    relative = audio.get("file", "")
    if not re.fullmatch(r"[a-z0-9-]+/[a-z0-9-]+\.wav", relative):
        raise ValueError("Invalid scene audio path")
    path = (MEDIA_ROOT / relative).resolve()
    if MEDIA_ROOT.resolve() not in path.parents or not path.is_file():
        raise ValueError("Scene audio missing")
    if hashlib.sha256(path.read_bytes()).hexdigest() != audio.get("sha256"):
        raise ValueError("Scene audio hash mismatch")
    return path


def validate_scene(lesson: dict) -> None:
    scene = lesson.get("scene", {})
    lines, steps, audio = scene.get("lines", []), scene.get("steps", []), scene.get("audio", {})
    if not scene.get("context") or len(lines) < 2 or not steps or not lesson.get("work_reference"):
        raise ValueError("Incomplete English scene")
    if len({line["id"] for line in lines}) != len(lines) or any(not all(line.get(k) for k in ("text", "translation", "speaker")) for line in lines):
        raise ValueError("Invalid scene lines")
    if any(not all(s.get(k) for k in ("id", "title", "parts", "explanation")) for s in steps):
        raise ValueError("Invalid animation steps")
    transcript = "\n".join(line["text"] for line in lines)
    if hashlib.sha256(transcript.encode()).hexdigest() != audio.get("transcript_sha256"):
        raise ValueError("Audio transcript hash mismatch")
    path = media_file(audio)
    with wave.open(str(path), "rb") as w:
        if (w.getframerate(), w.getnchannels(), w.getsampwidth()) != (22050, 1, 2):
            raise ValueError("Invalid scene PCM format")
        duration = w.getnframes() / w.getframerate()
    if not math.isfinite(audio.get("duration", float("nan"))) or abs(duration - audio["duration"]) > .001:
        raise ValueError("Scene duration mismatch")
    cues = audio.get("cues", [])
    if [cue["line_id"] for cue in cues] != [line["id"] for line in lines]:
        raise ValueError("Missing or reordered scene cues")
    end = 0
    for cue in cues:
        if not 0 <= end <= cue["start"] < cue["end"] <= duration:
            raise ValueError("Overlapping or invalid scene cue")
        end = cue["end"]


def public_scene(scene: dict, release_id: str, lesson_id: str) -> dict:
    import copy
    result = copy.deepcopy(scene)
    result["audio"].pop("file", None)
    result["audio"]["url"] = f"/api/library/releases/{release_id}/media/{lesson_id}"
    return result
