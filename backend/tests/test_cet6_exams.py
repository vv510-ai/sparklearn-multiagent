"""Real API boundaries: pinned answers, immutable attempts, isolation and model failures."""
import copy
import json
import uuid

import pytest

from app.models.db import session
from app.models.entities import Cet6PaperAttempt
from app.services import cet6_exams as exams
from tests.test_cet6_learning import setup
from tests.test_learning_spaces import learner, prepare  # noqa: F401

PAPER = "cet6-2026-06-1"


def action(state, action="save", **changes):
    return dict(user_id="session_user",request_id=str(uuid.uuid4()),revision=state["revision"],version=state["version"],action=action,
                answers=state["answers"],text=state["text"],**changes)


def test_catalogue_does_not_present_unreviewed_sets_or_future_papers_as_ready(learner):
    client,_,_,base=setup(learner)
    result=client.get(base+"/exams").json()
    assert len(result["items"])==15
    assert all(p["ready"] for p in result["items"])
    assert all(p["counts"]["reading_cloze"] == p["counts"]["reading_matching"] == p["counts"]["reading_careful"] == 10 for p in result["items"])
    assert all(p["counts"]["writing"] == p["counts"]["translation"] == 1 for p in result["items"])
    assert [p["id"] for p in result["items"] if p["counts"].get("listening")]==[PAPER]
    assert all(p["year"]<2026 or p["month"]==6 for p in result["items"])
    assert client.get(base+"/exams/cet6-2025-12-1/reading").status_code==404


@pytest.mark.parametrize("paper_id", ["cet6-2024-06-2", "cet6-2024-12-3", "cet6-2025-06-3", "cet6-2025-12-1", "cet6-2026-06-2"])
def test_subtypes_have_independent_records_and_hide_source_answers_until_submission(learner, paper_id):
    client, _, _, base = setup(learner)
    path=base+f"/exams/{paper_id}/reading_cloze"
    state=client.get(path).json()
    assert [q['number'] for q in state['material']['questions']]==list(range(26,36))
    assert 'answer_url' not in state['material']
    body=action(state,'submit',allow_incomplete=True)
    body['answers']={'26':'A'}
    result=client.post(path,json=body).json()
    assert result['first']['total']==10
    assert result['material']['answer_url'].startswith('https://raw.githubusercontent.com/')
    assert all(q['reference_page']>=1 for q in result['material']['questions'])
    matching=client.get(base+f"/exams/{paper_id}/reading_matching").json()
    careful=client.get(base+f"/exams/{paper_id}/reading_careful").json()
    assert matching['phase']==careful['phase']=='answer'
    assert matching['answers']==careful['answers']=={}
    invalid=action(matching);invalid['answers']={'26':'A'}
    assert client.post(base+f"/exams/{paper_id}/reading_matching",json=invalid).status_code==422


def test_reviewed_source_conflicts_are_bound_to_the_displayed_edition():
    from app.data.cet6_exam_catalogue import catalogue_data
    papers=catalogue_data()
    expected=[('cet6-2024-12-3','reading_cloze',32,'G'),('cet6-2025-06-3','reading_cloze',34,'O'),
        ('cet6-2025-12-1','reading_cloze',30,'E'),('cet6-2025-12-1','reading_careful',50,'B'),
        ('cet6-2025-12-1','reading_careful',53,'C'),('cet6-2026-06-2','reading_careful',54,'B')]
    for p,k,n,key in expected:
        q=next(q for q in papers[p]['blocks'][k]['questions'] if q['number']==n)
        assert q['answer']==key and len(q['explanation'])>50
    assert '人工智能' in papers['cet6-2025-06-1']['blocks']['writing']['rubric']
    assert '南水北调' in papers['cet6-2025-06-3']['blocks']['translation']['rubric']


