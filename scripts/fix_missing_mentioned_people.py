import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
TEXT_FIELDS = ("事件简介",)
EXCLUDED_NAMES = {
    "乌丸",
    "明帝",
}


def normalize_people(value) -> list[str]:
    if isinstance(value, list):
        return [str(person).strip() for person in value if str(person).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def collect_known_people() -> list[str]:
    names: set[str] = set()

    for path in RAW_DIR.glob("*_events.json"):
        names.add(path.name.removesuffix("_events.json"))

    # Use biography filenames only. Existing related-person fields include titles
    # like "县长" or "刘氏", which are too noisy for substring backfilling.
    return sorted(
        (name for name in names if len(name) >= 2 and "不详" not in name and name not in EXCLUDED_NAMES),
        key=len,
        reverse=True,
    )


def event_text(event: dict) -> str:
    return "\n".join(str(event.get(field, "")) for field in TEXT_FIELDS)


def fix_file(
    path: Path,
    known_people: list[str],
    dry_run: bool = False,
    prune: bool = False,
) -> list[tuple[str, list[str], list[str]]]:
    protagonist = path.name.removesuffix("_events.json")
    events = json.loads(path.read_text(encoding="utf-8"))
    changes: list[tuple[str, list[str], list[str]]] = []
    known_people_set = set(known_people)

    for event in events:
        people = normalize_people(event.get("相关人物"))
        people_set = set(people)
        text = event_text(event)
        missing = []
        for name in known_people:
            if name in people_set:
                continue
            if name in text:
                missing.append(name)

        removed = []
        if prune:
            kept = []
            for person in people:
                should_remove = (
                    person in EXCLUDED_NAMES
                    or (person in known_people_set and person != protagonist and person not in text)
                )
                if should_remove:
                    removed.append(person)
                else:
                    kept.append(person)
            people = kept

        if missing or removed:
            event["相关人物"] = [*people, *missing]
            changes.append((event.get("事件标题", "未命名事件"), missing, removed))

    if changes and not dry_run:
        path.write_text(json.dumps(events, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return changes


def main() -> None:
    parser = argparse.ArgumentParser(description="补全事件文本中提到但未列入相关人物的人名。")
    parser.add_argument("--apply", action="store_true", help="写入修复结果；默认只打印排查结果")
    parser.add_argument("--prune", action="store_true", help="移除不在事件简介里出现的已知人名（主传人物保留）")
    parser.add_argument("--file", help="只检查指定 raw 事件文件，例如 data/raw/典韦_events.json")
    args = parser.parse_args()

    known_people = collect_known_people()
    paths = [ROOT / args.file] if args.file else sorted(RAW_DIR.glob("*_events.json"))
    total_events = 0
    total_people = 0

    for path in paths:
        changes = fix_file(path, known_people, dry_run=not args.apply, prune=args.prune)
        if not changes:
            continue

        total_events += len(changes)
        total_people += sum(len(missing) + len(removed) for _, missing, removed in changes)
        print(f"{path.relative_to(ROOT)}: {len(changes)} events")
        for title, missing, removed in changes[:20]:
            added_text = f"+{', '.join(missing)}" if missing else ""
            removed_text = f"-{', '.join(removed)}" if removed else ""
            print(f"  - {title}: {' '.join(part for part in [added_text, removed_text] if part)}")
        if len(changes) > 20:
            print(f"  ... {len(changes) - 20} more events")

    mode = "Fixed" if args.apply else "Would fix"
    print(f"\n{mode} {total_people} person mentions across {total_events} events.")


if __name__ == "__main__":
    main()
