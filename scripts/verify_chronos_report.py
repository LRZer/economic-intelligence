"""Recompute data, chronology, baselines and metrics from saved quantiles."""
from __future__ import annotations

import argparse
import hashlib
from importlib.resources import files
import json
from pathlib import Path

from guanlan.chronos_report import PROTOCOL_SHA, strict_json, verify_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    try:
        if args.report.stat().st_size > 2 * 1024 * 1024:
            raise ValueError
        value = strict_json(args.report.read_bytes())
        packaged = files('guanlan').joinpath('resources/chronos-synth-v1/protocol.json').read_bytes()
        if hashlib.sha256(packaged).hexdigest() != PROTOCOL_SHA:
            raise ValueError
        protocol = strict_json(packaged)
        report = value['report'] if value.get('version') == 'chronos-synth-review-v1' else value
        if 'protocol' in value and value['protocol'] != protocol:
            raise ValueError
        source = files('china_macro').joinpath('demo_data.json').read_bytes()
        result = verify_report(report, protocol, source)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, RecursionError):
        print(json.dumps({'status': 'failed', 'reason': '文件、完整性、冻结数据、基线或指标无法核验。'}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
