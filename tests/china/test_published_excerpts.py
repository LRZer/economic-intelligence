import hashlib
import json
from pathlib import Path

from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[2]


def test_published_html_exactly_matches_validated_statistical_excerpts():
    manifest=json.loads((ROOT/'docs/source-excerpt-manifest.json').read_text(encoding='utf-8'))
    folder=ROOT/'src/china_macro/bundled_snapshots'
    expected={r['excerpt_file'] for r in manifest['records']}
    assert {p.name for p in folder.glob('*.html')}==expected
    assert len(expected)==342
    for record in manifest['records']:
        raw=(folder/record['excerpt_file']).read_bytes()
        assert hashlib.sha256(raw).hexdigest()==record['excerpt_sha256']
        assert record['original_sha256']!=record['excerpt_sha256'] and record['replay_unchanged']
        soup=BeautifulSoup(raw,'html.parser')
        assert not soup.find(['script','style','img','iframe','object','embed','form'])
