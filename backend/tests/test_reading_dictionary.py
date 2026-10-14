"""Reading vocabulary is broad; the study plan and coverage remain syllabus-only."""
import uuid

import pytest

from app.services import cet6_word_lookup as lookup, cet6_vocabulary as vocabulary, reading_dictionary
from tests.test_cet6_learning import setup, word_action
from tests.test_learning_spaces import learner, prepare  # noqa: F401
from tests.test_exam_reading_loop import context


@pytest.mark.parametrize('surface,headword,meaning', [
    ('legislature', 'legislature', '立法'), ('legislatures', 'legislature', '立法'),
    ('homelessness', 'homelessness', '无家可归'), ('lawmakers', 'lawmaker', '立法'),
    ('ever-increasing', 'ever-increasing', '增长'), ('legislature’s', 'legislature', '立法'),
])
def test_words_missing_from_study_list_have_real_dictionary_meanings(surface, headword, meaning):
    assert headword not in {e['word'] for e in vocabulary.entries().values()}
    matches = lookup.resolve(surface)
    match = next(m for m in matches if m['word'] == headword)
    assert meaning in match['meaning'] and match['collectible'] and not match['in_study_list']
    entry = vocabulary.entry(match['entry_id'])
    assert entry['level'] == 'reading' and entry['source_pages'] == []


def test_dictionary_keeps_independent_homographs_and_reuses_study_ids():
    matches = lookup.resolve('saw')
    assert {m['word'] for m in matches} == {'saw', 'see'}
    assert all(m['collectible'] for m in matches)
    assert '锯' in next(m['meaning'] for m in matches if m['word'] == 'saw')
    assert lookup.resolve('stopped')[0]['entry_id'] in vocabulary.entries()
    assert not lookup.resolve('qzxqzx')
    assert reading_dictionary.entry('reading-zz') is None
    assert reading_dictionary.entry('reading-' + '../secret'.encode().hex()) is None
    assert reading_dictionary.shard('manifest')['entries'] > 300000


@pytest.mark.parametrize('surface,lemma', [('was', 'be'), ('are', 'be'),
    ('algorithms', 'algorithm'), ('drones', 'drone'), ('sneakers', 'sneaker'), ('lawmakers', 'lawmaker')])
def test_pure_inflections_do_not_create_duplicate_cards(surface, lemma):
    assert {m['word'] for m in lookup.resolve(surface)} == {lemma}


def test_am_keeps_existing_study_identity_without_new_reading_card():
    matches = lookup.resolve('am')
    assert {m['word'] for m in matches} == {'am', 'be'}
    assert all(m['entry_id'] in vocabulary.entries() for m in matches)
    assert '人称' not in reading_dictionary.record('am')[1]


def test_long_headword_identity_fits_production_column():
    match = next(m for m in lookup.resolve('acceptable-environmental-range') if m['word'] == 'acceptable-environmental-range')
    assert len(match['entry_id']) <= 64
    assert vocabulary.entry(match['entry_id'])['word'] == match['word']
    assert {m['word'] for m in lookup.resolve('glasses')} >= {'glass', 'glasses'}
    assert {m['word'] for m in lookup.resolve('studied')} >= {'study', 'studied'}


def test_outside_collection_review_reload_does_not_change_daily_plan(learner):
    client, user, _, base = setup(learner)
    before = client.get(base + '/word-plan').json()
    lookup_result = client.get(base + '/word-lookup', params={'q': 'legislature'}).json()
    assert lookup_result['status'] == 'matched'
    item = lookup_result['auto_entry_id']
    detail = client.get(base + '/words/' + item).json()
    assert detail['family'] is None
    excerpt = context(client, base) | {'context': 'Two proposals are before the state legislature.',
                                     'surface_form': 'legislature', 'context_note': '本句指州立法机关'}
    card, body = word_action(client, base, detail, detail['cards'][0], 'collect', **excerpt)
    assert client.post(base + '/words/' + item, json=body).json() == card
    assert card['queued_at'] and not card['tracks']
    mine = client.get(base + '/words', params={'view': 'mine', 'q': 'legislatures'}).json()
    assert [e['id'] for e in mine['items']] == [item]
    assert client.get(base + '/words', params={'q': 'legislature'}).json()['total'] == 0
    round_ = client.post(base + '/word-rounds', json={'kind': 'review', 'request_id': str(uuid.uuid4())}).json()
    assert round_['items'][0]['entry_id'] == item
    card, _ = word_action(client, base, detail, card, 'start')
    active_plan = client.get(base + '/word-plan').json()
    assert active_plan['new_ids'] == before['new_ids'] and active_plan['protected_count'] == before['protected_count']
    restored = client.get(base + '/words/' + item).json()['cards'][0]
    assert restored['contexts'][0]['text'] == excerpt['context'] and restored['active']
    card, _ = word_action(client, base, detail, card, 'reveal')
    card, _ = word_action(client, base, detail, card, 'rate', rating='good')
    after = client.get(base + '/word-plan').json()
    for field in ('new_ids', 'completed_ids', 'new_done', 'new_remaining', 'available_new', 'coverage'):
        assert after[field] == before[field], field
    assert card['tracks']['meaning']['attempts'] == 1 and not card['queued_at']
    assert client.get(base + '/word-rounds/' + round_['id']).json()['finished']
    other, _, _ = prepare(client, user, 'cet6', '另一门六级')
    other_base = f"/api/notebooks/{other['id']}/cet6"
    assert not client.get(other_base + '/words/' + item).json()['cards'][0]['contexts']
    assert client.get(other_base + '/words', params={'view': 'mine'}).json()['total'] == 0
    for patch in ({'surface_form': 'legislatures'}, {'context': 'No matching token.'}):
        request = body | patch | {'revision': card['revision'], 'request_id': str(uuid.uuid4())}
        assert client.post(base + '/words/' + item, json=request).status_code == 422
