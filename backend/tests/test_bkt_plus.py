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
