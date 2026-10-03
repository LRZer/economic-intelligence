import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

import guanlan.data as data
from guanlan.data import (
    load_snapshot, normalize_comtrade_records, normalize_wdi_records,
    publish_snapshots, refresh_audit, save_snapshot, snapshot_catalog,
    restore_batch,
)


COUNTRIES = {"CHN": {"name": "China", "region": "East Asia", "income_level": "Upper middle"}}


def test_wdi_excludes_aggregate_and_preserves_missing_observation():
    records = [
        {"countryiso3code": "CHN", "indicator": {"id": "NY.GDP.MKTP.CD"}, "date": "2024", "value": None},
        {"countryiso3code": "WLD", "indicator": {"id": "NY.GDP.MKTP.CD"}, "date": "2024", "value": 1},
    ]
    result = normalize_wdi_records(records, COUNTRIES)
    assert len(result) == 1
    assert result.loc[0, "country_code"] == "CHN"
    assert pd.isna(result.loc[0, "value"])


def test_wdi_duplicate_key_is_rejected():
    record = {"countryiso3code": "CHN", "indicator": {"id": "NY.GDP.MKTP.CD"}, "date": "2024", "value": 1}
    with pytest.raises(ValueError, match="重复"):
        normalize_wdi_records([record, record], COUNTRIES)


def _trade_record(partner_code, partner_iso, value):
    return {
        "cmdCode": "TOTAL", "partnerCode": partner_code, "partner2Code": 0,
        "customsCode": "C00", "motCode": 0, "partnerISO": partner_iso,
        "primaryValue": value, "reporterISO": "CHN", "reporterDesc": "China",
        "partnerDesc": partner_iso, "refYear": 2024, "flowCode": "X",
    }


def test_trade_excludes_world_total_to_prevent_double_counting():
    frame = normalize_comtrade_records(
        [_trade_record(0, "W00", 500), _trade_record(842, "USA", 200), _trade_record(276, "DEU", 100)]
    )
    assert len(frame) == 2
    assert frame.trade_usd.sum() == 300


def test_trade_duplicate_partner_is_rejected():
    row = _trade_record(842, "USA", 200)
    with pytest.raises(ValueError, match="重复"):
        normalize_comtrade_records([row, row])


def test_snapshot_checksum_detects_parquet_and_metadata_mismatch(tmp_path):
    frame = pd.DataFrame({"value": [1.0, 2.0]})
    save_snapshot(frame, {"provider": "test"}, "sample", tmp_path)
    loaded, metadata = load_snapshot("sample", tmp_path)
    assert loaded.equals(frame)
    assert len(metadata["parquet_sha256"]) == 64
    with (tmp_path / "sample.parquet").open("ab") as handle:
        handle.write(b"corruption")
    with pytest.raises(ValueError, match="校验失败"):
        load_snapshot("sample", tmp_path)


def test_batch_publication_switches_all_snapshots_and_preserves_prior_release(tmp_path):
    initial = {"macro": (pd.DataFrame({"value": [1]}), {"rows": 1}),
               "us_monthly": (pd.DataFrame({"value": [10]}), {"rows": 1})}
    first = publish_snapshots(initial, tmp_path, operation="test")
    old_catalog = snapshot_catalog(tmp_path)
    assert set(old_catalog) == {"macro", "us_monthly"}
    assert all(first in path for path in old_catalog.values())
    assert load_snapshot("macro", tmp_path)[0].value.iloc[0] == 1
    assert load_snapshot("us_monthly", tmp_path)[0].value.iloc[0] == 10

    publish_snapshots({"macro": (pd.DataFrame({"value": [2]}), {"rows": 1})}, tmp_path, operation="test")
    assert load_snapshot("macro", tmp_path)[0].value.iloc[0] == 2
    assert load_snapshot("us_monthly", tmp_path)[0].value.iloc[0] == 10
    assert load_snapshot("macro", tmp_path, old_catalog)[0].value.iloc[0] == 1
    audit = refresh_audit(tmp_path)
    assert audit.status.tolist() == ["published", "published"]
    assert audit.previous.iloc[0] == {"macro": old_catalog["macro"]}


