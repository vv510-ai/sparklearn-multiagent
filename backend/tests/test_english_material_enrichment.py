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
