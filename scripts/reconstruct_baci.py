"""Reassemble the licensed official BACI ZIP and verify every byte by SHA256."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def reconstruct(directory: Path,output: Path) -> Path:
    manifest=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    def digest(path):
        d=hashlib.sha256()
        with path.open('rb') as handle:
            for block in iter(lambda:handle.read(1024*1024),b''):d.update(block)
        return d.hexdigest()
    if output.exists():
        if output.stat().st_size==manifest['bytes'] and digest(output)==manifest['sha256']:return output
        raise FileExistsError('目标已存在且指纹不匹配，拒绝覆盖')
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_name(output.name+'.reconstructing')
    if temporary.exists():raise FileExistsError('存在未完成的重建文件，先核查后再处理')
    total=hashlib.sha256();size=0
    try:
        with temporary.open('xb') as target:
            for item in manifest['parts']:
                if Path(item['file']).name!=item['file']:raise ValueError('分块路径越界')
                path=directory/item['file']
                part=hashlib.sha256();count=0
                with path.open('rb') as source:
                    for block in iter(lambda:source.read(1024*1024),b''):
                        target.write(block);total.update(block);part.update(block);size+=len(block);count+=len(block)
                if count!=item['bytes'] or part.hexdigest()!=item['sha256']:raise ValueError('分块SHA256或字节数不一致')
        if size!=manifest['bytes'] or total.hexdigest()!=manifest['sha256']:raise ValueError('完整ZIP校验失败')
        os.replace(temporary,output)
    except Exception:
        # Remove only the file exclusively created by this invocation.
        temporary.unlink(missing_ok=True)
        raise
    return output


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,default=Path('data/raw/baci'))
    parser.add_argument('--output',type=Path,default=Path('data/raw/BACI_HS17_V202601.zip'))
    args=parser.parse_args()
    print(reconstruct(args.directory,args.output))
