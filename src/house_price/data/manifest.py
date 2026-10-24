"""Dataset manifest command used by image health/verification steps."""

import argparse
import json
from pathlib import Path

from house_price.data.validation import load_and_validate_snapshot


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("verify",))
    parser.add_argument(
        "--dataset", type=Path, default=Path("/app/data/california_housing.parquet")
    )
    parser.add_argument("--manifest", type=Path, default=Path("/app/data/dataset-manifest.json"))
    args = parser.parse_args()
    _, snapshot = load_and_validate_snapshot(args.dataset, args.manifest)
    print(json.dumps({"status": "valid", **snapshot.__dict__}, default=str, sort_keys=True))


if __name__ == "__main__":
    main()