@pytest.mark.parametrize("kind,count",[("listening",25),("reading",30)])
def test_complete_section_hides_answers_and_preserves_partial_submit_and_retries(learner,kind,count):
    client,_,_,base=setup(learner)
    path=base+f"/exams/{PAPER}/{kind}"
    first=client.get(path).json()
    questions=first["material"]["questions"]
    assert len(questions)==count
    assert all(set(q)=={"number","choices","page","group"} for q in questions)
    assert "first" not in first and "crosscheck_url" not in first["material"]
    body=action(first);body["answers"]={str(questions[0]["number"]):"A"}
    saved=client.post(path,json=body).json()
    assert client.post(path,json=body).json()["revision"]==saved["revision"]
    reused={**body,"answers":{str(questions[0]["number"]):"B"}}
    assert client.post(path,json=reused).status_code==409
    submit=action(saved,"submit")
    assert client.post(path,json=submit).status_code==422
    assert client.get(path).json()["phase"]=="answer"
    submit["allow_incomplete"]=True
    result=client.post(path,json=submit)
    assert result.status_code==200,result.text
    submitted=result.json()
    assert submitted["phase"]=="feedback"
    assert submitted["first"]["total"]==count and submitted["first"]["answered"]==1
    assert client.post(path,json=submit).json()["revision"]==submitted["revision"]
    assert client.post(path,json=action(submitted)).status_code==409
    assert all(set(q["option_reasons"])==set(q["choices"]) and q["tip"] and q["location"] for q in submitted["material"]["questions"])
    restarted=client.post(path,json=action(submitted,"restart")).json()
    assert restarted["phase"]=="answer" and restarted["answers"]=={}
    assert restarted["history_count"]==1 and "first" not in restarted
    assert all("answer" not in q for q in restarted["material"]["questions"])


def test_bound_pdf_key_and_cross_section_answers(learner):
    client,_,_,base=setup(learner)
    path=base+f"/exams/{PAPER}/listening"
    state=client.get(path).json()
    body=action(state,"submit",allow_incomplete=True)
    # Q18 is B in the pinned PDF, C on the cross-check website.
    body["answers"]={"18":"B"}
    result=client.post(path,json=body).json()
    assert result["first"]["correct"]==1
    question=next(q for q in result["material"]["questions"] if q["number"]==18)
    assert question["answer"]=="B" and "汞" in question["option_reasons"]["B"]
    other=base+f"/exams/{PAPER}/reading"
    other_state=client.get(other).json()
    invalid=action(other_state);invalid["answers"]={"18":"B"}
    assert client.post(other,json=invalid).status_code==422
    invalid["answers"]={"55":"E"}
    assert client.post(other,json=invalid).status_code==422
    invalid["answers"]={"55":"D"};invalid["version"]="unknown"
    assert client.post(other,json=invalid).status_code==409


def test_all_reading_answers_agree_with_reviewed_source_and_gaps_remain_wrong(learner):
    client,_,_,base=setup(learner)
    path=base+f"/exams/{PAPER}/reading"
    state=client.get(path).json()
    body=action(state,"submit")
    key="J I D C F K B G A E D I F K B H L E M J A B C D A C B A D D".split()
    body["answers"]={str(i+26):a for i,a in enumerate(key)}
    result=client.post(path,json=body)
    assert result.status_code==200,result.text
    assert result.json()["first"]["correct"]==30
    by_number={q["number"]:q for q in result.json()["material"]["questions"]}
    assert by_number[36]["page"]==9 and by_number[36]["evidence_page"]==7
    assert by_number[46]["evidence_page"]==10 and by_number[55]["evidence_page"]==13


def test_stale_writer_and_foreign_course_cannot_overwrite(learner):
    client,user,book,base=setup(learner)
    path=base+f"/exams/{PAPER}/writing"
    first=client.get(path).json()
    a=action(first);a["text"]="My own draft remains available."
    saved=client.post(path,json=a)
    assert saved.status_code==200
    b=action(first);b["text"]="Stale page must not replace the newer draft."
    assert client.post(path,json=b).status_code==409
    assert client.get(path).json()["text"]==a["text"]
    other,_,_=prepare(client,user,"python","Python")
    assert client.get(f"/api/notebooks/{other['id']}/cet6/exams").status_code==404
    client.headers.pop("Authorization",None)
    assert client.get(path).status_code==401
    account=client.post("/api/auth/register",json={"email":f"exam-{uuid.uuid4().hex}@example.test","password":"Exam-Isolation-2026!","name":"另一位用户"}).json()
    client.headers["Authorization"]="Bearer "+account["access_token"]
    assert client.get(path).status_code==404
    assert client.post(path,json=a).status_code==404


def submitted_translation(learner):
    client,user,book,base=setup(learner)
    path=base+f"/exams/{PAPER}/translation"
    state=client.get(path).json()
    body=action(state,"submit");body["text"]="Technology improve medical care. Doctors can help patients in remote areas."
    result=client.post(path,json=body)
    assert result.status_code==200,result.text
    return client,user,book,path,result.json()


