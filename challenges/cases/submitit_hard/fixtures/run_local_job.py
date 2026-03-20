"""Run one tiny LocalExecutor job and write stable summary artifacts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import submitit

root = Path(sys.argv[1])
local_dir = root / "local"
local_dir.mkdir(parents=True, exist_ok=True)
executor = submitit.LocalExecutor(folder=local_dir)
executor.update_parameters(timeout_min=1)
job = executor.submit(sum, [1, 2, 3])
result = job.result()
files = sorted(path.name for path in local_dir.iterdir())
(root / "local_summary.json").write_text(
    json.dumps(dict(result=result, files=files), indent=2) + "\\n",
    encoding="utf-8",
)
(root / "local_files.txt").write_text("\\n".join(files) + "\\n", encoding="utf-8")
print(result)
