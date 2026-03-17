"""Small deterministic CLI ingested by the scaffold-command example."""

from __future__ import annotations

import argparse
import json


def main() -> None:
    """Parse CLI inputs and print a deterministic JSON payload."""
    parser = argparse.ArgumentParser(description="Deterministic beam CLI.")
    parser.add_argument("job_name", help="Job label.")
    parser.add_argument("--scale", type=float, default=1.0, help="Scale factor.")
    parser.add_argument("--verbose", action="store_true", help="Verbose mode.")
    args = parser.parse_args()
    print(json.dumps({"job_name": args.job_name, "scale": args.scale, "verbose": args.verbose}))


if __name__ == "__main__":
    main()
