"""Kiểm tra tầng 1 – tools/run_experiment.py không ghi đè số liệu cũ (BUG-03, NET-02 AC4)."""

import subprocess
import sys
from pathlib import Path

ROOT = Path (__file__) .resolve () .parent .parent


def test_existing_raw_csv_is_not_overwritten (tmp_path):
    raw = tmp_path / "acc_ref.csv"
    raw .write_text ("so lieu cu\n", encoding = "utf-8")
    summary = tmp_path / "summary.csv"

    result = subprocess .run (
        [sys .executable, str (ROOT / "tools" / "run_experiment.py"),
         "--label", "acc_ref", "--duration", "0.2",
         "--out-dir", str (tmp_path), "--summary-file", str (summary)],
        cwd = ROOT, capture_output = True, text = True, timeout = 30,
    )

    assert result .returncode != 0
    assert raw .read_text (encoding = "utf-8") == "so lieu cu\n"
    assert not summary .exists ()