def test_failed_batch_keeps_both_active_snapshots_and_records_failure(tmp_path, monkeypatch):
    old = {"macro": (pd.DataFrame({"value": [1]}), {"rows": 1}),
           "us_monthly": (pd.DataFrame({"value": [10]}), {"rows": 1})}
    publish_snapshots(old, tmp_path, operation="seed")
    before = snapshot_catalog(tmp_path)
    original_save = data.save_snapshot

    def fail_second(frame, metadata, stem, directory):
        if stem == "macro":
            raise IOError("模拟第二份快照写入失败")
        return original_save(frame, metadata, stem, directory)

    monkeypatch.setattr(data, "save_snapshot", fail_second)
    with pytest.raises(IOError, match="模拟第二份"):
        publish_snapshots({"us_monthly": (pd.DataFrame({"value": [20]}), {"rows": 1}),
                           "macro": (pd.DataFrame({"value": [2]}), {"rows": 1})},
                          tmp_path, operation="test_failure")
    assert snapshot_catalog(tmp_path) == before
    assert load_snapshot("macro", tmp_path)[0].value.iloc[0] == 1
    assert load_snapshot("us_monthly", tmp_path)[0].value.iloc[0] == 10
    assert refresh_audit(tmp_path).status.iloc[0] == "failed"
    assert not list(tmp_path.glob(".staging-*"))
    assert len(list((tmp_path / "releases").iterdir())) == 1


def test_catalog_failure_after_staging_does_not_switch_snapshot(tmp_path, monkeypatch):
    publish_snapshots({"macro": (pd.DataFrame({"value": [1]}), {"rows": 1})}, tmp_path)
    before = snapshot_catalog(tmp_path)
    real_connect = data.sqlite3.connect
    calls = 0

    def fail_first_connection(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise data.sqlite3.OperationalError("模拟目录提交失败")
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(data.sqlite3, "connect", fail_first_connection)
    with pytest.raises(data.sqlite3.OperationalError, match="模拟目录提交失败"):
        publish_snapshots({"macro": (pd.DataFrame({"value": [2]}), {"rows": 1})}, tmp_path)
    assert snapshot_catalog(tmp_path) == before
    assert load_snapshot("macro", tmp_path)[0].value.iloc[0] == 1
    assert refresh_audit(tmp_path).status.iloc[0] == "failed"
    assert len(list((tmp_path / "releases").iterdir())) == 1


def test_rollback_restores_prior_batch_and_refuses_partially_superseded_batch(tmp_path):
    save_snapshot(pd.DataFrame({"value": [0]}), {"rows": 1}, "macro", tmp_path)
    save_snapshot(pd.DataFrame({"value": [9]}), {"rows": 1}, "us_monthly", tmp_path)
    first = publish_snapshots({"macro": (pd.DataFrame({"value": [1]}), {"rows": 1}),
                               "us_monthly": (pd.DataFrame({"value": [10]}), {"rows": 1})}, tmp_path)
    second = publish_snapshots({"macro": (pd.DataFrame({"value": [2]}), {"rows": 1})}, tmp_path)
    with pytest.raises(ValueError, match="后续刷新"):
        restore_batch(first, tmp_path)
    restore_batch(second, tmp_path)
    assert load_snapshot("macro", tmp_path)[0].value.iloc[0] == 1
    assert refresh_audit(tmp_path).status.iloc[0] == "restored"
    restore_batch(first, tmp_path)
    assert load_snapshot("macro", tmp_path)[0].value.iloc[0] == 0
    assert "macro" not in snapshot_catalog(tmp_path)
    assert "us_monthly" not in snapshot_catalog(tmp_path)


def test_refresh_cli_audits_source_failure_without_publishing(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / "refresh_data.py"
    result = subprocess.run(
        [sys.executable, str(script), "--macro-only", "--start", "2025", "--end", "2024",
         "--directory", str(tmp_path)], capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert result.returncode != 0
    assert snapshot_catalog(tmp_path) == {}
    audit = refresh_audit(tmp_path)
    assert audit.status.tolist() == ["failed"]
    assert audit.stems.iloc[0] == ["macro"]
    assert "开始年份" in audit.error.iloc[0]
