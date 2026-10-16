"""BKT⁺: contextual guess/slip, support-aware evidence and forgetting."""
import datetime as dt

from app.services import bkt


def test_default_update_is_unchanged_standard_bkt():
    assert bkt.bkt_update_plus(0.3, True) == bkt.bkt_update(0.3, True)
    assert bkt.bkt_update_plus(0.3, False) == bkt.bkt_update(0.3, False)


def test_easy_to_guess_items_give_weaker_evidence():
    judge = bkt.bkt_update_plus(0.3, True, item_type="judge")
    single = bkt.bkt_update_plus(0.3, True, item_type="single", options=4)
    fill = bkt.bkt_update_plus(0.3, True, item_type="fill")
    assert judge < single < fill


def test_a_hinted_success_counts_less_than_an_independent_one():
    assert bkt.bkt_update_plus(0.3, True, item_type="fill", support="hinted") < bkt.bkt_update_plus(0.3, True, item_type="fill")


def test_forgetting_decays_toward_the_prior_and_slows_with_practice():
    assert bkt.forget(0.95, 0.01) == 0.95  # same session: no decay
    once = bkt.forget(0.95, 14, independent_correct=0)
    practised = bkt.forget(0.95, 14, independent_correct=4)
    assert bkt.FORGET_FLOOR < once < practised < 0.95
    assert abs(bkt.forget(0.95, 7, 0) - (0.3 + 0.65 / 2)) < 1e-3  # one half-life
    assert bkt.forget(0.2, 30) == 0.2  # never pushed below what was measured


def test_predicted_correct_combines_slip_and_guess():
    assert bkt.predicted_correct(1.0) == 0.9 and bkt.predicted_correct(0.0) == 0.2


def test_update_mastery_records_trace_and_applies_decay(monkeypatch):
    from app.services import profile_service as profiles
    state = {"knowledge_mastery": {"stack": 0.9}, "knowledge_trace": {}}

    def get_profile(user_id):
        return {"knowledge_mastery": dict(state["knowledge_mastery"]), "knowledge_trace": dict(state["knowledge_trace"])}

    def merge(user_id, patch):
        clean = profiles.sanitize_profile_patch(patch)
        state["knowledge_mastery"].update(clean.get("knowledge_mastery", {}))
        state["knowledge_trace"].update(clean.get("knowledge_trace", {}))
        return get_profile(user_id)

    monkeypatch.setattr(profiles, "get_profile", get_profile)
    monkeypatch.setattr(profiles, "merge_profile", merge)
    start = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
    profiles.update_mastery("u", "stack", True, item_type="fill", at=start)
    trace = state["knowledge_trace"]["stack"]
    assert trace["independent_correct"] == 1 and trace["attempts"] == 1
    state["knowledge_mastery"]["stack"] = 0.95
    after_month = profiles.update_mastery("u", "stack", False, item_type="fill", at=start + dt.timedelta(days=30))
    same_session = bkt.bkt_update_plus(0.95, False, item_type="fill")
    assert after_month < same_session  # a month away weakens the same evidence further


def test_path_reopens_faded_knowledge_and_prefers_the_zone_of_proximal_development():
    from app.services.path_service import plan_path
    from app.services.profile_service import default_profile
    now = dt.datetime(2026, 11, 1, tzinfo=dt.timezone.utc)
    profile = default_profile()
    profile["knowledge_mastery"].update({"complexity": 0.95, "array": 0.9})
    profile["knowledge_trace"] = {
        "complexity": {"last": (now - dt.timedelta(days=40)).isoformat(), "independent_correct": 0, "attempts": 3},
        "array": {"last": (now - dt.timedelta(hours=2)).isoformat(), "independent_correct": 5, "attempts": 6},
    }
    path = plan_path(profile, now=now)
    by = {node["id"]: node for node in path["nodes"]}
    assert by["array"]["status"] == "done"                      # practised recently and often
    assert by["complexity"]["status"] == "ready"                # mastered once, faded after 40 days
    assert by["complexity"]["recorded_mastery"] == 0.95 and by["complexity"]["mastery"] < 0.8
    assert "淡化" in by["complexity"]["reason"]
    assert path["algorithm"] == "bkt_plus_forgetting_zpd_v1"
    assert 0 <= by["complexity"]["predicted_correct"] <= 1
