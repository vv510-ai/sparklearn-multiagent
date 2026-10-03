import datetime as dt
import uuid

from app.services import cet6_learning as learning
from tests.test_cet6_learning import setup, word_action
from tests.test_learning_spaces import learner, prepare  # noqa: F401


def start(client, base, kind='new', request_id=None):
    response = client.post(base + '/word-rounds', json={'kind':kind,'request_id':request_id or str(uuid.uuid4())})
    assert response.status_code == 200, response.text
    return response.json()


def finish(client, base, item, rating='again'):
    detail = client.get(base + '/words/' + item['entry_id']).json()
    card = next(c for c in detail['cards'] if c['sense_id'] == item['sense_id'])
    card, _ = word_action(client, base, detail, card, 'start', mode=item['mode'])
    card, _ = word_action(client, base, detail, card, 'reveal', mode=item['mode'])
    card, body = word_action(client, base, detail, card, 'rate', mode=item['mode'], rating=rating)
    replay = client.post(base + '/words/' + item['entry_id'], json=body).json()
    assert replay['revision'] == card['revision']


def test_new_round_has_a_fixed_end_despite_relearning_due_and_survives_refresh(learner, monkeypatch):
    current = dt.datetime(2026,10,4,0,0,tzinfo=dt.timezone.utc)
    monkeypatch.setattr(learning, 'now', lambda:current)
    client, _, _, base = setup(learner)
    round = start(client, base)
    assert round['total'] == 5 and round['completed'] == 0
    assert len({i['entry_id'] for i in round['items']}) == 5
    assert start(client, base)['id'] == round['id']
    for index, item in enumerate(round['items']):
        finish(client,base,item)
        current += dt.timedelta(minutes=2)
        progress=client.get(base + '/word-rounds/' + round['id']).json()
        assert progress['total']==5 and progress['completed']==index+1
    assert progress['finished']
    plan=client.get(base+'/word-plan').json()
    assert plan['new_done']==5 and plan['review_due']==5
    review=start(client,base,'review')
    assert review['kind']=='review' and review['total']==5
    assert {i['entry_id'] for i in review['items']}=={i['entry_id'] for i in round['items']}
    another=start(client,base)
    assert another['id']!=round['id'] and another['total']==5
    assert not {i['entry_id'] for i in another['items']} & {i['entry_id'] for i in round['items']}


def test_start_retry_does_not_create_an_extra_round_and_isolates_courses(learner):
    client,user,_,base=setup(learner)
    request=str(uuid.uuid4())
    first=start(client,base,request_id=request)
    for item in first['items']:finish(client,base,item,'good')
    replay=start(client,base,request_id=request)
    assert replay['id']==first['id'] and replay['finished']
    second,_,_=prepare(client,user,'cet6','另一门六级')
    other=f"/api/notebooks/{second['id']}/cet6"
    assert client.get(other+'/word-rounds/'+first['id']).status_code==404
    assert start(client,other)['completed']==0
    assert client.post(base+'/word-rounds',json={'kind':'review','request_id':request}).status_code==409


def test_small_quota_and_zero_quota_do_not_invent_words(learner):
    client,_,_,base=setup(learner)
    plan=client.get(base+'/word-plan').json()
    changed=client.post(base+'/word-plan',json={'revision':plan['profile_revision'],'daily_new_words':2}).json()
    round=start(client,base)
    assert round['total']==2
    for item in round['items']:finish(client,base,item)
    assert start(client,base)['total']==0
    client.post(base+'/word-plan',json={'revision':changed['profile_revision'],'daily_new_words':0})
    assert start(client,base)['total']==0


def test_round_accepts_browser_compatibility_field_but_uses_signed_in_account(learner):
    client,_,_,base=setup(learner)
    response=client.post(base+'/word-rounds',json={
        'kind':'new','request_id':str(uuid.uuid4()),'user_id':'ignored-compatibility-value'})
    assert response.status_code==200,response.text
    round=response.json()
    assert round['total']==5
    assert client.get(base+'/word-rounds/'+round['id']).json()['id']==round['id']
