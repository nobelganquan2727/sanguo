import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"


def protagonist_from_path(path: Path) -> str:
    return path.name.removesuffix("_events.json")


def normalize_people(value) -> list[str]:
    if isinstance(value, list):
        return [str(person).strip() for person in value if str(person).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def fix_file(path: Path, dry_run: bool = False) -> int:
    protagonist = protagonist_from_path(path)
    events = json.loads(path.read_text(encoding="utf-8"))
    changed = 0

    for event in events:
        people = normalize_people(event.get("相关人物"))
        if protagonist not in people:
            event["相关人物"] = [protagonist, *people]
            changed += 1
        elif event.get("相关人物") != people:
            event["相关人物"] = people
            changed += 1

    if changed and not dry_run:
        path.write_text(json.dumps(events, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return changed


def main() -> None:
    total_files = 0
    total_events = 0

    for path in sorted(RAW_DIR.glob("*_events.json")):
        changed = fix_file(path)
        if changed:
            total_files += 1
            total_events += changed
            print(f"{path.relative_to(ROOT)}: fixed {changed} events")

    print(f"\nDone. Fixed {total_events} events across {total_files} files.")


if __name__ == "__main__":
    main()
