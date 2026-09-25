from __future__ import annotations
import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException
from app.models import db as database
from app.models.entities import User, GenerationJob, GenerationTicket, GenerationEvent, ConversationMessage
from app.services import generation_jobs as jobs
from app.tenant import current_user_context

@pytest.fixture
def store(tmp_path, monkeypatch):
    engine = create_engine('sqlite:///' + str(tmp_path/'jobs.db'), connect_args={'check_same_thread': False})
    monkeypatch.setattr(database, '_engine', engine)
    monkeypatch.setattr(database, '_SessionLocal', sessionmaker(bind=engine, expire_on_commit=False))
    monkeypatch.setattr(database, '_initialized_engine', None)
    database.init_db()
    with database.session() as db:
        db.add_all([User(id=f'u{i}', name='test') for i in range(8)])
        db.commit()
    monkeypatch.setenv('GENERATION_MAX_RUNNING', '4')
    monkeypatch.setenv('GENERATION_USER_PENDING', '3')
    yield engine
    engine.dispose()

def submit(user='u0', key='r1', kind='resource'):
    token = current_user_context.set(user)
    try:
        return jobs.submit({'user_id': user, 'session_id': 's-' + user, 'visible_message': 'question', 'messages': []}, kind, key, jobs.digest(key))
    finally:
        current_user_context.reset(token)

def expire(job_id):
    with database.session() as db:
        db.get(GenerationTicket, job_id).lease_until = 0
        db.commit()

def test_admission_is_atomic_and_idempotent(store):
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: submit(), range(6)))
    assert len({r['id'] for r in results}) == 1
    submit(key='r2'); submit(key='r3')
    with pytest.raises(HTTPException) as error:
        submit(key='r4')
    assert error.value.status_code == 429
    with pytest.raises(HTTPException):
        jobs.lookup('u0', 'r1', 'different')
    with pytest.raises(HTTPException) as error:
        jobs.owned('u1', results[0]['id'])
    assert error.value.status_code == 404
    assert jobs.list_jobs('u1', '') == []

def test_concurrent_workers_respect_global_and_user_limits(store):
    for i in range(6):
        submit(f'u{i}')
    submit('u0', 'r2')
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = [c for c in pool.map(lambda _: jobs.claim('worker'), range(8)) if c]
    assert len(claims) == 4
    assert len({c[1] for c in claims}) == 4
    first = claims[0]
    expire(first[0])
    recovered = jobs.claim('worker')
    assert recovered[0] == first[0] and recovered[2] != first[2]
    ctx = jobs._context.set(first)
    try:
        with database.session() as db:
            with pytest.raises(jobs.LeaseLost): jobs._leased(db)
    finally: jobs._context.reset(ctx)

def test_disconnect_does_not_cancel_job_and_cursor_replay_is_exact(store):
    job = submit(kind='chat')
    async def scenario():
        async def runner(state):
            yield {'type':'token', 'delta':'完整回答'}
            await asyncio.sleep(.02)
            yield {'type':'done'}
        execution = asyncio.create_task(jobs.execute(*jobs.claim('w'), runner=runner))
        stream = jobs.events('u0', job['id'])
        assert (await anext(stream))['type'] == 'job'
        await stream.aclose()  # browser disconnect
        await execution
        rows = [e async for e in jobs.events('u0', job['id'])]
        tokens = [e for e in rows if e['type']=='token']
        assert [e['delta'] for e in tokens] == ['完整回答']
        later = [e async for e in jobs.events('u0', job['id'], tokens[0]['event_id'])]
        assert not any(e['type']=='token' for e in later)
    asyncio.run(scenario())
    assert jobs.owned('u0', job['id'])['status'] == 'completed'
    with database.session() as db:
        assert [(r.role,r.content) for r in db.query(ConversationMessage).all()] == [('user','question'),('assistant','完整回答')]

def test_checkpoint_outbox_survives_crash_before_event_flush(store):
    job = submit(kind='chat')
    calls = []
    async def scenario():
        from app.agents.emitter import set_emitter, reset_emitter, emit
        async def answer(state):
            calls.append(1)
            await emit({'type':'token','delta':'已经完成的答案'})
            return {'answer':'已经完成的答案'}
        async def interrupted(state):
            token = set_emitter(lambda e: asyncio.sleep(0))  # event consumer never persisted the delivery
            try: await jobs.checkpoint('tutor', answer, state)
            finally: reset_emitter(token)
            raise asyncio.CancelledError()
            yield
        await jobs.execute(*jobs.claim('w'), runner=interrupted)
        expire(job['id'])
        async def recovered(state):
            result = await jobs.checkpoint('tutor', answer, state)
            assert result['answer'] == '已经完成的答案'
            yield {'type':'done'}
        await jobs.execute(*jobs.claim('w'), runner=recovered)
    asyncio.run(scenario())
    assert len(calls)==1
    with database.session() as db:
        answer = db.query(ConversationMessage).filter_by(role='assistant').one()
        assert answer.content == '已经完成的答案'
        assert db.query(GenerationEvent).filter_by(job_id=job['id']).count() == 2  # reset + outbox

