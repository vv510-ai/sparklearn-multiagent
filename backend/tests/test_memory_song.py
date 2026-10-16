"""Memory songs: model-chosen music, lyric review before any paid request, idempotent Suno use."""
import asyncio
import json

import pytest
import httpx

from app.agents import music_agent
from app.llm import suno_client
from app.services import memory_song

PLAN = {"title": "光合作用说唱", "key_points": ["光反应在类囊体膜上进行", "暗反应在叶绿体基质进行", "光反应产生ATP和NADPH", "暗反应固定二氧化碳"],
        "mnemonic": [{"line": "光在膜上造能量", "meaning": "光反应在类囊体膜产生ATP和NADPH"},
                     {"line": "暗在基质固碳忙", "meaning": "暗反应在叶绿体基质固定CO2"}],
        "plan": {"genre": "说唱", "style_tags": "Mandopop, hip hop, catchy hook, 96 bpm, male vocal", "bpm": 96,
                 "mood": "有能量", "vocal_gender": "male", "structure": ["Verse 1", "Chorus"], "reason": "并列要点适合节拍切分"}}
LYRICS = {"lyrics": "[Verse 1]\n" + "\n".join(["光在膜上造能量", "暗在基质固碳忙"] * 5) + "\n[Chorus]\n光在膜上造能量\n暗在基质固碳忙",
          "negative_tags": "", "cloze": [{"line": "光在膜上造能量", "answer": "膜上"}, {"line": "不存在的句子", "answer": "x"}]}


@pytest.fixture
def models(monkeypatch):
    monkeypatch.setattr(memory_song, "is_demo", lambda: False)
    monkeypatch.setattr(memory_song, "emit", _noop)
    reviews = []

    async def complete(prompt, **kwargs):
        if "TASK=music_plan" in prompt:
            return json.dumps(PLAN, ensure_ascii=False)
        if "TASK=music_lyrics" in prompt:
            return json.dumps(LYRICS, ensure_ascii=False)
        if "TASK=music_review" in prompt:
            return json.dumps(reviews.pop(0) if reviews else {"status": "passed", "issues": []}, ensure_ascii=False)
        raise AssertionError(prompt[:60])
    monkeypatch.setattr(memory_song, "llm_complete", complete)
    return reviews


async def _noop(*args, **kwargs):
    return None


def test_full_pipeline_submits_once_with_idempotency_key_and_stores_media(models, monkeypatch, tmp_path):
    monkeypatch.setattr(memory_song, "GEN_DIR", tmp_path)
    monkeypatch.setattr(suno_client, "available", lambda: True)
    submitted = []

    async def create(**kwargs):
        submitted.append(kwargs)
        return "ac_test_request"

    async def wait(request_id, **kwargs):
        return [{"song_id": "s1", "song_title": "光合作用说唱", "audio_url": "https://cdn.test/a.mp3", "cover_url": "https://cdn.test/c.jpg", "duration": 120.5, "status": "completed"}]

    async def download(url, *, limit):
        return b"ID3-audio" if url.endswith(".mp3") else b"\xff\xd8cover"

    async def timeline(song_id):
        return [{"word": "光在膜上造能量\n", "start_s": 12, "end_s": 14, "success": True}]
    monkeypatch.setattr(suno_client, "create_custom", create)
    monkeypatch.setattr(suno_client, "wait_for_songs", wait)
    monkeypatch.setattr(suno_client, "download", download)
    monkeypatch.setattr(suno_client, "timeline", timeline)
    song = asyncio.run(memory_song.generate("光合作用", goal="记住光合作用", persona="", context="", job_key="job_1"))
    assert song["status"] == "ready" and song["plan"]["genre"] == "说唱"
    assert len(submitted) == 1 and len(submitted[0]["idempotency_key"]) == 64
    assert submitted[0]["style_tags"].startswith("Mandopop") and submitted[0]["vocal_gender"] == "male"
    version = song["versions"][0]
    assert (tmp_path / version["audio_url"].split("/")[-1]).read_bytes() == b"ID3-audio"
    assert version["timeline"] == [{"text": "光在膜上造能量", "start": 12.0, "end": 14.0}]
    assert song["cloze"] == [{"line": "光在膜上造能量", "answer": "膜上"}]  # invented lines are dropped


def test_wrong_lyrics_are_repaired_once_and_never_sung_if_still_wrong(models, monkeypatch):
    models.extend([{"status": "failed", "issues": ["把暗反应位置写成了类囊体"]},
                   {"status": "failed", "issues": ["仍把暗反应位置写错"]}])
    monkeypatch.setattr(suno_client, "available", lambda: True)

    async def must_not_submit(**kwargs):
        raise AssertionError("a song that teaches a wrong fact must not be generated")
    monkeypatch.setattr(suno_client, "create_custom", must_not_submit)
    song = asyncio.run(memory_song.generate("光合作用", goal="", persona="", context="", job_key="job_2"))
    assert song["status"] == "lyrics_only" and song["review"]["status"] == "failed" and song["review"]["repaired"]
    assert "没有生成音乐" in song["error"]


