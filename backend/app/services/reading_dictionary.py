"""Read-only sharded dictionary. Never expands the CET-6 study catalogue."""
import hashlib
import json
import re
import zipfile
from functools import lru_cache
from pathlib import Path

ARCHIVE = Path(__file__).parents[1] / 'data/reading_dictionary_v1.zip'
PREFIX = 'reading-'
WORD = re.compile(r"[a-z]+(?:['-][a-z]+)*")


@lru_cache(maxsize=16)
def shard(prefix):
    # Read one small compressed shard, never extract the archive or load it all.
    with zipfile.ZipFile(ARCHIVE) as archive:
        try:
            return json.loads(archive.read(prefix.encode().hex() + '.json'))
        except KeyError:
            return {'words': {}, 'forms': {}}


def record(word):
    return shard(word[:2])['words'].get(word) if WORD.fullmatch(word) and len(word) <= 100 else None


def matches(word):
    if not WORD.fullmatch(word) or len(word) > 100:
        return []
    data = shard(word[:2])
    forms = data['forms'].get(word, {})
    row = data['words'].get(word)
    result = [(word, [])] if row and (row[2] or not forms) else []
    return result + [(lemma, list(codes)) for lemma, codes in forms.items()]


def entry_id(word):
    return PREFIX + hashlib.sha256(word.encode()).hexdigest()[:24]


def entry(item):
    if not re.fullmatch(r'reading-[0-9a-f]{24}', item):
        return None
    identifier = item[len(PREFIX):]
    word = shard('ids-' + identifier[:2]).get('ids', {}).get(identifier)
    if not word:
        return None
    if entry_id(word) != item:
        return None
    row = record(word)
    if not row:
        return None
    source = shard('manifest')['source_url']
    meanings = list(dict.fromkeys(line.strip() for line in row[1].splitlines() if line.strip()))
    return {'id': item, 'word': row[3], 'phonetic': row[0], 'level': 'reading',
            'variants': [], 'derivatives': [], 'source_pages': [], 'source_url': source, 'dictionary_url': source,
            'senses': [{'id': 'reading-sense-' + hashlib.sha256(f'{word}:{text}'.encode()).hexdigest()[:24],
                        'definition': text, 'source_label': 'ECDICT 社区词典 · 阅读补充词', 'source_url': source}
                       for text in meanings]}
