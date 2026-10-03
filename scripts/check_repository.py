"""Check tracked publication files for prohibited local materials and obvious credentials."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def check():
    names=subprocess.run(['git','ls-files','-z'],cwd=ROOT,capture_output=True,check=True).stdout.decode('utf-8').split('\0')
    names=[n for n in names if n]
    issues=[];data=[]
    token=re.compile(r'(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{35,}|sk-[A-Za-z0-9]{32,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')
    for name in names:
        path=ROOT/name
        if not path.resolve().is_relative_to(ROOT.resolve()):issues.append({'file':name,'reason':'resolved path outside repository'});continue
        if path.name in {'.env','secrets.toml'} or path.suffix in {'.pem','.p12','.sqlite3'} or '.local.' in path.name:
            issues.append({'file':name,'reason':'private runtime or credential file'})
        if name.startswith(('data/china/','data/private/','.venv/','output/','reports/')):
            issues.append({'file':name,'reason':'runtime/local directory tracked'})
        if path.stat().st_size>100*1024**2:issues.append({'file':name,'reason':'exceeds GitHub single-file size limit'})
        if path.suffix.lower() in {'.py','.md','.toml','.json','.yaml','.yml','.html','.txt','.js','.css','.example','.xml','.log','.csv'}:
            text=path.read_text(encoding='utf-8',errors='replace')
            if token.search(text):issues.append({'file':name,'reason':'credential-shaped content; value deliberately withheld'})
            if re.search(r'[CD]:\\(?:Users\\Lenovo|Documents\\ChatGPT)',text):
                issues.append({'file':name,'reason':'personal local source path'})
        if name.startswith('data/') or name.startswith('src/china_macro/bundled_snapshots/'):
            digest=hashlib.sha256()
            with path.open('rb') as handle:
                for block in iter(lambda:handle.read(1024*1024),b''):digest.update(block)
            data.append({'file':name,'bytes':path.stat().st_size,'sha256':digest.hexdigest()})
    result={'status':'passed' if not issues else 'failed','tracked_files':len(names),
            'tracked_bytes':sum((ROOT/n).stat().st_size for n in names),
            'data_files':len(data),'data_bytes':sum(x['bytes'] for x in data),'issues':issues,
            'limits':'启发式文件/凭据形状检查；不等于证明不存在所有秘密。没有输出任何匹配内容。'}
    (ROOT/'docs/data-file-manifest.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (ROOT/'reports/publication-safety.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))
    if issues:raise SystemExit(1)


if __name__=='__main__':check()
