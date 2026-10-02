"""Rebuild every visible vocabulary row from the exact official CET 2016 PDF.

This is a source extraction audit, not a product importer. It preserves source
variants and homograph identities; it never invents entries to match a total.
Requires pdfplumber and pypdf. Run from any directory with:
    python scripts/extract_cet6_official.py --source <official.pdf> --output-dir <directory>
Outputs are audit-official-rows.json and audit-official-report.json in that directory.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import statistics
import sys
import unicodedata

import pdfplumber
from pypdf import PdfReader

EXPECTED_SHA256 = '9166d3c03b7bc43abd9d9df91bd2ef8085b4419286f1e5ca100dea68f3cfd1f1'
SOURCE_URL = 'https://cet.neea.edu.cn/res/Home/1704/55b02330ac17274664f06d9d3db8249d.pdf'
STAR = chr(0x2605)
SOURCE_HYPHEN = chr(0xff27)
SOURCE_APOSTROPHE = chr(0x1001b3)
SUPER_DIGITS = dict(zip('123', ['\u00b9', '\u00b2', '\u00b3']))


def normalize_glyph(text):
    # Map the source's fullwidth G BEFORE NFKC, preserving a real Latin G.
    text = text.replace(SOURCE_HYPHEN, '-').replace(SOURCE_APOSTROPHE, "'")
    return unicodedata.normalize('NFKC', text)


def make_columns(chars):
    columns = []
    for c in sorted(chars, key=lambda c: c['x']):
        if not columns or c['x'] - columns[-1][-1]['x'] > 15:
            columns.append([])
        columns[-1].append(c)
    return columns


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).with_name('official-syllabus-2016.pdf'))
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).parent)
    args = parser.parse_args()
    digest = hashlib.sha256(args.source.read_bytes()).hexdigest()
    if digest != EXPECTED_SHA256:
        raise ValueError('This reviewed layout rule only supports the pinned source SHA256; inspect a changed PDF first.')
    reader = PdfReader(args.source)
    assert len(reader.pages) == 215

    printed_pages = {}
    for physical_page in range(21, 150):
        text = reader.pages[physical_page - 1].extract_text()
        values = re.findall(r'^\s*([\uff10-\uff19]{2,3})[\u3000 ]*$', text, re.M)
        values = [int(unicodedata.normalize('NFKC', n)) for n in values]
        assert values == [physical_page - 5], (physical_page, values)
        printed_pages[physical_page] = values[0]

    # Fonts have misleading bboxes: the star top is 7.336 pt below the English
    # top despite sharing the same drawing baseline. Use matrix[5], not top.
    draft_rows = []
    unassigned = []
    total_body_glyphs = 0
    assigned_glyph_ids = []
    with pdfplumber.open(args.source) as pdf:
        for physical_page in range(21, 150):
            page = pdf.pages[physical_page - 1]
            chars = []
            for index, c in enumerate(page.chars):
                if not (65 < c['top'] < 680 and c['x0'] < 490):
                    continue
                if round(c['size'], 3) not in {9.704, 5.337}:
                    continue
                chars.append({
                    'text': c['text'], 'x': round(c['matrix'][4], 3),
                    'y': round(c['matrix'][5], 3), 'size': round(c['size'], 3),
                    'id': (physical_page, index),
                })
            total_body_glyphs += len(chars)
            letters = [c for c in chars if c['size'] > 9 and
                       (re.fullmatch('[A-Za-z]', c['text']) or c['text'] == '\u00e9')]
            baselines = []
            for c in sorted(letters, key=lambda c: -c['y']):
                if not baselines or baselines[-1] - c['y'] > 2:
                    baselines.append(c['y'])
            groups = [[] for _ in baselines]
            for c in chars:
                closest = min(range(len(baselines)), key=lambda n: abs(baselines[n] - c['y']))
                if abs(baselines[closest] - c['y']) < 6:
                    groups[closest].append(c)
                    assigned_glyph_ids.append(c['id'])
                else:
                    unassigned.append({'page': physical_page, **c})
            for row_number, (baseline, row_chars) in enumerate(zip(baselines, groups), 1):
                columns = make_columns(row_chars)
                # Visually verified p.58 (physical 63), row 8: the long main
                # alternative almost touches derivative column 1. Generic gap
                # splitting merges them, so use this documented source boundary.
                if physical_page == 63 and row_number == 8:
                    assert ''.join(c['text'] for c in columns[0]) == STAR + 'esthetic/aestheticesthetics/aesthetics'
                    fused = columns[0]
                    left = [c for c in fused if c['x'] < 168.699]
                    right = [c for c in fused if c['x'] >= 168.699]
                    assert ''.join(c['text'] for c in left) == STAR + 'esthetic/aesthetic'
                    assert ''.join(c['text'] for c in right) == 'esthetics/aesthetics'
                    columns = [left, right] + columns[1:]
                draft_rows.append({'page': physical_page, 'row': row_number,
                                   'baseline': baseline, 'columns': columns})

    # The only unassigned full-size body glyphs must be the two printed totals.
    assert [(c['page'], c['text']) for c in unassigned] == [(149, t) for t in '\uff15\uff14\uff11\uff18\uff12\uff15\uff15\uff11']
    assert len(set(assigned_glyph_ids)) == len(assigned_glyph_ids)
    assert len(assigned_glyph_ids) + len(unassigned) == total_body_glyphs
    assert sum(len(col) for r in draft_rows for col in r['columns']) == len(assigned_glyph_ids)

    # Source PDF uses positioned glyphs, not literal spaces. Repeated Latin
    # letter pairs reveal normal distances; an extra 3.493 pt is a word space.
    pair_distances = defaultdict(list)
    for r in draft_rows:
        for col in r['columns']:
            for a, b in zip(col, col[1:]):
                if re.fullmatch('[A-Za-z]', a['text']) and re.fullmatch('[A-Za-z]', b['text']):
                    pair_distances[(a['text'], b['text'])].append(b['x'] - a['x'])
    pair_medians = {k: statistics.median(v) for k, v in pair_distances.items() if len(v) >= 4}
    spacing_repairs = []

    def parse_form(chars, page, row, column):
        chars = [c for c in chars if c['text'] != STAR]
        raw = ''.join(c['text'] for c in chars)
        indices = [i for i, c in enumerate(chars) if c['size'] < 8 and normalize_glyph(c['text']).isdigit()]
        assert len(indices) <= 1
        homograph = int(normalize_glyph(chars[indices[0]]['text'])) if indices else None
        display, normalized = [], []
        for index, c in enumerate(chars):
            if index:
                previous = chars[index - 1]
                pair = (previous['text'], c['text'])
                if pair in pair_medians:
                    residual = c['x'] - previous['x'] - pair_medians[pair]
                    if residual > 1:
                        assert 3.48 < residual < 3.51, (page, raw, residual)
                        display.append(' ')
                        normalized.append(' ')
                        spacing_repairs.append({'page': page, 'row': row, 'column': column,
                                                'raw': raw, 'insert_before_index': index,
                                                'extra_gap_pt': round(residual, 3)})
            text = normalize_glyph(c['text'])
            if index in indices:
                display.append(SUPER_DIGITS[text])
            else:
                display.append(text)
                normalized.append(text)
        display = ' '.join(''.join(display).split())
        normalized = ' '.join(''.join(normalized).split())
        if page == 49 and raw == "coup(d" + SOURCE_APOSTROPHE + '\u00e9tat)':
            # Visually verified physical 49, printed 44; parentheses here expand
            # a phrase, unlike a spelling-variant parenthesis inside a word.
            display = normalized = "coup (d'\u00e9tat)"
        return {'raw': raw, 'normalized': normalized, 'display': display,
                'homograph_number': homograph, 'x': chars[0]['x'], 'glyph_count': len(chars)}

    rows = []
    for ordinal, r in enumerate(draft_rows, 1):
        forms = [parse_form(c, r['page'], r['row'], i) for i, c in enumerate(r['columns'])]
        first, rest = forms[0], forms[1:]
        starred = any(c['text'] == STAR for c in r['columns'][0])
        assert 80 <= first['x'] <= 84
        assert all(160 <= c['x'] <= 430 for c in rest)
        rows.append({
            'ordinal': ordinal,
            'source_id': f"cet-2016-p{r['page']:03d}-r{r['row']:02d}",
            'raw_head': first['raw'], 'normalized_head': first['normalized'],
            'display_head': first['display'], 'starred': starred,
            'homograph_number': first['homograph_number'],
            'source_pdf_page': r['page'], 'source_printed_page': printed_pages[r['page']],
            'source_row': r['row'], 'source_baseline_y': r['baseline'],
            'source_x': first['x'],
            'derivatives': [
                {'raw_form': f['raw'], 'normalized_form': f['normalized'],
                 'display_form': f['display'], 'homograph_number': f['homograph_number'],
                 'source_column': n, 'source_x': f['x'], 'source_glyph_count': f['glyph_count']}
                for n, f in enumerate(rest, 1)
            ],
            'source_glyph_count': sum(len(c) for c in r['columns']),
        })

    per_page = []
    for p in range(21, 150):
        rs = [r for r in rows if r['source_pdf_page'] == p]
        body = '\n'.join(('\u2605 ' if r['starred'] else '') + r['display_head'] + '\t' +
                         '\t'.join(d['display_form'] for d in r['derivatives']) for r in rs)
        per_page.append({'pdf_page': p, 'printed_page': printed_pages[p], 'row_count': len(rs),
                         'first_head': rs[0]['display_head'], 'last_head': rs[-1]['display_head'],
                         'body_sha256': hashlib.sha256(body.encode('utf-8')).hexdigest()})
    assert [p['row_count'] for p in per_page] == [42] * 128 + [1]
    assert len({p['body_sha256'] for p in per_page}) == 129
    assert rows[0]['normalized_head'] == 'a/an' and rows[-1]['normalized_head'] == 'zoom'
    assert len(spacing_repairs) == 5
    assert {(r['page'], r['raw']) for r in spacing_repairs} == {
        (21, 'accordingto'), (29, 'babyboom'), (29, 'babyboomer'), (101, 'oughtto'), (102, 'owingto')}
    assert next(r for r in rows if r['normalized_head'] == 'owe')['derivatives'][0]['normalized_form'] == 'owing to'
    assert next(r for r in rows if r['normalized_head'] == 'pray')['derivatives'][0]['homograph_number'] == 1
    assert next(r for r in rows if r['normalized_head'] == 'pray')['derivatives'][1]['homograph_number'] == 2
    assert {r['source_id'] for r in rows if r['normalized_head'] == 'check/cheque'} == {'cet-2016-p041-r01'}

    derivatives = [d for r in rows for d in r['derivatives']]
    counts = {
        'visible_main_rows': len(rows), 'starred_main_rows': sum(r['starred'] for r in rows),
        'unstarred_main_rows': sum(not r['starred'] for r in rows),
        'visible_derivative_cells': len(derivatives),
        'main_rows_with_homograph_number': sum(r['homograph_number'] is not None for r in rows),
        'derivative_cells_with_homograph_number': sum(d['homograph_number'] is not None for d in derivatives),
        'unique_normalized_heads': len({r['normalized_head'] for r in rows}),
        'unique_normalized_derivative_forms': len({d['normalized_form'] for d in derivatives}),
        'body_glyphs_considered': total_body_glyphs,
        'body_glyphs_assigned_once': len(assigned_glyph_ids),
        'unassigned_printed_total_digits': len(unassigned),
        'printed_main_total': 5418, 'printed_second_column_total': 2551,
        'printed_minus_visible_main_rows': 5418 - len(rows),
        'printed_minus_visible_derivative_cells': 2551 - len(derivatives),
    }
    # Observations are regression gates for this SHA, never a padding target.
    assert (len(rows), len(derivatives), counts['starred_main_rows']) == (5377, 2519, 1263)
    assert counts['main_rows_with_homograph_number'] == 154
    assert counts['derivative_cells_with_homograph_number'] == 2
    assert hashlib.sha256(args.source.read_bytes()).hexdigest() == digest
    report = {
        'schema_version': 1, 'status': 'all_visible_rows_extracted_declared_total_difference_unresolved',
        'source_url': SOURCE_URL, 'source_sha256': digest, 'pdf_page_count': len(reader.pages),
        'vocabulary_physical_pages': [21, 149], 'vocabulary_printed_pages': [16, 144],
        'counts': counts,
        'checks': {
            'printed_page_numbers_continuous': True, 'no_duplicate_body_pages': True,
            'every_retained_body_glyph_assigned_once': True,
            'only_unassigned_glyphs_are_printed_totals': True,
            'original_sha256_unchanged_after_run': True,
            'variants_preserved_without_expansion': True,
        },
        'interpretation': [
            'Visible row and cell counts are not asserted to equal the publisher declared counts.',
            'The 41-row difference equals the final page unused 42-row positions, but this does not establish how the publisher counted.',
            'No missing or duplicate numbered vocabulary page was found; printed pages 16 through 144 are continuous.',
            'Different spelling variants and bracket abbreviations stay in their original source cell.',
            'Homograph numbers remain separate identities, including cross-page pairs and prayer derivatives.',
            'The official table supplies spelling forms, not pronunciation, meanings, or part of speech.',
        ],
        'layout_repairs': [
            {'type': 'baseline_instead_of_bbox_top', 'reason': 'star bbox top offset is 7.336 pt despite equal text baseline'},
            {'type': 'split_visually_verified_columns', 'pdf_page': 63, 'printed_page': 58, 'source_row': 8,
             'left': 'esthetic/aesthetic', 'right': 'esthetics/aesthetics', 'right_start_x': 168.699},
            {'type': 'phrase_parenthesis_space', 'pdf_page': 49, 'source_row': 10, 'normalized': "coup (d'\u00e9tat)"},
        ],
        'inferred_and_visually_verified_spaces': spacing_repairs,
        'pages': per_page,
        'runtime_versions': {p: importlib.metadata.version(p) for p in ('pdfplumber', 'pypdf')},
    }
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows_path = args.output_dir / 'audit-official-rows.json'
    report_path = args.output_dir / 'audit-official-report.json'
    rows_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    report['rows_file_sha256'] = hashlib.sha256(rows_path.read_bytes()).hexdigest()
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'rows_file': str(rows_path.resolve()), 'report_file': str(report_path.resolve()),
                      'counts': counts}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
