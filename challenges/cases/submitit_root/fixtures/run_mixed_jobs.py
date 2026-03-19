"""Run tiny DebugExecutor, LocalExecutor, and AutoExecutor jobs."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import submitit

root = Path(sys.argv[1])
summary = dict()
for name in ["debug", "local", "auto"]:
    (root / name).mkdir(parents=True, exist_ok=True)

debug_job = submitit.DebugExecutor(folder=root / "debug").submit(str.upper, "hello")
summary["debug_result"] = debug_job.result()
debug_files = sorted(path.name for path in (root / "debug").iterdir())
(root / "debug_files.txt").write_text("\\n".join(debug_files) + "\\n", encoding="utf-8")
summary["debug_files"] = debug_files

local = submitit.LocalExecutor(folder=root / "local")
local.update_parameters(timeout_min=1)
local_job = local.submit(sum, [1, 2, 3])
summary["local_result"] = local_job.result()
local_files = sorted(path.name for path in (root / "local").iterdir())
(root / "local_files.txt").write_text("\\n".join(local_files) + "\\n", encoding="utf-8")
summary["local_files"] = local_files

auto = submitit.AutoExecutor(folder=root / "auto", cluster="local")
auto.update_parameters(timeout_min=1)
auto_job = auto.submit(max, [3, 8, 5])
summary["auto_result"] = auto_job.result()
auto_files = sorted(path.name for path in (root / "auto").iterdir())
(root / "auto_files.txt").write_text("\\n".join(auto_files) + "\\n", encoding="utf-8")
summary["auto_files"] = auto_files
(root / "mixed_summary.json").write_text(
    json.dumps(summary, indent=2) + "\\n",
    encoding="utf-8",
)
print(summary["debug_result"])
print(summary["local_result"])
print(summary["auto_result"])
