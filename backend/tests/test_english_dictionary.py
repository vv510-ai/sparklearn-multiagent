"""Dictionary provenance is local, bounded, and independent of generated claims."""
import asyncio
from copy import deepcopy
import json
import re
from urllib.parse import parse_qs, urlparse

import pytest

from app.services import english_dictionary as dictionary
from app.services import english_learning as english
from app.api import learning
from tests.test_english_generation import SCENE
from tests.test_learning_spaces import learner  # noqa: F401


def test_snapshot_has_exact_pilot_coverage_and_attributed_original_senses():
    catalog = dictionary._catalog()
    assert set(catalog["entries"]) == {"hesitate", "awkward", "figure out", "recommend", "instead", "take away", "follow up", "clarify", "deadline"}
    for word in catalog["entries"]:
        found = dictionary.lookup(word)
        assert found["headword"] == word and found["status"] == "included"
        assert found["license"] == "CC BY-SA 4.0"
        assert found["retrieved_at"].startswith("2026-09-26T")
        assert re.fullmatch(r"[a-f0-9]{64}", found["source_sha256"])
        assert urlparse(found["source_url"]).hostname == "en.wiktionary.org"
        assert urlparse(found["extraction_url"]).hostname == "kaikki.org"
        assert found["license_url"] == "https://creativecommons.org/licenses/by-sa/4.0/"
        assert found["senses"] and all(s["definition"] and s["pos"] for s in found["senses"])
        assert "不代表上方 AI 解释已核验" in found["notice"]
    assert dictionary.lookup("figure out")["senses"][0]["definition"] == "To come to understand; to discover or find a solution; to deduce."
    assert dictionary.lookup("deadline")["senses"][0]["definition"] == "A time limit in the form of a date on or before which something must be completed."


def test_lookup_normalizes_spacing_without_guessing_inflection_and_copies_results():
    result = dictionary.lookup("  FIGURE   out ")
    assert result["headword"] == "figure out"
    result["senses"][0]["definition"] = "changed by caller"
    assert dictionary.lookup("figure out")["senses"][0]["definition"] != "changed by caller"
    assert dictionary.lookup("figured out")["status"] == "not_included"


def test_unknown_is_not_a_verified_link_and_query_cannot_change_host_or_parameters():
    word = "hello&search=wrong#https://evil.test/"
    result = dictionary.lookup(word)
    assert result["status"] == "not_included" and "source_url" not in result
    parsed = urlparse(result["search_url"])
    assert parsed.hostname == "en.wiktionary.org"
    assert parse_qs(parsed.query) == {"title": ["Special:Search"], "search": [word]}


@pytest.mark.parametrize("content", [None, "not JSON", "[]"])
def test_missing_or_broken_snapshot_does_not_break_learning(tmp_path, monkeypatch, content):
    file = tmp_path / "dictionary.json"
    if content is not None:
        file.write_text(content, encoding="utf-8")
    monkeypatch.setattr(dictionary, "CATALOG", file)
    dictionary._catalog.cache_clear()
    try:
        result = dictionary.with_sources(deepcopy(SCENE))
        assert result["lines"] == SCENE["lines"]
        assert result["question"] == SCENE["question"]
        assert result["vocabulary"][0]["dictionary"]["status"] == "not_included"
    finally:
        dictionary._catalog.cache_clear()


def test_model_cannot_claim_verified_sources_and_archive_preserves_attribution(monkeypatch):
    data = deepcopy(SCENE)
    data["vocabulary"][0]["dictionary"] = {"status": "verified", "source_url": "https://forged.test"}
    async def complete(*args, **kwargs):
        return json.dumps(data)
    monkeypatch.setattr(english, "llm_complete", complete)
    values = {"words": "figure out", "scene": "周末", "goal": "交流", "level": "中等", "subtitles": ""}
    scene = asyncio.run(english.generate_scene(values))
    evidence = scene["vocabulary"][0]["dictionary"]
    assert evidence["status"] == "included" and "forged" not in evidence["source_url"]
    archive = english.archive(scene)
    assert evidence["senses"][0]["definition"] in archive["markdown"]
    for expected in ["AI 解释", "Wiktionary contributors", "CC BY-SA 4.0", evidence["source_url"], evidence["extraction_url"], evidence["version"]]:
        assert expected in archive["markdown"]
    assert "forged.test" not in archive["markdown"]


def test_question_retry_does_not_send_dictionary_text_or_source_urls(monkeypatch):
    scene = dictionary.with_sources(deepcopy(SCENE))
    async def complete(prompt, **kwargs):
        assert "kaikki.org" not in prompt
        assert "To come to understand; to discover" not in prompt
        assert "figure out a plan" in prompt
        return json.dumps(SCENE["question"])
    monkeypatch.setattr(english, "llm_complete", complete)
    asyncio.run(english.generate_question(scene))


def test_legacy_scene_view_adds_sources_without_mutating_stored_content(learner, monkeypatch):
    from app.models.db import session
    from app.models.entities import Resource
    client, user = learner
    notebook = client.post("/api/notebooks", json={"user_id": user, "title": "旧英语场景"}).json()["id"]
    legacy = {**deepcopy(SCENE), "provenance": "原创教学场景", "mode": "live"}
    resource_id = learning._persist(user, notebook, legacy["title"], {"template": "english_scene", "english_scene": legacy, "markdown": "old archive"})
    response = client.get("/api/learning/english/scene/latest", params={"notebook_id": notebook})
    assert response.status_code == 200
    result = response.json()
    assert result["vocabulary"][0]["dictionary"]["status"] == "included"
    assert result["lines"] == legacy["lines"] and result["question"] == legacy["question"]
    with session() as db:
        payload = db.get(Resource, resource_id).payload
        assert payload["markdown"] == "old archive"
        assert "dictionary" not in payload["english_scene"]["vocabulary"][0]
