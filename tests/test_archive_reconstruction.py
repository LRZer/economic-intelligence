import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

spec=importlib.util.spec_from_file_location('reconstruct_baci',Path(__file__).resolve().parents[1]/'scripts/reconstruct_baci.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def parts(tmp_path):
    folder=tmp_path/'parts';folder.mkdir()
    blocks=[b'official fixture\x00',b'complete archive bytes']
    items=[]
    for i,block in enumerate(blocks):
        name=f'part{i:03d}';(folder/name).write_bytes(block)
        items.append({'file':name,'bytes':len(block),'sha256':hashlib.sha256(block).hexdigest()})
    content=b''.join(blocks)
    manifest={'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest(),'parts':items}
    (folder/'manifest.json').write_text(json.dumps(manifest),encoding='utf-8')
    return folder,content


def test_reconstruction_exact_idempotent_and_no_overwrite(tmp_path):
    folder,content=parts(tmp_path)
    output=tmp_path/'archive.zip'
    assert module.reconstruct(folder,output).read_bytes()==content
    assert module.reconstruct(folder,output)==output
    output.write_bytes(b'user existing content')
    with pytest.raises(FileExistsError):module.reconstruct(folder,output)
    assert output.read_bytes()==b'user existing content'


def test_corrupt_part_is_rejected_and_only_owned_partial_is_removed(tmp_path):
    folder,_=parts(tmp_path);(folder/'part001').write_bytes(b'corrupted')
    output=tmp_path/'archive.zip'
    with pytest.raises(ValueError,match='SHA256'):module.reconstruct(folder,output)
    assert not output.exists() and not output.with_name(output.name+'.reconstructing').exists()
    partial=output.with_name(output.name+'.reconstructing');partial.write_bytes(b'existing partial')
    with pytest.raises(FileExistsError):module.reconstruct(folder,output)
    assert partial.read_bytes()==b'existing partial'


def test_manifest_traversal_is_rejected(tmp_path):
    folder,_=parts(tmp_path)
    path=folder/'manifest.json';meta=json.loads(path.read_text());meta['parts'][0]['file']='../outside'
    path.write_text(json.dumps(meta),encoding='utf-8')
    with pytest.raises(ValueError,match='越界'):module.reconstruct(folder,tmp_path/'archive.zip')
