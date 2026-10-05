"""Run synthetic fixtures only; not a real-model or real-data evaluation entry."""
from pathlib import Path
import argparse,json
from chronos_resource_guard import run_fixture


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',choices=['persistence_fixture','slow_fixture','crossed_fixture'],default='persistence_fixture')
    parser.add_argument('--output-name',default='fixture-smoke')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    output=(root/'reports'/args.output_name).resolve()
    if not output.is_relative_to((root/'reports').resolve()) or output==(root/'reports').resolve():
        raise SystemExit('Output must be a new child of the preparation reports directory.')
    protocol=json.loads((root/'protocol.json').read_text(encoding='utf-8'))
    result=run_fixture(protocol,output,backend=args.backend)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    if result['status']!='fixture_complete':raise SystemExit(2)


if __name__=='__main__':main()
