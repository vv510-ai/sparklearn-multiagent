from urllib.parse import parse_qs, urlparse

import pytest
import requests

from app.services import course_search as search, course_service as courses


@pytest.fixture(autouse=True)
def clean_cache(monkeypatch):
    search._CACHE.clear()
    monkeypatch.setattr(courses, "get_profile", lambda _: {})


def test_public_results_have_safe_links_and_clean_text():
    item = {"bvid": "BV1CAxaeHEeH", "title": '<em class="keyword">物理</em> &amp; 实验',
            "author": "公开讲解", "duration": "135:15", "pic": "//i0.hdslb.com/cover.jpg"}
    rows = search.parse_results([item, item, {**item, "bvid": "javascript:alert(1)"}])
    assert len(rows) == 1
    assert rows[0]["title"] == "物理 & 实验"
    assert rows[0]["duration_seconds"] == 8115
    assert rows[0]["cover_url"] == "https://i0.hdslb.com/cover.jpg"
    assert urlparse(rows[0]["watch_url"]).hostname == "www.bilibili.com"
    assert "verified_at" not in rows[0]
    assert rows[0]["source"] == "bilibili_search"


def test_provider_failure_is_not_an_empty_success_and_is_cached(monkeypatch):
    calls = []
    def blocked(*args, **kwargs):
        calls.append(kwargs)
        raise requests.HTTPError("412")
    monkeypatch.setattr(search.requests, "get", blocked)
    assert search.search_bilibili("摄影入门")["status"] == "unavailable"
    assert search.search_bilibili("摄影入门")["cached"]
    assert len(calls) == 1
    assert calls[0]["allow_redirects"] is False


@pytest.mark.parametrize("query", ["量子力学", "摄影入门", "世界历史", "音乐理论", "机器学习", "经济学"])
def test_arbitrary_subject_search_overrides_current_course_and_kp(query, monkeypatch):
    received = []
    monkeypatch.setattr(courses, "is_demo", lambda: False)
    monkeypatch.setattr(courses, "current_space", lambda: {"course": {"kind": "cet6", "title": "英语六级"}})
    def live(value):
        received.append(value)
        return {"status": "ok", "cached": False, "items": search.parse_results([
            {"bvid": "BV1CAxaeHEeH", "title": query + "课程"}])}
    monkeypatch.setattr(courses, "search_bilibili", live)
    result = courses.recommend("test", query, kp="complexity", topic="旧主题" * 300)
    assert received == [query]
    assert result["items"][0]["title"] == query + "课程"
    assert parse_qs(urlparse(result["search_url"]).query)["keyword"] == [query]


@pytest.mark.parametrize("query", ["英语六级", "CET-6", "Python 入门", "高数"])
def test_verified_courses_survive_search_outage(query, monkeypatch):
    monkeypatch.setattr(courses, "is_demo", lambda: False)
    monkeypatch.setattr(courses, "search_bilibili", lambda _: {"status": "unavailable", "cached": False, "items": []})
    result = courses.recommend("test", query)
    assert result["items"]
    assert result["search_status"] == "unavailable"
    assert all(item["source"] == "curated_catalog" for item in result["items"])


def test_youtube_selection_never_returns_bilibili_results(monkeypatch):
    monkeypatch.setattr(courses, "is_demo", lambda: False)
    def unexpected(_):
        raise AssertionError("YouTube filter must not run Bilibili search")
    monkeypatch.setattr(courses, "search_bilibili", unexpected)
    result = courses.recommend("test", "algorithms", platform="youtube")
    assert result["items"] and all(item["platform"] == "youtube" for item in result["items"])


def test_scoped_python_recommendations_do_not_disappear(monkeypatch):
    monkeypatch.setattr(courses, "current_space", lambda: {"course": {"kind": "python", "title": "Python 入门"}})
    result = courses.recommend("test")
    assert result["items"] and all(item.get("course_kind") == "python" for item in result["items"])
