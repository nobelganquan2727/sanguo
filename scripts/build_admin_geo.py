import json
from pathlib import Path


# This one-off migration script has already been run to generate
# frontend/public/eastern_han_admin.json from frontend/public/geo.json.
# If the generated JSON will be maintained directly, this script can be deleted.
ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "frontend" / "public" / "geo.json"
TARGET = ROOT / "frontend" / "public" / "eastern_han_admin.json"


def split_region(region: str) -> tuple[str, str]:
    if not region or region == "不详":
        return "不详", "不详"

    parts = [part.strip() for part in region.split("-", 1)]
    if len(parts) == 1:
        return parts[0] or "不详", "不详"

    province, commandery = parts
    return province or "不详", commandery or "不详"


def has_valid_coordinate(entity: dict) -> bool:
    return isinstance(entity.get("lat"), (int, float)) and isinstance(entity.get("lng"), (int, float))


def commandery_type(name: str) -> str:
    if name.endswith("郡"):
        return "郡"
    if name.endswith("国"):
        return "国"
    if name.endswith("尹"):
        return "尹"
    return "不详"


def average_center(items: list[dict]) -> dict | None:
    points = [
        (item.get("lat"), item.get("lng"))
        for item in items
        if isinstance(item.get("lat"), (int, float)) and isinstance(item.get("lng"), (int, float))
    ]
    if not points:
        return None

    return {
        "lat": round(sum(lat for lat, _ in points) / len(points), 6),
        "lng": round(sum(lng for _, lng in points) / len(points), 6),
        "basis": "children_centroid",
    }


def make_id(*parts: str) -> str:
    return ":".join(part.replace(" ", "") for part in parts if part)


def build_admin_geo() -> dict:
    with SOURCE.open("r", encoding="utf-8") as f:
        raw_geo = json.load(f)

    tree: dict[str, dict] = {}

    for original, entities in raw_geo.items():
        for entity in entities:
            name = entity.get("std_name")
            if not name or name == "不详" or not has_valid_coordinate(entity):
                continue

            province_name, commandery_name = split_region(entity.get("region", ""))
            if province_name == "不详" or commandery_name == "不详":
                continue
            if name == province_name or name == commandery_name:
                continue

            province = tree.setdefault(
                province_name,
                {
                    "id": make_id(province_name),
                    "name": province_name,
                    "level": "province",
                    "center": None,
                    "commanderies": {},
                },
            )
            commandery = province["commanderies"].setdefault(
                commandery_name,
                {
                    "id": make_id(province_name, commandery_name),
                    "name": commandery_name,
                    "level": "commandery",
                    "type": commandery_type(commandery_name),
                    "seat": None,
                    "center": None,
                    "counties": {},
                },
            )

            county_key = name
            county = commandery["counties"].setdefault(
                county_key,
                {
                    "id": make_id(province_name, commandery_name, name),
                    "name": name,
                    "level": "county",
                    "modern": None,
                    "lat": entity.get("lat"),
                    "lng": entity.get("lng"),
                    "aliases": [],
                    "region": entity.get("region", "不详"),
                    "confidence": 0.6,
                },
            )

            if original not in county["aliases"]:
                county["aliases"].append(original)

            if county.get("lat") is None and entity.get("lat") is not None:
                county["lat"] = entity.get("lat")
            if county.get("lng") is None and entity.get("lng") is not None:
                county["lng"] = entity.get("lng")

    provinces = []
    for province in tree.values():
        commanderies = []
        all_counties = []

        for commandery in province["commanderies"].values():
            counties = sorted(commandery["counties"].values(), key=lambda item: item["name"])
            commandery["counties"] = counties
            commandery["center"] = average_center(counties)
            commanderies.append(commandery)
            all_counties.extend(counties)

        province["commanderies"] = sorted(commanderies, key=lambda item: item["name"])
        province["center"] = average_center(all_counties)
        provinces.append(province)

    return {
        "meta": {
            "period": "东汉末年",
            "approxYear": 189,
            "coordinateSystem": "WGS84",
            "source": "Generated from frontend/public/geo.json",
            "note": "此文件由现有事件地名字典自动聚合而来；州郡坐标为子地点中心点均值，适合作为前端层级地图初稿，后续需人工校订。",
        },
        "provinces": sorted(provinces, key=lambda item: item["name"]),
    }


if __name__ == "__main__":
    TARGET.write_text(json.dumps(build_admin_geo(), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {TARGET}")
