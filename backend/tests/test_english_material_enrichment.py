"""Content delivery must preserve attempts, source editions and per-sense recall."""
import copy

import pytest

from app.data.cet6_exam_catalogue import catalogue_data
from app.data.cet6_material_enrichment import enrich_papers, word_additions
from app.services import cet6_vocabulary as vocabulary, vocabulary_lessons
from tests.test_cet6_learning import setup, find_word, word_action
from tests.test_cet6_exams import action
from tests.test_learning_spaces import learner, prepare  # noqa: F401


def test_pending_question_is_not_a_learning_error_and_does_not_rewrite_history(learner):
    client, _, _, base = setup(learner)
    path = base + '/exams/cet6-2024-06-1/reading_careful'
    initial = client.get(path).json()
    assert 'comparison' not in initial
    assert all(set(q) == {'number', 'choices', 'page', 'group'} for q in initial['material']['questions'])
    body = action(initial, 'submit')
    body['answers'] = dict(zip(map(str, range(46, 56)), 'B B A D C D C A B A'.split()))
    response = client.post(path, json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    first = copy.deepcopy(result['first'])
    assert first['correct'] == 9 and first['total'] == 10
    assert result['comparison'] == {'correct': 9, 'total': 9, 'excluded': [47]}
    q47 = result['material']['questions'][1]
    assert q47['answer'] == 'D' and q47['review_status'] == 'pending'
    assert len(q47['option_reasons']) == 4
    assert client.get(path).json()['first'] == first
    restarted = client.post(path, json=action(result, 'restart')).json()
    assert restarted['history_count'] == 1 and 'comparison' not in restarted
    assert all('review_note' not in q for q in restarted['material']['questions'])


def test_source_change_cannot_silently_reuse_teaching_notes():
    papers = copy.deepcopy(catalogue_data())
    papers['cet6-2024-06-1']['pdf_sha256'] = 'different-edition'
    with pytest.raises(ValueError, match='source edition'):
        enrich_papers(papers)


def test_corrected_reference_recompares_without_rewriting_old_attempt(learner, monkeypatch):
    client, _, _, base = setup(learner)
    paper = catalogue_data()['cet6-2025-06-1']
    questions = paper['blocks']['reading_careful']['questions']
    q52 = next(q for q in questions if q['number'] == 52)
    assert q52['answer'] == 'A'
    assert q52['answer_correction']['from'] == 'D'
    assert q52['answer_correction']['source_sha256'] == paper['pdf_sha256']
    assert q52['answer_correction']['evidence_pages'] == [12, 13]
    path = base + '/exams/cet6-2025-06-1/reading_careful'
    initial = client.get(path).json()
    assert 'answer_correction' not in initial['material']['questions'][6]
    body = action(initial, 'submit')
    body['answers'] = {str(q['number']): q['answer'] for q in questions}
    # Exercise an attempt actually scored with the old key before this correction.
    with monkeypatch.context() as old:
        old.setitem(q52, 'answer', 'D')
        old.delitem(q52, 'answer_correction')
        submitted = client.post(path, json=body).json()
    first = copy.deepcopy(submitted['first'])
    assert first['correct'] == 9
    fresh = client.get(path).json()
    assert fresh['first'] == first
    assert fresh['comparison'] == {'correct': 10, 'total': 10, 'excluded': [], 'corrected': [52]}
    retried = client.post(path, json=body)
    assert retried.status_code == 200
    assert retried.json()['first'] == first and retried.json()['comparison'] == fresh['comparison']
    restarted = client.post(path, json=action(fresh, 'restart')).json()
    assert restarted['history_count'] == 1 and 'comparison' not in restarted
    next_body = action(restarted, 'submit')
    next_body['answers'] = body['answers']
    current = client.post(path, json=next_body).json()
    assert current['first']['correct'] == 10 and current['history_count'] == 1
    from app.models.db import session
    from app.models.entities import Cet6PaperAttempt
    from sqlalchemy import select
    with session() as db:
        saved = db.scalar(select(Cet6PaperAttempt).where(Cet6PaperAttempt.data['first']['submission_id'].as_string() == current['first']['submission_id']))
        assert saved.data['history'][-1] == first


def test_lessons_keep_existing_sense_identities_and_basic_preferences():
    base_words = {e['word']: e for e in vocabulary.corpus()['entries']}
    for row in word_additions():
        entry = next(e for e in vocabulary.entries().values() if e['word'] == row['word'])
        assert [s['id'] for s in entry['senses'][:len(base_words[row['word']]['senses'])]] == [s['id'] for s in base_words[row['word']]['senses']]
        lesson = vocabulary_lessons._ready(entry, row['sense_id'])
        assert lesson['status'] == 'ready' and lesson['origin'] == 'curated'
        assert lesson['sources'][0]['url'] == row['source_url']
        if row.get('definition'):
            assert vocabulary_lessons.preferred_sense(entry) != row['sense_id']


def test_supplemental_sense_from_exam_keeps_context_and_enters_review(learner):
    client, _, _, base = setup(learner)
    detail = find_word(client, base, 'climate')
    sense = 'sense-material-v1-climate-atmosphere'
    card = next(c for c in detail['cards'] if c['sense_id'] == sense)
    result, _ = word_action(client, base, detail, card, 'collect',
        context='Build a safety climate within their team.', context_note='这里是团队氛围',
        exam_id='cet6-2024-06-1', exam_kind='reading_careful', exam_question=50,
        exam_version=catalogue_data()['cet6-2024-06-1']['version'])
    assert result['queued_at'] and result['tracks'] == {}
    assert result['contexts'][0]['exam_question'] == 50
    assert result['contexts'][0]['note'] == '这里是团队氛围'
    fresh = find_word(client, base, 'climate')
    assert fresh['next_review'] == {'sense_id': sense, 'mode': 'meaning'}
    assert next(c for c in fresh['cards'] if c['sense_id'] == sense)['contexts'] == result['contexts']
    lesson = client.get(base + '/words/' + detail['entry']['id'] + '/lesson', params={'sense_id': sense})
    assert lesson.status_code == 200 and lesson.json()['origin'] == 'curated'


@pytest.mark.parametrize('paper_id', [
    f'cet6-{period}-{number}'
    for period in ('2024-06', '2024-12', '2025-06', '2025-12')
    for number in (1, 2, 3)
])
@pytest.mark.parametrize('kind', ['reading_cloze', 'reading_matching', 'reading_careful'])
def test_full_reading_notes_only_appear_after_submission(learner, paper_id, kind):
    client, _, _, base = setup(learner)
    path = base + f'/exams/{paper_id}/{kind}'
    initial = client.get(path).json()
    assert all(set(q) == {'number', 'choices', 'page', 'group'} for q in initial['material']['questions'])
    expected = catalogue_data()[paper_id]['blocks'][kind]['questions']
    body = action(initial, 'submit')
    body['answers'] = {str(q['number']): q['answer'] for q in expected}
    response = client.post(path, json=body)
    assert response.status_code == 200, response.text
    questions = response.json()['material']['questions']
    assert len(questions) == 10
    assert all(q['explanation'] and q['location'] and q['tip'] for q in questions)
    assert [q['answer'] for q in questions] == [q['answer'] for q in expected]


def test_topics_reuse_word_cards_without_replacing_daily_plan(learner):
    from app.services import cet6_vocabulary_topics as topics
    client, _, _, base = setup(learner)
    plan = client.get(base + '/word-plan').json()
    values = client.get(base + '/words', params={'topic': 'blame'}).json()
    assert values['topic']['id'] == 'blame'
    assert {w['word'] for w in values['items']} == set(topics.select('blame', vocabulary.entries())['words'])
    detail = find_word(client, base, 'blame')
    assert next(w['id'] for w in values['items'] if w['word'] == 'blame') == detail['entry']['id']
    word_action(client, base, detail, detail['cards'][0], 'collect')
    mine = client.get(base + '/words', params={'topic': 'blame', 'view': 'mine'}).json()
    assert [w['word'] for w in mine['items']] == ['blame']
    assert client.get(base + '/word-plan').json()['new_ids'] == plan['new_ids']
    assert client.get(base + '/words', params={'topic': 'missing'}).status_code == 422
    ordinary = client.get(base + '/words').json()
    assert ordinary['topic'] is None and ordinary['total'] == 8010
    other, _, _ = prepare(client, learner[1], 'python', 'Python')
    assert client.get(f"/api/notebooks/{other['id']}/cet6/words?topic=blame").status_code == 404
    client.headers.pop('Authorization', None)
    assert client.get(base + '/words?topic=blame').status_code == 401


def test_topic_references_are_separate_and_cached_data_is_not_mutated():
    from app.services import cet6_vocabulary_topics as topics
    original = copy.deepcopy(topics.data())
    known = {e['word'] for e in vocabulary.entries().values()}
    assert len({t['id'] for t in original['topics']}) == len(original['topics'])
    for topic in original['topics']:
        selected = topics.select(topic['id'], vocabulary.entries())
        assert len(topic['words']) == len(set(topic['words']))
        assert set(selected['words']) <= known
        assert set(selected['reference_words']).isdisjoint(known)
        assert set(selected['words']) | set(selected['reference_words']) == set(topic['words'])
        for check in selected['checks']:
            assert len(check['options']) == 4 and 0 <= check['answer'] < 4
        selected['words'].clear()
    assert topics.data() == original
