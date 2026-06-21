from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import unicodedata
import uuid
from pathlib import Path


def normalize(keyword: str) -> str:
    return unicodedata.normalize("NFKC", keyword).strip().casefold()


def load_keywords(path: Path) -> list[str]:
    seen: set[str] = set()
    keywords: list[str] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        keyword = line.strip()
        normalized = normalize(keyword)
        if not keyword or keyword.startswith("#") or normalized in seen:
            continue
        seen.add(normalized)
        keywords.append(keyword)
    return keywords


def load_records(path: Path) -> dict:
    if not path.exists():
        return {"version": 1, "used": []}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or not isinstance(data.get("used"), list):
        raise ValueError(f"Invalid used keyword file: {path}")
    return data


def save_records(path: Path, data: dict) -> None:
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def set_output(name: str, value: str) -> None:
    output_path = os.getenv("GITHUB_OUTPUT")
    if not output_path:
        print(f"{name}={value}")
        return
    delimiter = f"KEYWORD_{uuid.uuid4().hex}"
    with Path(output_path).open("a", encoding="utf-8") as output:
        output.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


def claim(args: argparse.Namespace) -> None:
    data_dir = Path(args.data_dir)
    keywords_path = data_dir / "keywords.txt"
    records_path = data_dir / "used_keywords.json"
    if not keywords_path.exists():
        raise FileNotFoundError(f"Private keyword file not found: {keywords_path}")

    keywords = load_keywords(keywords_path)
    records = load_records(records_path)
    used = {
        normalize(str(record.get("keyword", "")))
        for record in records["used"]
        if record.get("keyword")
    }
    keyword = next((item for item in keywords if normalize(item) not in used), None)
    if not keyword:
        set_output("available", "false")
        set_output("keyword", "")
        print(f"No unused keywords remain. Total keywords: {len(keywords)}")
        return

    print(f"::add-mask::{keyword}")
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    records["used"].append(
        {
            "keyword": keyword,
            "status": "claimed",
            "claimed_at": now,
            "completed_at": None,
            "run_id": os.getenv("GITHUB_RUN_ID", ""),
        }
    )
    save_records(records_path, records)
    set_output("available", "true")
    set_output("keyword", keyword)
    print(
        f"Claimed one private keyword. "
        f"Used: {len(records['used'])}/{len(keywords)}"
    )


def complete(args: argparse.Namespace) -> None:
    keyword = args.keyword.strip()
    if not keyword:
        raise ValueError("Keyword is required.")
    print(f"::add-mask::{keyword}")
    records_path = Path(args.data_dir) / "used_keywords.json"
    records = load_records(records_path)
    target = normalize(keyword)
    for record in reversed(records["used"]):
        if normalize(str(record.get("keyword", ""))) == target:
            record["status"] = "completed"
            record["completed_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            save_records(records_path, records)
            print("Marked the private keyword as completed.")
            return
    raise ValueError("Claimed keyword was not found in the private record.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage private keyword records.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    claim_parser = subparsers.add_parser("claim")
    claim_parser.add_argument("--data-dir", default=".private-keywords")
    claim_parser.set_defaults(func=claim)

    complete_parser = subparsers.add_parser("complete")
    complete_parser.add_argument("--data-dir", default=".private-keywords")
    complete_parser.add_argument("--keyword", required=True)
    complete_parser.set_defaults(func=complete)

    args = parser.parse_args()
    args.func(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
