"""One isolated answering process: questions in, answers out; no gold access."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from guanlan.evidence_assistant import EvidenceStore, answer_question

ROOT=Path(__file__).resolve().parents[1]


def main():
    request=json.load(sys.stdin)
    store=EvidenceStore(request['source_rows'])
    forbidden=[]
    def audit(event,args):
        if event in {'socket.connect','subprocess.Popen'}:
            forbidden.append(event)
            raise RuntimeError('Worker network/process execution forbidden')
        if event=='open' and args and isinstance(args[0],(str,bytes)):
            name=str(args[0]).lower()
            if any(x in name for x in ('-gold.json','-questions.json','assistant-evaluation-sealed','api_key.md','secrets.toml')):
                forbidden.append('unapproved_file')
                raise RuntimeError('Worker unapproved evaluation/credential file access forbidden')
    sys.addaudithook(audit)
    answers=[]
    for item in request['questions']:
        start=time.perf_counter()
        answer=answer_question(item['question'],store,policy=request['policy'],threshold=request['threshold'])
        answers.append({'id':item['id'],'answer':answer,'latency_ms':round((time.perf_counter()-start)*1000,3)})
    json.dump({'answers':answers,'forbidden_attempts':forbidden,'gold_received':False,'network_requests':0},sys.stdout,ensure_ascii=False)


if __name__=='__main__':main()