def test_cached_stream_and_completed_text_are_not_paid_twice(store):
    job = submit()
    counts = {'text':0, 'stream':0}
    @jobs.durable_call('test')
    async def text_call(): counts['text'] += 1; return 'draft'
    @jobs.durable_stream
    async def stream_call(): counts['stream'] += 1; yield 'a'; yield 'b'
    async def runner(state):
        assert await text_call() == await text_call() == 'draft'
        assert [x async for x in stream_call()] == ['a','b']
        assert [x async for x in stream_call()] == ['a','b']
        yield {'type':'done'}
    asyncio.run(jobs.execute(*jobs.claim('w'), runner=runner))
    assert counts == {'text':1,'stream':1}

def test_unknown_submission_stops_instead_of_resubmitting(store):
    job = submit()
    called = []
    @jobs.durable_call('paid')
    async def provider():
        called.append(1)
        raise asyncio.CancelledError()
    async def run(state):
        await provider()
        yield {'type':'done'}
    asyncio.run(jobs.execute(*jobs.claim('w'), runner=run))
    expire(job['id'])
    asyncio.run(jobs.execute(*jobs.claim('w'), runner=run))
    assert len(called)==1
    assert jobs.owned('u0',job['id'])['status']=='needs_review'

def test_xiaoyunque_known_task_resumes_without_new_submission(store, monkeypatch, tmp_path):
    from app.llm import multimodal_gateway as gateway
    monkeypatch.setattr(gateway, 'GEN_DIR', tmp_path)
    counts = {'create':0,'poll':0}
    def create(prompt): counts['create'] += 1; return 'existing-provider-task'
    def poll(task_id):
        assert task_id == 'existing-provider-task'
        counts['poll'] += 1
        if counts['poll'] == 1: raise asyncio.CancelledError()
        return {'status':'succeeded','url':'https://example.test/image.jpg'}
    def download(url, target, **kwargs):
        from PIL import Image
        result=target.with_suffix('.jpg'); Image.new('RGB',(2,2)).save(result); return result
    monkeypatch.setattr(gateway.xiaoyunque_client, 'create_image_task', create)
    monkeypatch.setattr(gateway.xiaoyunque_client, 'poll_image_task', poll)
    monkeypatch.setattr(gateway, '_download_image', download)
    job = submit()
    async def run(state):
        url = gateway._generate_xiaoyunque_image('课程', 'digest', SimpleNamespace())
        yield {'type':'resource','resource':{'id':'result','payload':{'image_url':url}}}
    asyncio.run(jobs.execute(*jobs.claim('w'),runner=run))
    expire(job['id'])
    asyncio.run(jobs.execute(*jobs.claim('w'),runner=run))
    assert counts == {'create':1,'poll':2}
    assert jobs.owned('u0',job['id'])['status']=='completed'

def test_clear_conversation_invalidates_running_job(store):
    from app.services.conversation_service import clear_session_messages
    job=submit(kind='chat')
    claim=jobs.claim('w')
    with database.session() as db:
        row=db.get(GenerationJob,job['id']); row.status='running'; db.commit()
    clear_session_messages('u0','s-u0')
    assert jobs.owned('u0',job['id'])['status']=='cancelled'
    async def runner(state):
        pytest.fail('cancelled job must never execute')
        yield
    asyncio.run(jobs.execute(*claim,runner=runner))
    with database.session() as db: assert db.query(ConversationMessage).count()==0

def test_trace_runs_do_not_overwrite_each_other(tmp_path, monkeypatch):
    from app import trace
    monkeypatch.setattr(trace,'RUNS_DIR',tmp_path)
    monkeypatch.setattr(trace,'get_settings',lambda:SimpleNamespace(trace_enabled=True))
    with ThreadPoolExecutor(max_workers=4) as pool:
        runs=list(pool.map(lambda _:trace.TraceRecorder({'session_id':'same','user_id':'u'}),range(4)))
    assert len({r.run_dir for r in runs})==4
    assert all((r.run_dir/'request.json').exists() for r in runs)


