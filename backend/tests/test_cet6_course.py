"""CET-6 course contracts: real audio, scoped evidence and limited assessment."""
import asyncio
import hashlib
import json
import struct
import wave
from pathlib import Path

from app.data.cet6_course import build_course, LESSONS, GUIDE_URL
from app.services.learning_scope import course_scope, selected_sources
from app.services.textbook_service import course_textbook_chunks
from tests.test_learning_spaces import learner, prepare, finish  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]


def test_original_bank_and_audio_are_complete_and_match_pinned_scripts():
    course = build_course()
    assert len(course["bank"]) == 18 and len(course["practice_bank"]) == 54
    assert not course["graph"]["edges"]  # No artificial chain across English skills.
    questions = course["bank"] + course["practice_bank"]
    assert len({q["id"] for q in questions}) == len({q["stem"] for q in questions}) == 72
    for kp in LESSONS:
        assert sum(q["kp"] == kp for q in course["bank"]) == 3
        assert sum(q["kp"] == kp for q in course["practice_bank"]) == 9
    for q in questions:
        assert len(set(q["options"])) == 4
        assert all(k in "ABCD" for k in q["answer"])
        assert q["explain"] and q["citations"]
    manifest = {item["id"]: item for item in json.loads((ROOT / "backend/app/data/cet6_audio_manifest.json").read_text(encoding="utf-8"))}
    audio_questions = [q for q in questions if q.get("audio_url")]
    assert len(audio_questions) == len(manifest) == 12
    for q in audio_questions:
        file = ROOT / "frontend/public" / q["audio_url"].lstrip("/")
        meta = manifest[q["id"]]
        assert hashlib.sha256(file.read_bytes()).hexdigest() == meta["audio_sha256"]
        assert hashlib.sha256(q["transcript"].encode()).hexdigest() == meta["transcript_sha256"]
        with wave.open(str(file)) as audio:
            assert audio.getnchannels() == 1 and audio.getsampwidth() == 2
            assert 8 < audio.getnframes() / audio.getframerate() < 40
            pcm = audio.readframes(audio.getnframes())
            samples = struct.unpack(f"<{len(pcm)//2}h", pcm)
            assert sum(s*s for s in samples) / len(samples) > 10000  # Audible waveform, not silent placeholder.
    guide = (ROOT / "docs/courses/cet6-guide-v1.md").read_text(encoding="utf-8")
    assert all(lesson in guide for lesson in LESSONS.values())
    import html
    public = (ROOT / "frontend/public/courses/cet6-guide-v1.html").read_text(encoding="utf-8")
    assert all(html.escape(lesson.split("\n\n")[0]) in public for lesson in LESSONS.values())
    assert all(f'id="{s["id"]}"' in public for s in course["textbook"]["sections"])
    assert all(c["course"] == "cet6" for c in course_textbook_chunks(course))


def test_cet6_catalogue_diagnostic_and_plan_are_course_specific(learner):
    client, user = learner
    catalogue = client.get("/api/notebooks/learning/catalogue").json()["items"]
    assert any(item["id"] == "cet6" and "18" in item["description"] for item in catalogue)
    book, survey, course = prepare(client, user, "cet6", "大学英语六级", "准备课程考试")
    survey.update(barriers=["listening", "expression"], study_days=[1, 2, 3, 4, 5, 6, 7], daily_minutes=30)
    assert course["kind"] == "cet6" and course["exam_reference"]["total_minutes"] == 130
    assert "practice_bank" not in course and "evidence" not in course
    state = finish(client, survey, False)
    assert state["report"]["coverage"] == 6
    assert "不预测六级分数" in state["report"]["boundary"]
    assert "完整输出能力" in state["report"]["boundary"]
    tasks = [t for d in state["plan"]["days"] for t in d["tasks"]]
    assert all(t["kp"].startswith("cet6_") for t in tasks)
    assert all(d["minutes"] <= d["capacity"] <= 30 for d in state["plan"]["days"])
    assert "完整听一遍" in " ".join(next(t for t in tasks if t["kp"] == "cet6_listening")["steps"])
    assert any("文字稿" in s for s in state["plan"]["adaptations"])
    assert len(state["materials"]) == 6
    assert any("120–150" in m["markdown"] for m in state["materials"])
    with course_scope(user, book["id"]):
        from app.rag.retriever import retrieve
        hits = retrieve("however 转折 听力", user_id=user, kp="cet6_listening", source_ids=selected_sources([]))
        assert hits and all(h["course"] == "cet6" and h["url"].startswith(GUIDE_URL) for h in hits)
        assert retrieve("return None", user_id=user, kp="py_functions") == []


