from __future__ import annotations

import asyncio
import json
import pytest
from tests._stubs import install
install()
from fastapi.testclient import TestClient
from app.main import app
from app.models.db import init_db, session
from app.models.entities import Resource
from app.services.profile_service import ensure_user
from app.services.knowledge_graph import clean_topic_label, explicit_topic_label, resolve_conversation_topic
from app.services.learning_scope import _scope, graph_index
from app.agents import quiz_agent, doc_agent


def test_course_task_command_resolves_subject_but_preserves_compound_questions():
    command = '请带我开始“词汇与语境”的第一项学习任务。先用一句话说清今天要学什么，再给我一个可以马上作答的小问题'
    assert clean_topic_label(command) == '词汇与语境'
    assert explicit_topic_label('我今天要学习什么内容，要具体完成什么任务，达到什么目标') is None
    token = _scope.set({'course': {'kind': 'cet6', 'title': '大学英语六级'}, 'graph': graph_index({'nodes': [{'id': 'cet6_vocabulary', 'name': '词汇与语境'}], 'edges': []})})
    try:
        assert resolve_conversation_topic(command) == ('cet6_vocabulary', '词汇与语境', True)
        assert resolve_conversation_topic('我今天要学习什么内容')[1] == '大学英语六级'
        assert '区别' in resolve_conversation_topic('词汇与语境和阅读推断有什么区别？')[1]
        assert explicit_topic_label('现在学什么是光合作用，为什么它会产生氧气') is not None
    finally:
        _scope.reset(token)


def test_resource_rename_is_durable_and_owner_only():
    init_db()
    ensure_user('batch-owner'); ensure_user('batch-other')
    with session() as db:
        db.query(Resource).filter(Resource.id == 'batch-rename').delete()
        db.add(Resource(id='batch-rename', user_id='batch-owner', kind='doc', kp='binary_tree', title='原笔记', payload={'markdown': '# 正文'}, citations=[]))
        db.commit()
    with TestClient(app) as client:
        forbidden = client.post('/api/resources/batch-rename/rename', json={'user_id': 'batch-other', 'title': '越权'})
        assert forbidden.status_code == 404
        for title in ['  ', 'a' * 121]:
            assert client.post('/api/resources/batch-rename/rename', json={'user_id': 'batch-owner', 'title': title}).status_code == 422
        response = client.post('/api/resources/batch-rename/rename', json={'user_id': 'batch-owner', 'title': '  二叉树复习  '})
        assert response.status_code == 200, response.text
        assert response.json()['title'] == '二叉树复习'
    with session() as db:
        saved = db.get(Resource, 'batch-rename')
        assert saved.title == '二叉树复习'
        assert saved.payload == {'markdown': '# 正文'}


async def _quiet(*args, **kwargs):
    pass


def test_real_quiz_failure_does_not_publish_generic_self_reflection(monkeypatch):
    monkeypatch.setattr(quiz_agent, 'is_demo', lambda: False)
    monkeypatch.setattr(quiz_agent, 'retrieve', lambda *a, **kw: [{'text': '二叉树每个节点最多两个孩子。', 'kp': 'binary_tree'}])
    for name in ['agent_start', 'agent_end', 'emit']:
        monkeypatch.setattr(quiz_agent, name, _quiet)
    async def failed(*args, **kwargs):
        raise TimeoutError('provider unavailable')
    monkeypatch.setattr(quiz_agent, 'llm_complete', failed)
    with pytest.raises(ValueError, match='没有可用的同主题题目'):
        asyncio.run(quiz_agent.run({'knowledge_points': ['binary_tree'], 'topic_label': '二叉树', 'source_ids': ['own-book'], 'learning_goal': '测试二叉树', 'student_profile': {}}))


