from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import config
from app.auth import bind_request_user, reset_request_user
from app.llm import selected_model, spark_client
from app.services import model_preferences as preferences, study_research
from app.services.profile_service import ensure_user
from app.models.db import session
from app.models.entities import ModelPreference


@pytest.fixture
def user():
    import uuid
    value = "upgrade_" + uuid.uuid4().hex
    ensure_user(value)
    return value


def test_personal_keys_are_encrypted_and_never_returned(user):
    key = "sk-test-only-private-key"
    public = preferences.save(user, {"default":"deepseek-flash"}, {"deepseek":key})
    assert key not in json.dumps(public)
    assert public["providers"]["deepseek"]["has_personal_key"]
    with session() as db:
        encrypted = db.get(ModelPreference, user).credentials["deepseek"]
    assert key not in encrypted
    assert preferences._open(user,"deepseek",encrypted) == key
    with pytest.raises(HTTPException):
        preferences._open("another_user","deepseek",encrypted)
    with pytest.raises(HTTPException):
        preferences._open(user,"kimi",encrypted)


def test_model_routes_are_tenant_and_capability_specific(user):
    preferences.save(user, {"default":"deepseek-flash", "english":"kimi-k3"},
                     {"deepseek":"test-deepseek", "kimi":"test-kimi"})
    token = bind_request_user(user)
    try:
        assert preferences.resolve("CAPABILITY=english.scene\n")['model']=="kimi-k3"
        assert preferences.resolve("CAPABILITY=doc.complete_notes\n")['model']=="deepseek-flash"
    finally:
        reset_request_user(token)
    assert preferences.resolve("CAPABILITY=english.scene\n") is None


