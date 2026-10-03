"""Export model evidence without network or paid API calls."""
import argparse
import json
import platform
import sys
from pathlib import Path
from importlib.metadata import version

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from china_macro import app
from guanlan.forecast import MODEL_KEYS, analyze_series, anomaly
import pandas as pd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("reports/china-ai.json"))
    args = parser.parse_args()
    app.initialize()
    data = app.dashboard()
    result = {"python": platform.python_version(), "packages": {k:version(k) for k in ("numpy","scikit-learn","pandas")},
              "data_snapshot_hash":data["snapshot_hash"], "captured_at":data["demo_captured_at"], "indicators":{}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for key in MODEL_KEYS:
        rows = data["series"].get(key, [])
        model = analyze_series(rows)
        result["indicators"][key] = {"model":model, "anomaly":anomaly(rows)}
        if model.get("backtest"):
            pd.DataFrame(model["backtest"]).to_csv(args.output.parent/f"backtest-{key}.csv", index=False)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k:{"status":v["model"]["status"], "metrics":v["model"].get("metrics",{}).get("test"),
                          "passes_gate":v["model"].get("passes_research_gate")} for k,v in result["indicators"].items()}))


if __name__ == "__main__":
    main()
