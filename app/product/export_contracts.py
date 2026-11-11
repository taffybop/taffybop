"""Regenerate the reviewed PX1 JSON Schema snapshot without contacting providers."""

import json
from pathlib import Path

from app.product.contracts import contract_schema


def serialized_schema() -> str:
    return json.dumps(contract_schema(), indent=2, sort_keys=True) + "\n"


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[2] / "tracker/parse-extract-v1/contracts/v2.schema.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(serialized_schema(), encoding="utf-8")
    print(target.relative_to(Path(__file__).resolve().parents[2]))