def test_skipped_listening_is_unmeasured_and_transcripts_are_deferred(learner):
    client, user = learner
    _, survey, _ = prepare(client, user, "cet6", "大学英语六级")
    survey["target_kps"] = ["cet6_listening"]
    state = client.post("/api/assessment/start", json={"survey": survey, "mode": "comprehensive"}).json()
    while state["question"]:
        question = state["question"]
        assert question["audio_url"].endswith(".wav")
        assert "transcript" not in question and "answer" not in question and "explain" not in question
        state = client.post(f"/api/assessment/{state['id']}/answers", json={"revision": state["revision"],
            "question_id": question["id"], "status": "skipped"}).json()
    assert state["report"]["skills"][0]["status"] == "unmeasured"
    assert state["report"]["skills"][0]["attempts"] == 0
    assert "听力文字稿" in state["report"]["explanations"][0]["explain"]


def test_fresh_listening_scoring_resume_and_delay_preserve_baseline(learner):
    client, user = learner
    book, survey, _ = prepare(client, user, "cet6", "大学英语六级")
    state = finish(client, survey, False)
    bank = {q["id"]: q for q in build_course()["practice_bank"]}
    for i in range(3):
        new = client.post(f"/api/assessment/{state['id']}/practice", json={"kp": "cet6_listening"}).json()
        q = new["question"]
        assert new["status"] == "active" and "transcript" not in q and "code" not in q
        payload = {"question_id": q["id"], "choice": bank[q["id"]]["answer"], "assisted": False}
        saved = client.post(f"/api/assessment/{state['id']}/practice/answers", json=payload)
        assert saved.status_code == 200, saved.text
        result = saved.json()
        assert result["result"]["transcript"] == bank[q["id"]]["transcript"]
        assert result["assessment"]["report"] == state["report"]
        retry = client.post(f"/api/assessment/{state['id']}/practice/answers", json=payload)
        assert retry.json()["result"] == result["result"]
    assert result["assessment"]["learning_progress"]["cet6_listening"]["independent"] == 3
    assert client.post(f"/api/assessment/{state['id']}/practice", json={"kp": "cet6_listening"}).json()["status"] == "scheduled"
    restored = client.get(f"/api/assessment?notebook_id={book['id']}").json()["assessment"]
    assert restored["learning_progress"]["cet6_listening"]["next_due_at"]
    # A correct choice cannot silently mark the actual writing task complete.
    for _ in range(3):
        q = client.post(f"/api/assessment/{state['id']}/practice", json={"kp": "cet6_writing"}).json()["question"]
        result = client.post(f"/api/assessment/{state['id']}/practice/answers", json={"question_id": q["id"], "choice": bank[q["id"]]["answer"]}).json()
    tasks = [t for d in result["assessment"]["plan"]["days"] for t in d["tasks"]] + result["assessment"]["plan"]["deferred"]
    assert all(not t["done"] for t in tasks if t["kp"] == "cet6_writing")


def test_generated_explanation_receives_english_scope_and_real_guide(learner, monkeypatch):
    from app.agents import doc_agent
    from app.services.knowledge_graph import resolve_conversation_topic
    client, user = learner
    book, survey, _ = prepare(client, user, "cet6", "大学英语六级", "准备课程考试")
    finish(client, survey, False)
    prompts = []
    async def model(prompt, **kwargs):
        prompts.append(prompt)
        return "# 六级阅读\n\n看到相关关系时不能直接判断因果，需要检查其他解释。[^1]"
    async def grounding(*args, **kwargs):
        return {"grounded": True, "unsupported": [], "verdict": "test"}
    monkeypatch.setattr(doc_agent, "llm_complete", model)
    monkeypatch.setattr(doc_agent, "grounding_check", grounding)
    monkeypatch.setattr(doc_agent, "is_demo", lambda: False)
    goal = "请依据六级指南，解释阅读中为什么不能把相关当因果。"
    with course_scope(user, book["id"]):
        kp, topic, custom = resolve_conversation_topic(goal, knowledge_points=["cet6_reading"], topic_label="仔细阅读与推断")
        resource = asyncio.run(doc_agent._gen_one("doc", kp, {}, topic_name=topic, custom_topic=custom,
            source_ids=selected_sources([]), goal=goal, prompt_template="complete_notes", user_id=user,
            trace_id="cet6-test", skip_multimodal=True))["resource"]
    assert prompts and "Students who joined the reading club" in prompts[0]
    assert "准备课程考试" in prompts[0] and "20" in prompts[0]
    assert resource["citations"] and all("cet6-guide-v1" in c for c in resource["citations"])
    assert resource["payload"]["source_evidence"]
