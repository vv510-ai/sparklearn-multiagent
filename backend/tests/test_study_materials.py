"""Account ownership, source boundaries and conflict-safe learning notes."""
import copy
import uuid
from sqlalchemy import select
from app.models.db import session, TENANT_TABLES
from app.models.entities import MaterialStudy
from app.services import study_materials
from tests.test_learning_spaces import learner  # noqa: F401


def test_reviewed_catalogue_does_not_equate_links_to_hosted_papers():
    data = study_materials.catalogue()
    papers = [m for m in data['items'] if m['kind'] == 'past_paper']
    assert len(papers) == 33
    assert len({m['year'] for m in papers}) == 11
    assert set(data['courses']) == {m['course'] for m in data['items']}
    assert all(m['source_role'] == '机构整理真题' for m in papers)
    assert all(m['checked_on'] and m['verification'] and m['access'] for m in data['items'])
    assert 'material_studies' in TENANT_TABLES
    assert '全文' in data['boundary']


def test_public_browse_private_writes_ownership_revision_and_no_mastery_change(learner):
    client, user = learner
    headers = dict(client.headers)
    client.headers.pop('authorization', None)
    assert client.get('/api/materials').status_code == 200
    assert 'studies' not in client.get('/api/materials').json()
    assert client.get('/api/materials/studies').status_code == 401
    assert client.post('/api/materials/studies', json={'material_id': 'cet6-format'}).status_code == 401
    assert client.post('/api/materials').status_code == 401
    assert client.get('/api/materials/unknown').status_code == 401
    client.headers.update(headers)
    before = client.get(f'/api/profile/{user}').json()['knowledge_mastery']
    row = client.post('/api/materials/studies', json={'material_id': 'cet6-format'}).json()
    assert row['revision'] == 0
    assert client.post('/api/materials/studies', json={'material_id': 'cet6-format'}).json() == row
    assert client.post('/api/materials/studies', json={'material_id': 'unknown'}).status_code == 404
    assert client.post('/api/materials/studies', json={'material_id': 'cet6-format', 'user_id': 'another-user'}).status_code == 422
    url = '/api/materials/studies/' + row['id']
    payload = dict(revision=0, task='完成阅读', location='46—50题', notes='先定位原文再推断', minutes=20, next_review='2026-10-03', status='done')
    response = client.post(url, json=payload)
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated['revision'] == 1 and updated['next_review'] == '2026-10-03'
    assert client.post(url, json=payload).json() == updated
    assert client.post(url, json={**payload, 'notes': 'stale'}).status_code == 409
    assert client.post(url, json={**payload, 'revision': 1, 'minutes': -1}).status_code == 422
    assert client.post(url, json={**payload, 'revision': 1, 'next_review': 'tomorrow'}).status_code == 422
    other = client.post('/api/auth/register', json={'email': f'materials-other-{uuid.uuid4().hex}@example.test', 'password': 'Test-Materials-Password!', 'name': '另一账号'}).json()
    client.headers['Authorization'] = 'Bearer ' + other['access_token']
    assert client.get('/api/materials/studies').json()['items'] == []
    assert client.post(url, json={**payload, 'revision': 1}).status_code == 404
    client.headers.update(headers)
    assert client.get('/api/materials/studies').json()['items'][0] == updated
    assert client.get(f'/api/profile/{user}').json()['knowledge_mastery'] == before
    with session() as db:
        assert len(db.scalars(select(MaterialStudy).where(MaterialStudy.user_id == user)).all()) == 1
