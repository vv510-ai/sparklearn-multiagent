"""Actual syllabus families, stable preferences, and distinct-word coverage."""
import datetime as dt
import uuid

from app.services import cet6_vocabulary as vocabulary, cet6_word_groups as groups, cet6_learning as learning
from tests.test_cet6_learning import setup, find_word, word_action
from tests.test_cet6_plans_and_papers import introduce
from tests.test_learning_spaces import learner, prepare  # noqa: F401


def set_order(client, base, order, target=20):
    current = client.get(base).json()
    result = client.post(base + "/word-plan", json={"revision": current["revision"],
        "daily_new_words": target, "word_order": order})
    assert result.status_code == 200, result.text
    return result.json()


def test_syllabus_coverage_corrections_and_recall_identity():
    original = vocabulary.corpus()["entries"]
    catalog = vocabulary.entries()
    words = {e["word"]: e for e in catalog.values()}
    assert len(catalog) == 8010 and all(e["senses"] for e in catalog.values())
    assert set(vocabulary.corrections()["aliases"]).isdisjoint(words)
    assert "connexion" in words and "connecxion" not in words
    assert "connecxion" not in words["connection"]["variants"]
    assert {l["row_id"] for e in original for l in e["locators"]} == {
        l["row_id"] for e in catalog.values() for l in e["locators"]}
    assert len({l["row_id"] for e in catalog.values() for l in e["locators"]}) == 5377
    assert all("\\r" not in s["definition"] for e in catalog.values() for s in e["senses"])
    for e in original:
        if e["id"] in catalog:
            assert {s["id"] for s in e["senses"]} <= {s["id"] for s in catalog[e["id"]]["senses"]}
    assert words["a"]["senses"][0]["definition"].startswith("art. 不定冠词")
    assert set(groups.family(words["able"]["id"])["words"]) == {"able", "ability"}
    assert {"connect", "connection", "connexion"} <= set(groups.family(words["connect"]["id"])["words"])


def test_homographs_do_not_bridge_unrelated_syllabus_families():
    catalog = vocabulary.entries()
    words = {e["word"]: e for e in catalog.values()}
    fatigue = set(groups.family(words["tired"]["id"])["words"])
    assert {"tire", "tired", "tiring"} <= fatigue
    assert "tyre" not in fatigue
    assert "tired" not in groups.family(words["tyre"]["id"])["words"]
    for entry_id, family in groups.families().items():
        assert entry_id in family["entry_ids"]
        assert all(family["id"] in {loc["row_id"] for loc in catalog[key]["locators"]}
                   for key in family["entry_ids"])


def test_default_priority_and_family_search_are_syllabus_based(learner):
    client, _, _, base = setup(learner)
    plan = client.get(base + "/word-plan").json()
    assert plan["word_order"] == "priority"
    assert all(vocabulary.entry(key)["level"] == "cet6" for key in plan["new_ids"])
    assert plan["coverage"]["total"] == 8010
    assert plan["coverage"]["priority_total"] == 1724
    detail = find_word(client, base, "able")
    family = detail["family"]
    result = client.get(base + f"/words?order=family&family={family['id']}").json()
    assert {item["word"] for item in result["items"]} == {"able", "ability"}
    assert result["total"] == 2
    alphabetical = client.get(base + "/words?order=alphabetical").json()
    assert alphabetical["items"][0]["word"] == "a"
    assert client.get(base + "/words?order=unsupported").status_code == 422


def test_order_change_preserves_open_round_and_finished_progress(learner):
    client, _, _, base = setup(learner)
    first = set_order(client, base, "alphabetical", 12)
    assert vocabulary.entry(first["new_ids"][0])["word"] == "a"
    response = client.post(base + "/word-rounds", json={"kind": "new", "request_id": str(uuid.uuid4())})
    assert response.status_code == 200, response.text
    opened = response.json()
    ids = [i["entry_id"] for i in opened["items"]]
    introduce(client, base, ids[0])
    family_plan = set_order(client, base, "family", 12)
    assert family_plan["new_done"] == 1 and family_plan["coverage"]["learned"] == 1
    assert family_plan["new_ids"][:4] == ids[1:]
    assert client.get(base + "/word-plan").json()["new_ids"] == family_plan["new_ids"]
    resumed = client.post(base + "/word-rounds", json={"kind": "new", "request_id": str(uuid.uuid4())}).json()
    assert resumed["id"] == opened["id"] and resumed["completed"] == 1
    assert [i["entry_id"] for i in resumed["items"]] == ids
    assert client.get(base).json()["preferences"]["word_order"] == "family"


def test_family_words_stay_adjacent_and_random_plan_survives_refresh(learner):
    client, _, _, base = setup(learner)
    plan = set_order(client, base, "family", 200)
    seen = set()
    previous = None
    for entry_id in plan["new_ids"]:
        group = groups.families()[entry_id]["id"]
        if group != previous:
            assert group not in seen
            seen.add(group)
        previous = group
    assert any(groups.family(i)["total"] > 1 for i in plan["new_ids"])
    random_plan = set_order(client, base, "random", 200)
    assert random_plan["new_ids"] != plan["new_ids"]
    assert len(set(random_plan["new_ids"])) == 200
    assert client.get(base + "/word-plan").json()["new_ids"] == random_plan["new_ids"]


def test_coverage_counts_word_once_and_is_private(learner):
    client, _, _, base = setup(learner)
    key = client.get(base + "/word-plan").json()["new_ids"][0]
    detail, card = introduce(client, base, key)
    first = client.get(base + "/word-plan").json()["coverage"]
    card, _ = word_action(client, base, detail, card, "start", mode="spelling")
    card, _ = word_action(client, base, detail, card, "reveal", answer=detail["entry"]["word"])
    word_action(client, base, detail, card, "rate", rating="good")
    assert client.get(base + "/word-plan").json()["coverage"] == first
    assert first["learned"] == first["priority_learned"] == 1
    assert first["remaining"] == 8009
    other, _, _, other_base = setup(learner)
    assert other.get(other_base + "/word-plan").json()["coverage"]["learned"] == 0
    foreign = client.post("/api/auth/register", json={"email": f"words-{uuid.uuid4().hex}@example.test",
        "password": "Vocab-Other-Password!", "name": "另一位学习者"}).json()
    client.headers["Authorization"] = f"Bearer {foreign['access_token']}"
    assert client.get(base + "/word-plan").status_code == 404
    assert client.get(base + "/words").status_code == 404


def test_stale_order_save_and_next_day_carry(learner, monkeypatch):
    clock = [dt.datetime(2026, 10, 4, 15, 59, tzinfo=dt.timezone.utc)]
    monkeypatch.setattr(learning, "now", lambda: clock[0])
    client, _, _, base = setup(learner)
    plan = set_order(client, base, "family", 10)
    assert client.post(base + "/word-plan", json={"revision": plan["profile_revision"] - 1,
        "daily_new_words": 20, "word_order": "random"}).status_code == 409
    introduce(client, base, plan["new_ids"][0])
    clock[0] += dt.timedelta(minutes=2)
    tomorrow = client.get(base + "/word-plan").json()
    assert tomorrow["day"] == "2026-10-05" and tomorrow["new_done"] == 0
    assert tomorrow["coverage"]["learned"] == 1
    assert tomorrow["new_ids"][:9] == plan["new_ids"][1:]