def test_deleting_in_use_key_requires_clear_or_replacement(user, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    config.get_settings.cache_clear()
    preferences.save(user,{"default":"deepseek-flash"},{"deepseek":"test-secret"})
    with pytest.raises(HTTPException):
        preferences.save(user,{"default":"deepseek-flash"},{"deepseek":""})
    assert preferences.view(user)["providers"]["deepseek"]["has_personal_key"]
    public = preferences.save(user,{}, {"deepseek":""})
    assert not public["providers"]["deepseek"]["has_personal_key"]


def test_unknown_model_and_provider_are_rejected(user):
    with pytest.raises(HTTPException):
        preferences.save(user,{"default":"arbitrary-model"},{})
    with pytest.raises(HTTPException):
        preferences.save(user,{}, {"http://127.0.0.1":"private-key"})


def test_stale_settings_cannot_overwrite_another_tab(user):
    first = preferences.save(user, {}, {"deepseek": "private-key-one"}, revision=0)
    with pytest.raises(HTTPException) as conflict:
        preferences.save(user, {}, {"kimi": "private-key-two"}, revision=0)
    assert conflict.value.status_code == 409
    second = preferences.save(user, {}, {"kimi": "private-key-two"}, revision=first["revision"])
    assert second["providers"]["deepseek"]["has_personal_key"]
    assert second["providers"]["kimi"]["has_personal_key"]


def test_subtitle_replay_time_is_derived_from_matching_cue():
    from app.services.subtitle_service import source_lines
    subtitles = "1\n00:00:01,000 --> 00:00:03,000\nDon't hesitate.\n\n2\n00:00:04,000 --> 00:00:06,000\nI can figure it out."
    result = source_lines([{"text": "I can figure it out.", "timestamp": "00:00:01,000"}], subtitles)
    assert result[0]["timestamp"] == "00:00:04,000"
    with pytest.raises(ValueError):
        source_lines([{"text": "This line was invented.", "timestamp": "00:00:01,000"}], subtitles)


def test_subtitles_without_blank_separators_keep_each_replay_time():
    from app.services.subtitle_service import source_lines
    subtitles = "1\n00:01.000 --> 00:02.000\nDon't hesitate.\n2\n00:03.000 --> 00:04.000\nI can figure it out."
    result = source_lines([{"text": "I can figure it out."}], subtitles)
    assert result[0]["timestamp"] == "00:03.000"


def test_knowledge_usage_questions_are_not_product_help():
    from app.agents.tutor_agent import _needs_retrieval
    assert _needs_retrieval("英语中 hesitate 怎么用？")
    assert _needs_retrieval("如何使用递归？")
    assert not _needs_retrieval("这个软件怎么用？")


def test_followups_wait_for_pending_turn_instead_of_mixing_rounds(monkeypatch):
    from app.api import learning
    monkeypatch.setattr(learning, "_scope", lambda _: "test-user")
    monkeypatch.setattr(learning, "get_session_messages", lambda *a: [
        {"role": "user", "content": "旧问题"}, {"role": "assistant", "content": "旧回答"},
        {"role": "user", "content": "新问题"}])
    result = asyncio.run(learning.followups.__wrapped__(learning.FollowupRequest(session_id="test")))
    assert result == {"suggestions": [], "mode": "empty"}


def test_research_string_queries_do_not_become_character_searches(monkeypatch):
    received = []
    async def complete(*args, **kwargs):
        return '{"queries":"梯度下降","questions":"运行机制"}'
    async def discover(queries):
        received.extend(queries)
        return [], []
    monkeypatch.setattr(study_research, "llm_complete", complete)
    monkeypatch.setattr(study_research, "discover", discover)
    result = asyncio.run(study_research.research("如何理解梯度下降？"))
    assert received == ["如何理解梯度下降？"]
    assert result["plan"]["questions"][1] == "理解运行机制"


def test_knowledge_map_splitting_preserves_sections():
    from app.agents.doc_agent import _one_page_parts
    markdown = "# 01 概念与机制\n\nA → B\n\n# 02 应用与复习\n\n公式的适用条件"
    parts = _one_page_parts(markdown)
    assert len(parts) == 2 and "\n\n".join(parts) == markdown


def test_selected_tutor_failure_cannot_be_presented_as_a_mock_lesson(user, monkeypatch):
    from app.agents import tutor_agent
    monkeypatch.setattr(tutor_agent, "resolve", lambda _: {"model": "deepseek-flash"})
    monkeypatch.setattr(tutor_agent, "retrieve", lambda *a, **k: [])
    async def fail(*args, **kwargs):
        raise RuntimeError("HTTP 429")
        yield ""
    monkeypatch.setattr(tutor_agent, "llm_stream", fail)
    result = asyncio.run(tutor_agent.run({"user_id": user, "session_id": user,
        "messages": [{"role": "user", "content": "英语中hesitate怎么用"}],
        "topic_label": "英语", "student_profile": {}}))
    assert "本次没有生成讲解" in result["answer"]


def test_kimi_and_openai_have_distinct_official_wire_contracts():
    params=selected_model._request({"provider":"kimi","model":"kimi-k3"},[],700,True,"disabled")
    assert params['max_completion_tokens']>=4096 and params['reasoning_effort']=='low'
    assert 'temperature' not in params and 'max_tokens' not in params and 'extra_body' not in params
    params=selected_model._request({"provider":"openai","model":"gpt-6-astra"},[],700,True,"disabled")
    assert params['store'] is False and params['reasoning']['effort']=='low'


def test_selected_model_bypasses_demo_and_never_changes_provider(user,monkeypatch):
    preferences.save(user,{'default':'kimi-k3'},{'kimi':'test-private-key'})
    calls=[]
    async def complete(route,messages,**kwargs):
        calls.append(route)
        return '模型的真实响应'
    monkeypatch.setattr(selected_model,'complete',complete)
    token=bind_request_user(user)
    try:
        assert asyncio.run(spark_client.llm_complete('CAPABILITY=tutor.guided\n'))=='模型的真实响应'
        assert calls[0]['provider']=='kimi'
        async def fail(*args,**kwargs):raise RuntimeError('HTTP 429')
        monkeypatch.setattr(selected_model,'complete',fail)
        with pytest.raises(RuntimeError):asyncio.run(spark_client.llm_complete('hello'))
    finally:reset_request_user(token)


def test_discovery_deduplicates_sources_and_keeps_metadata_distinct(monkeypatch):
    async def encyclopedia(client,q):return [{'title':'Topic','url':'https://en.wikipedia.org/wiki/Topic','excerpt':'Evidence','kind':'百科导言'}]
    async def papers(client,q):return [{'title':'Paper','url':'https://doi.org/10.1000/test','excerpt':'','kind':'论文题录（未取得摘要）'}]
    monkeypatch.setattr(study_research,'_encyclopedia',encyclopedia)
    monkeypatch.setattr(study_research,'_papers',papers)
    sources,failures=asyncio.run(study_research.discover(['one','two']))
    assert len(sources)==2 and [s['id'] for s in sources]==[1,2]
    assert sources[1]['excerpt']=='' and not failures


def test_research_rejects_fabricated_citation_and_exposes_partial_status(monkeypatch):
    async def complete(prompt,**kwargs):
        return '{"queries":["example"],"questions":["why"]}' if 'research.plan' in prompt else '结论 [999]'
    async def discover(queries):return ([{'id':1,'title':'Evidence','url':'https://example.org/','excerpt':'Fact'}],[])
    monkeypatch.setattr(study_research,'llm_complete',complete)
    monkeypatch.setattr(study_research,'discover',discover)
    result=asyncio.run(study_research.research('研究问题'))
    assert result['status']=='sources_only' and '[999]' not in result['markdown']


def test_offline_research_never_searches_or_fabricates_sources(monkeypatch):
    async def fail(*args):raise AssertionError('unexpected network')
    monkeypatch.setattr(study_research,'discover',fail)
    result=asyncio.run(study_research.research('研究问题',offline=True))
    assert result['status']=='offline' and result['sources']==[]


def test_settings_auth_and_validation_never_echo_key(monkeypatch):
    from app.main import app
    monkeypatch.setenv('AUTH_REQUIRED','true');config.get_settings.cache_clear()
    client=TestClient(app)
    assert client.get('/api/settings/models').status_code==401
    monkeypatch.setenv('AUTH_REQUIRED','false');config.get_settings.cache_clear()
    secret='private-should-not-appear'
    response=client.post('/api/settings/models',json={'keys':{str(i):secret for i in range(10)}})
    assert response.status_code==422 and secret not in response.text


def test_video_metadata_does_not_invent_captions_or_allow_arbitrary_embeds():
    from app.services.video_metadata import parse_bilibili, youtube_urls
    metadata=parse_bilibili({'title':'course','pic':'http://i0.hdslb.com/a.jpg','duration':120,'pages':[{'page':1,'part':'Introduction','duration':120}]},'BV1b7411N798')
    assert metadata['published_at'] is None and '未确认' in metadata['subtitle_status']
    assert metadata['cover_url'].startswith('https://')
    assert 'p=1' in metadata['chapters'][0]['url']
    with pytest.raises(ValueError):youtube_urls('https://evil.test')
