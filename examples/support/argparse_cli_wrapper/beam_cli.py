"""Small deterministic CLI used by the argparse wrapper example."""

from __future__ import annotations

import argparse
import json


def main() -> None:
    """Parse CLI inputs and print a deterministic JSON payload."""
    parser = argparse.ArgumentParser(description="Beam post-processor.")
    parser.add_argument("case_name")
    parser.add_argument("--scale", type=float, default=1.0)
    parser.add_argument("--export-vtk", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            {
                "case_name": args.case_name,
                "export_vtk": args.export_vtk,
                "scale": args.scale,
                "stress_limit": round(125.0 * args.scale, 3),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
