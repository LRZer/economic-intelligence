"""Read-only publication audit; never rewrite the approved data manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[1]
FROZEN_PROTOCOL='research/chronos/PROTOCOL.md'
FROZEN_SHA='124637cf3634ab97fb2084daea2aa87cd991ca3ef138e2b7afe767c49f4e5d74'
TEXT={'.py','.md','.toml','.json','.jsonl','.yaml','.yml','.html','.txt','.js','.css','.example','.xml','.log','.csv','.svg'}


def audit(root: Path, names: list[str], *, allow_frozen_task_paths: bool=False) -> dict:
    root=root.resolve();issues=[];data=[];total=0;exceptions=[]
    token=re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{35,}|sk-[A-Za-z0-9]{32,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')
    personal=re.compile(r'[CD]:\\(?:Users\\Lenovo|Documents\\ChatGPT)')
    for name in names:
        path=root/name
        if not path.resolve().is_relative_to(root):issues.append({'file':name,'reason':'resolved path outside repository'});continue
        if not path.is_file():issues.append({'file':name,'reason':'tracked file unavailable; sparse audit is incomplete'});continue
        size=path.stat().st_size;total+=size
        if path.name in {'.env','secrets.toml'} or path.suffix.lower() in {'.pem','.p12','.sqlite3'} or '.local.' in path.name:
            issues.append({'file':name,'reason':'private runtime or credential file'})
        if name.startswith(('data/china/','data/private/','.venv/','output/','reports/')):issues.append({'file':name,'reason':'runtime/local directory tracked'})
        if size>100*1024**2:issues.append({'file':name,'reason':'exceeds GitHub single-file size limit'})
        if path.suffix.lower() in TEXT:
            text=path.read_text(encoding='utf-8',errors='replace')
            if token.search(text):issues.append({'file':name,'reason':'credential-shaped content; value withheld'})
            if personal.search(text):
                permitted=allow_frozen_task_paths and name==FROZEN_PROTOCOL and hashlib.sha256(path.read_bytes()).hexdigest()==FROZEN_SHA
                if permitted:exceptions.append({'file':name,'sha256':FROZEN_SHA,'reason':'explicit private audit of unchanged pre-execution scientific protocol'})
                else:issues.append({'file':name,'reason':'personal local source path'})
        if name.startswith(('data/','src/china_macro/bundled_snapshots/')):
            with path.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
            data.append({'file':name,'bytes':size,'sha256':digest})
    approved_path=root/'docs/data-file-manifest.json'
    if approved_path.is_file():
        approved=json.loads(approved_path.read_text(encoding='utf-8'))
        if sorted(data,key=lambda r:r['file'])!=sorted(approved,key=lambda r:r['file']):issues.append({'file':'docs/data-file-manifest.json','reason':'actual publication data differs from approved manifest'})
    else:issues.append({'file':'docs/data-file-manifest.json','reason':'approved manifest unavailable'})
    return {'status':'passed' if not issues else 'failed','tracked_files':len(names),'tracked_bytes':total,
            'data_files':len(data),'data_bytes':sum(r['bytes'] for r in data),'approved_manifest_rewritten':False,
            'explicit_frozen_path_exceptions':exceptions,'issues':issues,
            'limits':'Heuristic shape/path audit; cannot prove absence of all secrets. Matched content withheld. No source or approved manifest writes.'}


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--allow-frozen-task-paths',action='store_true',help='Private repository only: exact unchanged Chronos protocol SHA')
    parser.add_argument('--output',type=Path,help='Optional JSON receipt within ignored reports/')
    args=parser.parse_args()
    names=subprocess.run(['git','-c','safe.directory='+ROOT.as_posix(),'ls-files','-z'],cwd=ROOT,capture_output=True,check=True).stdout.decode('utf-8').split('\0')
    result=audit(ROOT,[n for n in names if n],allow_frozen_task_paths=args.allow_frozen_task_paths)
    if args.output:
        destination=(ROOT/args.output).resolve()
        if not destination.is_relative_to((ROOT/'reports').resolve()):raise ValueError('Audit output must remain within ignored reports/')
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
