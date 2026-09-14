"""Shift normalized JSON/GeoJSON fixture timestamps onto the current demo timeline."""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any


TIME_KEYS = {"issued_date", "valid_until", "valid_from", "forecast_time", "observed_at"}


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _format(original: str, value: datetime) -> str:
    if "T" not in original:
        return value.date().isoformat()
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _timestamps(value: Any) -> list[datetime]:
    if isinstance(value, dict):
        result: list[datetime] = []
        for key, child in value.items():
            if key in TIME_KEYS and isinstance(child, str):
                try:
                    result.append(_parse(child))
                except ValueError:
                    pass
            result.extend(_timestamps(child))
        return result
    if isinstance(value, list):
        result = []
        for child in value:
            result.extend(_timestamps(child))
        return result
    return []


def _shift(value: Any, offset: timedelta) -> Any:
    if isinstance(value, dict):
        return {key: _format(child, _parse(child) + offset) if key in TIME_KEYS and isinstance(child, str) and _is_time(child) else _shift(child, offset) for key, child in value.items()}
    if isinstance(value, list):
        return [_shift(child, offset) for child in value]
    return value


def _is_time(value: str) -> bool:
    try:
        _parse(value)
        return True
    except ValueError:
        return False


def shift_directory(input_dir: Path, output_dir: Path, target_date: date) -> timedelta:
    paths = sorted(input_dir.glob("*.json"))
    all_times: list[datetime] = []
    payloads: list[tuple[Path, Any]] = []
    for path in paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        payloads.append((path, payload))
        all_times.extend(_timestamps(payload))
    if not all_times:
        raise ValueError(f"No supported timestamps found in {input_dir}")
    offset = datetime.combine(target_date, datetime.min.time(), tzinfo=timezone.utc) - min(all_times)
    output_dir.mkdir(parents=True, exist_ok=True)
    for path, payload in payloads:
        destination = output_dir / path.name
        destination.write_text(json.dumps(_shift(payload, offset), indent=2) + "\n", encoding="utf-8")
    return offset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target-date", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    offset = shift_directory(args.input_dir, args.output_dir, args.target_date)
    print(f"Shifted {len(list(args.input_dir.glob('*.json')))} fixture files by {offset} into {args.output_dir}.")


if __name__ == "__main__":
    main()