import requests
import json

query_ways = """[out:json][timeout:180];
(
  way["name"="长江"]["waterway"="river"](18,73,54,135);
  way["name"="金沙江"]["waterway"="river"](18,73,54,135);
  way["name"="通天河"]["waterway"="river"](18,73,54,135);
  way["name"="沱沱河"]["waterway"="river"](18,73,54,135);
  way["name:en"="Yangtze River"]["waterway"="river"](18,73,54,135);
  way["name:en"="Yangtze"]["waterway"="river"](18,73,54,135);
  way["name"="Yangtze River"]["waterway"="river"](18,73,54,135);
  way["name"="Yangtze"]["waterway"="river"](18,73,54,135);
);
out geom;"""

mirrors = [
    "https://lz4.overpass-api.de/api/interpreter",
    "https://z.overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter"
]

headers = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://overpass-turbo.eu",
    "Referer": "https://overpass-turbo.eu/"
}

data = None
for url in mirrors:
    try:
        print(f"Trying mirror: {url}")
        res = requests.post(url, data={"data": query_ways}, headers=headers, timeout=40)
        if res.status_code == 200:
            data = res.json()
            if data.get("elements"):
                print("Successfully retrieved data!")
                break
    except Exception as e:
        print(f"Mirror failed: {e}")

if not data:
    print("Could not retrieve data from any mirror.")
    exit(1)

elements = data.get("elements", [])
print(f"Total elements: {len(elements)}")

name_counts = {}
for elem in elements:
    name = elem.get("tags", {}).get("name", "No Name")
    name_counts[name] = name_counts.get(name, 0) + 1
print("Name counts:", name_counts)

for target_name in ["长江", "金沙江", "通天河", "沱沱河"]:
    ways = [e for e in elements if e.get("tags", {}).get("name") == target_name]
    print(f"Number of {target_name} ways: {len(ways)}")
    if ways:
        coords = []
        for w in ways:
            if "geometry" in w:
                for pt in w["geometry"]:
                    coords.append((pt["lon"], pt["lat"]))
        lons = [c[0] for c in coords]
        lats = [c[1] for c in coords]
        print(f"  Bounds: lon ({min(lons):.4f} to {max(lons):.4f}), lat ({min(lats):.4f} to {max(lats):.4f})")
