"""Clicking inflected text must find real lemmas, not substring coincidences."""
import uuid

import pytest

from app.services import cet6_word_lookup as lookup
from tests.test_cet6_learning import setup, word_action
from tests.test_learning_spaces import learner  # noqa: F401
from tests.test_exam_reading_loop import context


@pytest.mark.parametrize("surface,headword", [
    ("stopped", "stop"), ("stopping", "stop"), ("studies", "study"), ("studied", "study"),
    ("studying", "study"), ("children", "child"), ("Children’s", "child"), ("students'", "student"),
    ("went", "go"), ("gone", "go"), ("written", "write"), ("bought", "buy"), ("took", "take"),
    ("was", "be"), ("were", "be"), ("am", "be"), ("are", "be"), ("does", "do"),
    ("has", "have"), ("lied", "lie"), ("organised", "organise"), ("ORGANIZED", "organize"),
])
def test_real_inflections_reach_headword(surface, headword):
    assert headword in {m["word"] for m in lookup.resolve(surface)}


def test_ambiguity_is_preserved_without_substring_or_derivational_guessing():
    assert {m["word"] for m in lookup.resolve("saw")} == {"see", "saw"}
    assert {m["word"] for m in lookup.resolve("better")} >= {"good", "well", "better"}
    assert {m["word"] for m in lookup.resolve("leaves")} >= {"leaf", "leave"}
    assert "organize" not in {m["word"] for m in lookup.resolve("organization")}
    assert not lookup.resolve("qzxqzx")
    assert not lookup.resolve("stoppedd")
    assert "twenty" not in {m["word"] for m in lookup.resolve("went")}
    assert "it" not in {m["word"] for m in lookup.resolve("it's")}


@pytest.mark.parametrize("surface,headword,code", [("rose", "rise", "p"), ("rang", "ring", "p"),
    ("ate", "eat", "p"), ("broke", "break", "p"), ("rung", "ring", "d"), ("sung", "sing", "d"), ("drunk", "drink", "d")])
def test_irregular_tenses_do_not_merge_noisy_reverse_labels(surface, headword, code):
    match = next(m for m in lookup.resolve(surface) if m["word"] == headword)
    assert match["codes"] == [code]


def test_word_boundaries_preserve_possessives_but_not_substrings():
    assert lookup.contains_form("The students' work improved.", "students'")
    assert lookup.contains_form("The students’ work improved.", "students'")
    assert lookup.contains_form("They said 'stopped'.", "stopped")
    assert not lookup.contains_form("They are stopping.", "stop")
    assert not lookup.contains_form("Children's games", "children")


def test_lookup_endpoint_resolves_forms_preserves_choices_and_checks_ownership(learner):
    client, _, _, base = setup(learner)
    def find(q, sentence=""):
        response = client.get(base + "/word-lookup", params={"q": q, "context": sentence})
        assert response.status_code == 200, response.text
        return response.json()
    stopped = find("stopped", "That doesn't mean it should be stopped.")
    assert stopped["status"] == "matched" and stopped["auto_entry_id"]
    assert stopped["matches"][0]["word"] == "stop"
    assert set(stopped["matches"][0]["forms"]) == {"过去式", "过去分词"}
    assert "被动" in stopped["usage_hint"]
    assert find("stopped", "She stopped yesterday.")["usage_hint"] == ""
    assert find("saw")["auto_entry_id"] is None
    assert find("better")["auto_entry_id"] is None
    well = next(m for m in find("better")["matches"] if m["word"] == "well")
    assert "井" not in well["meaning"] and "adv." in well["meaning"]
    stopped_detail = client.get(base + "/words/" + stopped["auto_entry_id"]).json()
    suggested = stopped["matches"][0]["suggested_sense_id"]
    assert next(s for s in stopped_detail["entry"]["senses"] if s["id"] == suggested)["definition"].startswith("vt.")
    assert find("qzxqzx")["status"] == "not_found"
    assert "qzxqzx" in find("qzxqzx")["dictionary_url"]
    assert find("organize")["status"] == "matched"
    # The catalogue also accepts inflections while keeping its browsing filters.
    assert client.get(base + "/words", params={"q": "went"}).json()["items"][0]["word"] == "go"
    foreign = client.post("/api/auth/register", json={"email": f"forms-{uuid.uuid4().hex}@example.test", "password": "Form-Password-2026!", "name": "其他学生"}).json()
    client.headers["Authorization"] = f"Bearer {foreign['access_token']}"
    assert client.get(base + "/word-lookup", params={"q": "stopped"}).status_code == 404


def test_inflected_excerpts_share_card_and_keep_original_forms(learner):
    client, _, _, base = setup(learner)
    match = client.get(base + "/word-lookup", params={"q": "stopped"}).json()
    detail = client.get(base + "/words/" + match["auto_entry_id"]).json()
    excerpt = context(client, base) | {"context": "That doesn't mean it should be stopped.", "surface_form": "stopped"}
    card, _ = word_action(client, base, detail, detail["cards"][0], "collect", **excerpt)
    first_due = card["queued_at"]
    assert card["contexts"][0]["surface_form"] == "stopped"
    second = excerpt | {"context": "They are stopping the car.", "surface_form": "stopping"}
    card, _ = word_action(client, base, detail, card, "collect", **second)
    assert {c["surface_form"] for c in card["contexts"]} == {"stopped", "stopping"}
    assert card["queued_at"] == first_due and card["tracks"] == {}
    assert client.get(base + "/word-plan").json()["review_due"] == 1
    card, _ = word_action(client, base, detail, card, "collect", **(second | {"context_note": "修改笔记"}))
    assert len(card["contexts"]) == 2 and card["contexts"][-1]["note"] == "修改笔记"
    for patch in ({"surface_form": "went"}, {"context": "There is no matching word."}):
        body = dict(action="collect", revision=card["revision"], request_id=str(uuid.uuid4()), version=detail["version"],
                    sense_id=card["sense_id"], **(excerpt | patch))
        assert client.post(base + "/words/" + detail["entry"]["id"], json=body).status_code == 422
    restored = client.get(base + "/words/" + detail["entry"]["id"]).json()["cards"][0]
    assert restored == card


def test_same_sentence_can_accumulate_forms_and_upgrade_legacy_context(learner):
    client, _, _, base = setup(learner)
    match = client.get(base + "/word-lookup", params={"q": "stopped"}).json()
    detail = client.get(base + "/words/" + match["auto_entry_id"]).json()
    excerpt = context(client, base) | {"context": "He stopped yesterday but is stopping today."}
    card, _ = word_action(client, base, detail, detail["cards"][0], "collect", **excerpt)
    queued = card["queued_at"]
    for surface in ("stopped", "stopping", "stopped"):
        card, _ = word_action(client, base, detail, card, "collect", **(excerpt | {"surface_form": surface}))
    assert len(card["contexts"]) == 1
    assert card["contexts"][0]["surface_forms"] == ["stopped", "stopping"]
    assert card["queued_at"] == queued and card["tracks"] == {}