def test_real_quiz_keeps_valid_questions_without_padding(monkeypatch):
    monkeypatch.setattr(quiz_agent, 'is_demo', lambda: False)
    monkeypatch.setattr(quiz_agent, 'retrieve', lambda *a, **kw: [{'text': '二叉树每个节点最多两个孩子。', 'kp': 'binary_tree'}])
    for name in ['agent_start', 'agent_end', 'emit']:
        monkeypatch.setattr(quiz_agent, name, _quiet)
    async def valid(*args, **kwargs):
        assert kwargs['max_tokens'] >= 6000
        assert kwargs['reasoning_mode'] == 'disabled'
        return json.dumps({'questions': [{'type': 'single', 'stem': '二叉树每个节点最多有几个孩子？', 'options': ['A. 一个', 'B. 两个', 'C. 三个', 'D. 四个'], 'answer': 'B', 'explain': '二叉树节点至多两个孩子。'}]}, ensure_ascii=False)
    monkeypatch.setattr(quiz_agent, 'llm_complete', valid)
    result = asyncio.run(quiz_agent.run({'knowledge_points': ['binary_tree'], 'topic_label': '二叉树', 'source_ids': ['own-book'], 'learning_goal': '测试二叉树', 'student_profile': {}}))
    resource = next(iter(result['generated_resources'].values()))
    assert len(resource['payload']['questions']) == 1


def test_conversation_notes_without_retrieval_remain_explicitly_unverified(monkeypatch):
    monkeypatch.setattr(doc_agent, 'retrieve', lambda *a, **kw: [])
    monkeypatch.setattr(doc_agent, 'is_demo', lambda: False)
    monkeypatch.setattr(doc_agent, 'emit', _quiet)
    async def unexpected(*args, **kwargs):
        raise AssertionError('conversation excerpt must not call external generation')
    monkeypatch.setattr(doc_agent, 'llm_complete', unexpected)
    result = asyncio.run(doc_agent._gen_one('doc', 'binary_tree', {}, topic_name='二叉树', source_ids=[], goal='保存对话', prompt_template='conversation_notes', conversation='学习者：二叉树是什么？\n小知：每个节点最多两个孩子。', trace_id='batch-notes', skip_multimodal=True, source_policy='strict'))
    payload = result['payload'] if 'payload' in result else result['resource']['payload']
    assert payload['generation_mode'] != 'unavailable'
    assert payload['verification'] == 'conversation_excerpt'
    assert '尚未用课程资料核验' in payload['markdown']
    assert '每个节点最多两个孩子' in payload['markdown']
    assert payload['source_evidence'] == []


def test_compound_question_keeps_concepts_after_comma():
    token = _scope.set({'course': {'kind': 'custom', 'title': '生态学'}, 'graph': graph_index({'nodes': [{'id': 'a', 'name': '能量流动'}, {'id': 'b', 'name': '物质循环'}], 'edges': []})})
    try:
        assert '物质循环' in resolve_conversation_topic('请解释能量流动，比较它与物质循环的区别')[1]
    finally:
        _scope.reset(token)


def test_tagged_course_sections_do_not_leak_via_incidental_vocabulary_words():
    from app.data.cet6_course import build_course
    from app.services.topic_scope import focus_chunks_on_topic
    course = build_course()
    token = _scope.set({'course': course, 'graph': graph_index(course['graph'])})
    try:
        chunks = [
            {'source_type': 'textbook', 'source_id': course['textbook']['id'], 'kp': 'cet6_vocab', 'text': '词汇与语境：用词性和搭配选择单词。'},
            {'source_type': 'textbook', 'source_id': course['textbook']['id'], 'kp': 'cet6_listening', 'text': '听力中也要理解词汇与语境，但本章练习听音频。'},
        ]
        assert [c['kp'] for c in focus_chunks_on_topic(chunks, 'cet6_vocab', '词汇与语境')] == ['cet6_vocab']
        assert len(focus_chunks_on_topic(chunks, 'custom_topic', '词汇与语境和听力信息提取的关系')) == 2
        assert len(focus_chunks_on_topic(chunks, 'custom_topic', course['title'])) == 2
    finally:
        _scope.reset(token)
