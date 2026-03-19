"""Run one tiny DebugExecutor job and write stable summary artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import submitit

root = Path(sys.argv[1])
debug_dir = root / "debug"
debug_dir.mkdir(parents=True, exist_ok=True)
job = submitit.DebugExecutor(folder=debug_dir).submit(str.upper, "hello")
result = job.result()
files = sorted(path.name for path in debug_dir.iterdir())
(root / "debug_summary.json").write_text(
    json.dumps(dict(result=result, files=files), indent=2) + "\\n",
    encoding="utf-8",
)
(root / "debug_files.txt").write_text("\\n".join(files) + "\\n", encoding="utf-8")
print(result)
