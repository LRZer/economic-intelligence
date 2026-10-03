"""Runtime storage stays outside the Python package and can be isolated in tests."""
import os
from pathlib import Path

DATA_ROOT = Path(os.getenv("CHINA_DATA_DIR", str(Path(__file__).resolve().parents[2] / "data" / "china")))