def test_missing_music_key_still_returns_mnemonic_and_lyrics(models, monkeypatch):
    monkeypatch.setattr(suno_client, "available", lambda: False)
    song = asyncio.run(memory_song.generate("光合作用", goal="", persona="", context="", job_key="job_3"))
    assert song["status"] == "lyrics_only" and song["mnemonic"][0]["line"] == "光在膜上造能量"
    assert "SUNO_API_KEY" in song["error"]


def test_suno_failures_are_reported_without_retrying_a_paid_request(models, monkeypatch):
    monkeypatch.setattr(suno_client, "available", lambda: True)
    calls = []

    async def create(**kwargs):
        calls.append(kwargs)
        raise suno_client.SunoError("insufficient_balance", "音乐服务返回 HTTP 402：余额不足")
    monkeypatch.setattr(suno_client, "create_custom", create)
    song = asyncio.run(memory_song.generate("光合作用", goal="", persona="", context="", job_key="job_4"))
    assert len(calls) == 1 and song["status"] == "lyrics_only" and "402" in song["error"]


def test_music_agent_only_runs_for_song_requests_and_emits_a_song_resource(monkeypatch):
    assert asyncio.run(music_agent.run({"kinds": ["doc"]})) == {}
    events = []

    async def emit(event):
        events.append(event)

    async def generate(topic, **kwargs):
        return {"status": "ready", "title": "测试歌", "plan": {"genre": "流行"}, "versions": [{"song_id": "s", "audio_url": "/static/gen/x.mp3"}]}
    monkeypatch.setattr(music_agent, "emit", emit)
    monkeypatch.setattr(music_agent, "agent_start", lambda *a, **k: _noop())
    monkeypatch.setattr(music_agent, "agent_end", lambda *a, **k: _noop())
    monkeypatch.setattr(music_agent.memory_song, "generate", generate)
    out = asyncio.run(music_agent.run({"kinds": ["song"], "topic_label": "光合作用", "learning_goal": "编成歌",
                                       "one_page_scope": {"topic": "光合作用", "kp": "custom_topic"}}))
    resource = next(iter(out["generated_resources"].values()))
    assert resource["kind"] == "song" and resource["title"] == "光合作用·记忆歌曲"
    assert resource["payload"]["song"]["status"] == "ready"
    assert any(event["type"] == "resource" for event in events)


def test_free_text_song_request_routes_to_the_music_agent_with_scope_template():
    from app.agents import orchestrator
    assert orchestrator.requested_resource_kinds("把光合作用编成一首歌") == ["song"]
    assert orchestrator.requested_resource_kinds("不要编成歌，直接讲") == []
    out = asyncio.run(orchestrator.run({"messages": [{"role": "user", "content": "帮我把光合作用编成一首记忆歌曲"}]}))
    assert out["intent"] == "generate" and out["kinds"] == ["song"] and out["prompt_template"] == "memory_song"


@pytest.mark.parametrize("failure", [httpx.ReadTimeout, httpx.WriteError])
def test_suno_does_not_switch_hosts_after_ambiguous_paid_submission(monkeypatch, failure):
    from app.services.generation_jobs import SubmissionUncertain
    calls = []
    monkeypatch.setattr(suno_client, "config", lambda: suno_client.SunoConfig("test", ("https://primary.invalid", "https://backup.invalid"), "suno-v6"))

    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def request(self, method, url, **kwargs):
            calls.append(url)
            raise failure("connection interrupted after submit")

    monkeypatch.setattr(suno_client.httpx, "AsyncClient", Client)
    with pytest.raises(SubmissionUncertain):
        asyncio.run(suno_client._request("POST", "/api/music/create/custom", json_body={}))
    assert calls == ["https://primary.invalid/api/music/create/custom"]


def test_suno_can_switch_hosts_if_connect_failed_before_submission(monkeypatch):
    calls = []
    monkeypatch.setattr(suno_client, "config", lambda: suno_client.SunoConfig("test", ("https://primary.invalid", "https://backup.invalid"), "suno-v6"))

    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def request(self, method, url, **kwargs):
            calls.append(url)
            if len(calls) == 1:
                raise httpx.ConnectTimeout("not connected")
            return httpx.Response(202, json={"data": {"request_id": "ac_test"}})

    monkeypatch.setattr(suno_client.httpx, "AsyncClient", Client)
    result = asyncio.run(suno_client._request("POST", "/api/music/create/custom", json_body={}))
    assert len(calls) == 2 and result["data"]["request_id"] == "ac_test"