def model_reply(quote="Technology improve medical care."):
    return {"summary":"原稿表达了医疗发展和远程医疗，但若干原文信息尚未覆盖。", "strengths":["提到了远程地区患者。"],
        "priorities":["检查单数主语的谓语形式，再补齐人工智能、健康档案与线上咨询信息。"],
        "dimensions":[{"name":name,"comment":"请结合原题信息逐项检查这份原稿。"} for name in exams.pilot()["blocks"]["translation"]["dimensions"]],
        "suggestions":[{"quote":quote,"replacement":"Technology improves medical care.","reason":"单数主语需要第三人称单数谓语形式。"}]}


def test_model_feedback_is_cached_and_cites_actual_learner_text(learner,monkeypatch):
    client,_,_,path,first=submitted_translation(learner)
    monkeypatch.setattr(exams,"is_demo",lambda:False)
    calls=[]
    async def complete(prompt,**kwargs):
        calls.append((prompt,kwargs));return json.dumps(model_reply())
    monkeypatch.setattr(exams,"llm_complete",complete)
    reviewed=client.post(path+"/review").json()
    assert reviewed["review"]["status"]=="ready"
    assert reviewed["first"]==first["first"]
    assert calls[0][1]["allow_mock_fallback"] is False
    assert calls[0][1]["max_tokens"] == 10000
    assert client.post(path+"/review").json()["review"]["status"]=="ready" and len(calls)==1


@pytest.mark.parametrize("failure",["invented_quote","provider_error","wrong_rubric","truncated","timeout"])
def test_invalid_model_output_never_becomes_feedback_and_original_is_retained(learner,monkeypatch,failure):
    client,_,_,path,first=submitted_translation(learner)
    monkeypatch.setattr(exams,"is_demo",lambda:False)
    async def complete(*args,**kwargs):
        if failure=="provider_error":raise RuntimeError("synthetic provider failure")
        if failure=="truncated":raise exams.ModelFailure("truncated")
        if failure=="timeout":raise TimeoutError()
        value=model_reply("A sentence absent from the original." if failure=="invented_quote" else "Technology improve medical care.")
        if failure=="wrong_rubric":value["dimensions"][0]["name"]="unrelated"
        return json.dumps(value)
    monkeypatch.setattr(exams,"llm_complete",complete)
    response=client.post(path+"/review").json()
    assert response["review"]["status"]=="failed" and "content" not in response["review"]
    if failure in {"truncated","timeout"}:
        assert response["review"]["reason_code"]==failure
    assert client.get(path).json()["first"]==first["first"]


def test_truncated_feedback_can_retry_without_replacing_the_first_answer(learner,monkeypatch):
    client,_,_,path,first=submitted_translation(learner)
    monkeypatch.setattr(exams,"is_demo",lambda:False)
    calls=[]
    async def complete(*args,**kwargs):
        calls.append(1)
        if len(calls)==1:raise exams.ModelFailure("truncated")
        return json.dumps(model_reply())
    monkeypatch.setattr(exams,"llm_complete",complete)
    failed=client.post(path+"/review").json()
    assert failed["review"]["reason_code"]=="truncated"
    retried=client.post(path+"/review").json()
    assert retried["review"]["status"]=="ready"
    assert retried["first"]==first["first"]
    assert retried["history_count"]==0


def test_late_model_result_cannot_attach_to_restarted_attempt(learner,monkeypatch):
    client,user,book,path,_=submitted_translation(learner)
    monkeypatch.setattr(exams,"is_demo",lambda:False)
    async def complete(*args,**kwargs):
        with session() as db:
            row=db.get(Cet6PaperAttempt,exams._id(user,book,PAPER,"translation"))
            row.data=exams._initial();row.revision+=1;db.commit()
        return json.dumps(model_reply())
    monkeypatch.setattr(exams,"llm_complete",complete)
    result=client.post(path+"/review").json()
    assert result["phase"]=="answer" and "review" not in result


def test_demo_never_fakes_model_review(learner,monkeypatch):
    client,_,_,path,first=submitted_translation(learner)
    monkeypatch.setattr(exams,"is_demo",lambda:True)
    result=client.post(path+"/review").json()
    assert result["review"]["status"]=="unavailable"
    assert result["first"]==first["first"]
