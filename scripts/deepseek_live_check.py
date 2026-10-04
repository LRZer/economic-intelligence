"""Default is an offline preview. Only a local human may trigger --live."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import time
from datetime import datetime, timezone

from guanlan.ai import (DEFAULT_DEEPSEEK_MODEL, DEEPSEEK_URL, DeepSeekAPIError,
                        build_grounded_payload, generate_grounded_brief)

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = [{"id": "smoke-test", "label": "人工合成连接测试材料", "period": "TEST-ONLY",
             "value": 1, "unit": "arbitrary_test_unit", "source_url": "https://api-docs.deepseek.com/",
             "kind": "test_fixture"}]
MAX_OUTPUT_TOKENS = 512
INPUT_ESTIMATE_CEILING = 2048
KEY_PATTERN = re.compile(r'(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{16,128}(?![A-Za-z0-9_-])')


class KeyFileError(ValueError):
    pass


def read_key_for_user_triggered_test(path: Path) -> str:
    """Called after local confirmation only; no key in stdout, logs, or config."""
    try:
        if not path.is_file() or path.stat().st_size > 65536:
            raise KeyFileError
        text = path.read_text(encoding='utf-8-sig')
    except (OSError, UnicodeError):
        raise KeyFileError from None
    all_keys = set(KEY_PATTERN.findall(text))
    preferred = set()
    in_deepseek_section = False
    section_level = 0
    for line in text.splitlines():
        heading = re.match(r'^\s*(#{1,6})\s+(.+)', line)
        if heading:
            level, title = len(heading[1]), heading[2].lower()
            if 'deepseek' in title:
                in_deepseek_section, section_level = True, level
            elif level <= section_level:
                in_deepseek_section = False
        if 'deepseek' in line.lower() or in_deepseek_section:
            preferred.update(KEY_PATTERN.findall(line))
    candidates = preferred or all_keys
    if len(candidates) != 1:
        raise KeyFileError
    return next(iter(candidates))


def preview(key_file: Path) -> dict:
    payload, _ = build_grounded_payload(EVIDENCE, model=DEFAULT_DEEPSEEK_MODEL, max_tokens=MAX_OUTPUT_TOKENS)
    content_bytes = sum(len(x['content'].encode('utf-8')) for x in payload['messages'])
    assert content_bytes + 256 <= INPUT_ESTIMATE_CEILING
    return {"status": "not_run", "mode": "offline_preview", "endpoint": DEEPSEEK_URL,
            "model": DEFAULT_DEEPSEEK_MODEL, "request_preview": payload,
            "key_file_exists": key_file.is_file(), "key_file_content_read": False,
            "input_tokens_conservative_estimate": INPUT_ESTIMATE_CEILING,
            "max_output_tokens": MAX_OUTPUT_TOKENS, "max_requests": 1, "automatic_retry": False,
            "estimated_max_usd_at_recorded_peak_rates": round((2048 * .3 + 512 * 1.2) / 1_000_000, 7),
            "price_checked_utc": "2026-10-04", "price_source": "https://api-docs.deepseek.com/quick_start/pricing/",
            "budget_note": "本次累计人民币十元以内已获批准；不充值、不订阅。美元值为当前公开峰值价的估算，不是账单保证。",
            "credentials": "仅在本人本机确认后临时读取桌面api_key.md，使用授权头向固定DeepSeek地址认证；不写环境、配置、日志或报告。"}


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Requires a human confirmation in a local interactive console')
    parser.add_argument('--key-file', type=Path, default=Path.home() / 'Desktop/api_key.md')
    args = parser.parse_args(argv)
    plan = preview(args.key_file)
    if not args.live:
        write_report(ROOT / 'reports/deepseek-preflight.json', plan)
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    output = ROOT / 'reports/deepseek-live-check.json'
    attempt_file = ROOT / 'reports/deepseek-live-attempt.json'
    result = {k: plan[k] for k in ('endpoint', 'model', 'max_output_tokens', 'max_requests', 'automatic_retry',
                                 'estimated_max_usd_at_recorded_peak_rates', 'price_checked_utc', 'price_source')}
    result.update(mode='live', status='blocked', requested_at_utc=datetime.now(timezone.utc).isoformat(),
                  live_request_attempted=False, key_file_read_attempted=False, key_file_parse_succeeded=False, validation_passed=False)
    if attempt_file.exists():
        print('本次一次性测试已有尝试记录，不自动重复或覆盖结果。请核对reports/deepseek-live-check.json。')
        return 2
    if not sys.stdin.isatty():
        print('未发送：必须由本人在本机交互窗口确认。没有读取密钥或改变真实结果文件。')
        return 2
    print('将发送一次DeepSeek测试：人工合成材料，输入保守估计不超过2048 tokens，输出最多512 tokens。')
    print('按当前峰值价格估算不超过0.0013美元；本次总预算人民币10元已批准，不充值、不订阅。')
    print('确认后才临时读取桌面api_key.md，将key作为认证凭据发往api.deepseek.com；不会复制或持久化key。')
    if input('本人按回车发送一次；输入其他内容取消：') != '':
        result['reason'] = 'user_cancelled'
        write_report(output, result)
        print('已取消，没有读取密钥或发送请求。')
        return 2
    api_key = None
    metadata: dict = {}
    previous_flag = os.environ.get('ENABLE_PAID_AI')
    start = time.monotonic()
    try:
        result['key_file_read_attempted'] = True
        api_key = read_key_for_user_triggered_test(args.key_file)
        result['key_file_parse_succeeded'] = True
        attempt_file.parent.mkdir(parents=True, exist_ok=True)
        with attempt_file.open('x', encoding='utf-8') as marker:
            json.dump({'requested_at_utc': result['requested_at_utc'], 'max_requests': 1,
                       'note': 'Reserved before sending; ambiguous failures are not retried.'}, marker)
        os.environ['ENABLE_PAID_AI'] = '1'
        result['live_request_attempted'] = True
        brief = generate_grounded_brief(EVIDENCE, api_key=api_key, model=DEFAULT_DEEPSEEK_MODEL,
                                       max_tokens=MAX_OUTPUT_TOKENS, max_attempts=1, request_metadata=metadata)
        result.update(status='passed', validation_passed=True,
                      checks={'json_structure': True, 'citations_match_synthetic_fixture': True,
                              'synthetic_evidence_not_economic_observation': True,
                              'no_numbers_in_generated_prose': True, 'output_text_not_saved': True})
        result['observation_count'] = len(brief['observations'])
    except KeyFileError:
        result['reason'] = 'key_file_missing_unreadable_or_ambiguous'
    except FileExistsError:
        print('另一个窗口已保留本次尝试；当前窗口不发送，也不覆盖结果。')
        return 2
    except DeepSeekAPIError as error:
        result.update(status='failed', reason=error.category, http_status=error.status_code)
    except ValueError:
        result.update(status='failed', reason='structured_evidence_validation_failed')
    except Exception:
        result.update(status='failed', reason='local_test_error_details_withheld')
    finally:
        api_key = None
        if previous_flag is None:
            os.environ.pop('ENABLE_PAID_AI', None)
        else:
            os.environ['ENABLE_PAID_AI'] = previous_flag
    result.update(http_status=metadata.get('http_status', result.get('http_status')),
                  request_attempts=metadata.get('attempts', 0), usage=metadata.get('usage', {}),
                  elapsed_seconds=round(time.monotonic() - start, 3),
                  may_have_been_billed=bool(result['live_request_attempted']),
                  completed_at_utc=datetime.now(timezone.utc).isoformat())
    write_report(output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'passed' else 2


if __name__ == '__main__':
    raise SystemExit(main())