def test_real_process_exit_recovers_saved_stage(store, tmp_path):
    import os, subprocess, sys
    from pathlib import Path
    job = submit(kind='chat')
    code = """
import asyncio, os, sys
from app.services import generation_jobs as jobs
from app.agents.emitter import emit
async def node(state):
    await emit({'type':'token','delta':'answer-saved-before-exit'})
    return {'answer':'answer-saved-before-exit'}
async def runner(state):
    result=await jobs.checkpoint('tutor',node,state)
    assert result['answer']=='answer-saved-before-exit'
    if sys.argv[1]=='crash': os._exit(71)
    yield {'type':'done'}
asyncio.run(jobs.execute(*jobs.claim('process'),runner=runner))
"""
    env={**os.environ,'DATABASE_URL':str(store.url),'DEMO_MODE':'true','AUTH_REQUIRED':'false','TRACE_ENABLED':'false'}
    cwd=str(Path(__file__).resolve().parents[1])
    first=subprocess.run([sys.executable,'-c',code,'crash'],cwd=cwd,env=env,capture_output=True,timeout=30)
    assert first.returncode == 71, first.stderr.decode(errors='replace')
    expire(job['id'])
    second=subprocess.run([sys.executable,'-c',code,'resume'],cwd=cwd,env=env,capture_output=True,timeout=30)
    assert second.returncode == 0, second.stderr.decode(errors='replace')
    assert jobs.owned('u0',job['id'])['status']=='completed'
    with database.session() as db:
        assert db.query(ConversationMessage).filter_by(role='assistant').one().content=='answer-saved-before-exit'


def test_provider_wait_yields_to_other_users_and_has_total_deadline(store, monkeypatch):
    job=submit()
    async def pending(state):
        raise jobs.ProviderPending()
        yield
    asyncio.run(jobs.execute(*jobs.claim('w'),runner=pending))
    submit('u1')
    assert jobs.claim('w')[1]=='u1'
    with database.session() as db:
        ticket=db.get(GenerationTicket,job['id']); ticket.created=time.time()-1900; ticket.lease_until=0; db.commit()
    async def forbidden(state):
        pytest.fail('expired task must not call provider again')
        yield
    asyncio.run(jobs.execute(*jobs.claim('w'),runner=forbidden))
    assert jobs.owned('u0',job['id'])['status']=='needs_review'


@pytest.mark.parametrize('failure',['poll','download','budget','provider_503'])
def test_provider_transient_failure_resumes_same_task(store, monkeypatch, tmp_path, failure):
    import requests
    from app.llm import multimodal_gateway as gateway
    monkeypatch.setattr(gateway,'GEN_DIR',tmp_path)
    counts={'create':0,'poll':0,'download':0}
    def create(prompt): counts['create']+=1; return 'same-provider-id'
    def poll(task):
        assert task=='same-provider-id'
        counts['poll']+=1
        if failure=='poll' and counts['poll']==1: raise requests.Timeout()
        if failure=='provider_503' and counts['poll']==1: raise gateway.xiaoyunque_client._TransientPollError('503')
        if failure=='budget' and counts['poll']==1: return {'status':'running'}
        return {'status':'succeeded','url':'https://example.test/a.jpg'}
    def download(url,target,**kwargs):
        counts['download']+=1
        if failure=='download' and counts['download']==1: raise requests.ConnectionError()
        from PIL import Image
        p=target.with_suffix('.jpg'); Image.new('RGB',(2,2)).save(p); return p
    monkeypatch.setattr(gateway.xiaoyunque_client,'create_image_task',create)
    monkeypatch.setattr(gateway.xiaoyunque_client,'poll_image_task',poll)
    monkeypatch.setattr(gateway,'_download_image',download)
    if failure=='budget':
        clock=iter(range(1000))
        monkeypatch.setattr(gateway,'time',SimpleNamespace(monotonic=lambda:next(clock),sleep=lambda n:None))
    job=submit()
    async def run(state):
        gateway._generate_xiaoyunque_image('topic','digest',SimpleNamespace(mm_xyq_image_wait_budget_s=1))
        yield {'type':'done'}
    asyncio.run(jobs.execute(*jobs.claim('w'),runner=run))
    with database.session() as db:
        assert db.get(GenerationTicket,job['id']).status=='queued'
        db.get(GenerationTicket,job['id']).lease_until=0; db.commit()
    asyncio.run(jobs.execute(*jobs.claim('w'),runner=run))
    assert counts['create']==1
    assert jobs.owned('u0',job['id'])['status']=='completed'


def test_recovered_error_is_not_reported_as_success(store):
    job=submit()
    async def first(state):
        from app.agents.emitter import emit
        async def bad(state):
            await emit({'type':'error','detail':'controlled failure'})
            return {}
        await jobs.checkpoint('doc',bad,state)
        raise asyncio.CancelledError()
        yield
    asyncio.run(jobs.execute(*jobs.claim('w'),runner=first))
    expire(job['id'])
    async def resume(state): yield {'type':'done'}
    asyncio.run(jobs.execute(*jobs.claim('w'),runner=resume))
    assert jobs.owned('u0',job['id'])['status']=='failed'


def test_request_trace_id_does_not_repeat_paid_media_call(store):
    submit()
    calls=[]
    @jobs.durable_call('tts')
    async def media(text, *, trace_id): calls.append(trace_id); return {'audio':'saved'}
    async def runner(state):
        assert await media('same lesson',trace_id='before') == await media('same lesson',trace_id='after')
        yield {'type':'done'}
    asyncio.run(jobs.execute(*jobs.claim('w'),runner=runner))
    assert calls==['before']
