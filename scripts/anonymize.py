"""Anonymize a discovery dump so it can be committed as test fixtures or docs examples.

Reads every .json and .jsonl file in a dump directory, replaces serial numbers, machine names,
emails, tokens and similar with placeholders (consistently across all files), and writes the
result to an output directory. Fails if any original value is still present afterwards.

    uv run python scripts/anonymize.py dumps/20261115-083000 --out tests/fixtures/linea_micra
    uv run python scripts/anonymize.py dumps/... --out ... --redact "My Kitchen" --redact "Emil"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from lamarzocco_mcp.anonymize import Anonymizer


def load(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".jsonl":
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return json.loads(text)


def dump(path: Path, data: Any) -> str:
    if path.suffix == ".jsonl":
        text = "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in data)
    else:
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")
    return text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path, help="dump directory from scripts/discover.py")
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument(
        "--redact",
        action="append",
        default=[],
        metavar="TEXT",
        help="extra text to remove everywhere (repeatable), e.g. your name",
    )
    args = parser.parse_args()

    files = sorted(p for p in args.source.iterdir() if p.suffix in {".json", ".jsonl"})
    if not files:
        print(f"No .json/.jsonl files in {args.source}", file=sys.stderr)
        return 1

    anonymizer = Anonymizer(extra_values=args.redact)
    documents = {path: load(path) for path in files}
    for data in documents.values():
        anonymizer.collect(data)

    args.out.mkdir(parents=True, exist_ok=True)
    leaks: list[str] = []
    for path, data in documents.items():
        target = args.out / path.name
        text = dump(target, anonymizer.apply(data))
        leaks += [f"{target}: {leak}" for leak in anonymizer.leaks(text)]
        print(f"  wrote {target}")

    kinds = sorted({placeholder.rsplit("_", 1)[0] for placeholder in anonymizer.mapping.values()})
    print(f"Replaced {len(anonymizer.mapping)} values ({', '.join(kinds) or 'none'}).")
    if leaks:
        print("Sensitive values are still present:", *leaks, sep="\n  ", file=sys.stderr)
        return 1
    print("Review the output by eye before committing it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
