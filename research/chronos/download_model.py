"""Download only three pinned public model files; never execute model code."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlparse

import requests

from chronos_runtime_resources import disk_resources
from chronos_resource_guard import disk_stop_reason

MODEL_ID = 'autogluon/chronos-2-synth'
REVISION = '3607918a9fd027d5c465d8213e46b98e2c041cea'
FILES = {
    'config.json': (971, '01fd2b164b1ea49588624d369c37fcd67acfc12735c1082d79f5ec14a4d7cf37'),
    'README.md': (1265, '3b86d1695d4f98bc2b149f7afbe14c93df991284fd0bcb9bd40253f951866a48'),
    'model.safetensors': (475963368, '920a3344726a8026c9335d38ae1a2bfa9b7d659c1b8fe0b0af8d5f775863422e'),
}


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def check_file(path, size, digest):
    if path.stat().st_size != size or sha(path) != digest:
        raise ValueError('Pinned model file size/SHA mismatch: ' + path.name)


def check_url(url):
    parsed = urlparse(url)
    host = parsed.hostname or ''
    if parsed.scheme != 'https' or not (host == 'huggingface.co' or host.endswith(('.huggingface.co', '.hf.co'))):
        raise RuntimeError('Unexpected nonofficial model redirect')


def get(session, url, headers):
    for _ in range(8):
        check_url(url)
        response = session.get(url, headers=headers, stream=True, timeout=(10, 90), allow_redirects=False)
        if response.is_redirect:
            location = response.headers['Location']
            from urllib.parse import urljoin
            url = urljoin(url, location)
            response.close()
            continue
        response.raise_for_status()
        return response
    raise RuntimeError('Too many official redirects')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--verify-only', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if disk_stop_reason(disk_resources(root), starting=not args.verify_only):
        raise RuntimeError('Research disk budget not met')
    model = root / 'model'
    if not args.verify_only:
        model.mkdir(exist_ok=True)
        (root / 'metadata').mkdir(exist_ok=True)
    session = requests.Session()
    session.trust_env = False
    records = []
    for name, (size, digest) in FILES.items():
        target = model / name
        url = f'https://huggingface.co/{MODEL_ID}/resolve/{REVISION}/{name}'
        if target.exists():
            check_file(target, size, digest)
        elif args.verify_only:
            raise FileNotFoundError('Model file missing: ' + name)
        else:
            partial = model / (name + '.part')
            if partial.exists() and partial.stat().st_size > size:
                raise ValueError('Partial model file exceeds pinned size')
            while (partial.stat().st_size if partial.exists() else 0) < size:
                if disk_stop_reason(disk_resources(root)):
                    raise RuntimeError('Research disk budget stop')
                start = partial.stat().st_size if partial.exists() else 0
                end = min(size - 1, start + 32 * 1024**2 - 1)
                headers = {'Accept-Encoding': 'identity'}
                is_weight = name == 'model.safetensors'
                if is_weight:
                    headers['Range'] = f'bytes={start}-{end}'
                elif start:
                    raise RuntimeError('Small file transfer incomplete; preserve evidence and inspect before retry')
                with get(session, url + '?download=true&range_start=' + str(start), headers) as response:
                    if is_weight:
                        match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
                        if response.status_code != 206 or not match or tuple(map(int, match.groups())) != (start, end, size):
                            raise RuntimeError('Server did not honor exact immutable range')
                    elif response.status_code != 200:
                        raise RuntimeError('Unexpected small model file response')
                    total = 0
                    with partial.open('ab') as output:
                        for chunk in response.iter_content(1024 * 1024):
                            total += len(chunk)
                            if total > end - start + 1:
                                raise RuntimeError('Server sent more bytes than pinned range')
                            output.write(chunk)
                    if total != end - start + 1:
                        raise RuntimeError('Truncated range; preserve partial and stop')
                print(json.dumps({'file': name, 'verified_range_end': end}), flush=True)
            check_file(partial, size, digest)
            partial.replace(target)
        records.append({'name': name, 'bytes': size, 'sha256': digest, 'official_revision_url': url})
    session.close()
    marker = root / 'metadata/model-file-lock.json'
    result = {'status': 'verified_fixed_files', 'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
              'model_id': MODEL_ID, 'revision': REVISION, 'license': 'Apache-2.0', 'files': records,
              'trust_remote_code': False, 'pickle_files_downloaded': False, 'credentials_used': False,
              'paid_api_called': False, 'economic_data_uploaded': False, 'disk': disk_resources(root)}
    if not args.verify_only and not marker.exists():
        with marker.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    elif marker.exists():
        existing = json.loads(marker.read_text(encoding='utf-8'))
        if existing['status'] != 'verified_fixed_files' or existing['revision'] != REVISION:
            raise ValueError('Existing model marker disagrees with pinned revision')
    print(json.dumps({'status': 'passed', 'files': records, 'model_executed': False, 'verify_only': args.verify_only}), flush=True)


if __name__ == '__main__':
    main()
