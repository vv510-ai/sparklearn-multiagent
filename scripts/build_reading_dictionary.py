"""Build a bounded, indexed reading dictionary from the pinned ECDICT snapshot."""
import argparse
import csv
import hashlib
import json
import re
import zipfile
from pathlib import Path

from build_cet6_vocabulary import COMMIT, DICT_SHA, ROOT
from build_cet6_word_forms import CODES, exchange

WORD = re.compile(r"[a-z]+(?:['-][a-z]+)*")


def build(source, output):
    if hashlib.sha256(source.read_bytes()).hexdigest() != DICT_SHA:
        raise ValueError("Unreviewed ECDICT snapshot")
    records = {}
    with source.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            word = row['word'].casefold()
            meaning = (row['translation'] or row['definition']).replace('\\n', '\n').strip()
            if len(word) <= 100 and WORD.fullmatch(word) and meaning:
                if word not in records or row['word'] == word:
                    records[word] = (row['phonetic'], meaning, exchange(row['exchange']), row['word'])
    forms = {}

    def add(surface, lemma, codes):
        surface = surface.strip().casefold()
        if surface != lemma and WORD.fullmatch(surface) and len(surface) <= 100 and lemma in records:
            forms.setdefault(surface, {}).setdefault(lemma, set()).update(c for c in codes if c in CODES)

    for word, (_, _, ex, _) in records.items():
        for code, value in ex.items():
            if code in CODES:
                for surface in value.split(','):
                    add(surface, word, code)
    forward = {(s, w) for s, matches in forms.items() for w in matches}
    for surface, (_, _, ex, _) in records.items():
        for lemma in ex.get('0', '').split(','):
            if ex.get('1') and (surface, lemma) not in forward:
                add(surface, lemma, ex['1'])
    supplement = json.loads((ROOT / 'backend/app/data/cet6_word_forms_supplement.json').read_text(encoding='utf-8'))
    for extra in supplement['entries']:
        for surface, codes in extra['forms'].items():
            # "present" has a reviewed mapping in the study index; the archive
            # only needs the lemma to avoid a false standalone form.
            forms.setdefault(surface, {}).setdefault(extra['word'], set()).update(c for c in codes if c in CODES)
    shards = {}
    for word, (phonetic, meaning, ex, display) in sorted(records.items()):
        # Reverse-only records often just say "past tense/plural of ...".
        # Keep genuine independent meanings (e.g. saw), including adjectives.
        independent_lines = [line for line in meaning.splitlines() if line.strip() and not re.search(
            r'(?:复数|过去式|过去分词|现在分词|人称|比较级|最高级|plural of|past tense of|participle of)', line, re.I)]
        pure_form = not independent_lines
        standalone = not pure_form and (not ex.get('0') or bool(re.search(r'(?m)^(?:a|adj|adv|n)\.', meaning)) or any(
            ex.get(c) and ex[c] != word for c in ('p', 'd', '3')))
        # Lexicalized plural with independent meanings; the source explicitly
        # includes eyeglasses/binoculars, unlike a simple plural label.
        if word == 'glasses':
            standalone = True
        if word in forms and standalone and independent_lines:
            meaning = '\n'.join(independent_lines)
        shards.setdefault(word[:2], {'words': {}, 'forms': {}})['words'][word] = [phonetic, meaning, standalone, display]
        identifier = hashlib.sha256(word.encode()).hexdigest()[:24]
        shards.setdefault('ids-' + identifier[:2], {'ids': {}})['ids'][identifier] = word
    for surface, matches in sorted(forms.items()):
        shards.setdefault(surface[:2], {'words': {}, 'forms': {}})['forms'][surface] = {
            w: ''.join(sorted(codes)) for w, codes in sorted(matches.items())}
    manifest = {'version': 'ecdict-bc015ed-reading-v1', 'source_commit': COMMIT,
                'source_sha256': DICT_SHA, 'entries': len(records), 'forms': len(forms),
                'scope': 'Single English words, apostrophes and hyphens; Chinese meanings with English fallback. Not an exhaustive dictionary.',
                'source_url': f'https://github.com/skywind3000/ECDICT/tree/{COMMIT}',
                'license_url': f'https://github.com/skywind3000/ECDICT/blob/{COMMIT}/LICENSE'}
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in [('manifest', manifest), *sorted(shards.items())]:
            info = zipfile.ZipInfo(name.encode().hex() + '.json', (2026, 10, 15, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode())
    print(json.dumps(manifest | {'bytes': output.stat().st_size}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dictionary', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=ROOT / 'backend/app/data/reading_dictionary_v1.zip')
    args = parser.parse_args()
    build(args.dictionary, args.output)
