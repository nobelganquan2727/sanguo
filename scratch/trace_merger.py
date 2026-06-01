import requests
import json
import math

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
    print("Could not retrieve data.")
    exit(1)

elements = data["elements"]

paths = []
for elem in elements:
    name = elem.get("tags", {}).get("name", "No Name")
    # Exclude noise named 通天河 that's too far east
    if name == "通天河":
        geometry = elem.get("geometry", [])
        if geometry and geometry[0]["lon"] > 105:
            continue
    if "geometry" in elem:
        coords = [[pt["lon"], pt["lat"]] for pt in elem["geometry"]]
        paths.append((name, coords))

print(f"Total paths: {len(paths)}")

def dist(p1, p2):
    return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)

# Run merger with tracing
unmerged = list(paths)
longest_idx = max(range(len(unmerged)), key=lambda idx: len(unmerged[idx][1]))
start_name, current = unmerged.pop(longest_idx)
current = list(current)
print(f"Starting merging with longest segment: {start_name}, length {len(current)} points.")
print(f"Current endpoints: Start {current[0]}, End {current[-1]}")

merged_names = [start_name]

step = 0
while unmerged:
    best_dist = float('inf')
    best_idx = -1
    reverse_other = False
    append_to_end = True
    
    for i, (name, other) in enumerate(unmerged):
        # Case 1: current end to other start
        d1 = dist(current[-1], other[0])
        if d1 < best_dist:
            best_dist = d1
            best_idx = i
            reverse_other = False
            append_to_end = True
            
        # Case 2: current end to other end
        d2 = dist(current[-1], other[-1])
        if d2 < best_dist:
            best_dist = d2
            best_idx = i
            reverse_other = True
            append_to_end = True
            
        # Case 3: other end to current start
        d3 = dist(other[-1], current[0])
        if d3 < best_dist:
            best_dist = d3
            best_idx = i
            reverse_other = False
            append_to_end = False
            
        # Case 4: other start to current start
        d4 = dist(other[0], current[0])
        if d4 < best_dist:
            best_dist = d4
            best_idx = i
            reverse_other = True
            append_to_end = False

    # A threshold of 1.2 degrees (~120km)
    if best_idx != -1 and best_dist < 1.2:
        step += 1
        name, other = unmerged.pop(best_idx)
        other_path = list(reversed(other)) if reverse_other else other
        
        merged_names.append(name)
        if append_to_end:
            current.extend(other_path[1:])
        else:
            current = other_path[:-1] + current
    else:
        print(f"Stopping merger. Closest remaining distance was {best_dist} at index {best_idx}.")
        if best_idx != -1:
            name, other = unmerged[best_idx]
            print(f"Closest segment name: {name}, points: {other[0]} to {other[-1]}")
        break

print(f"Merging finished. Merged path has {len(current)} points.")
print(f"Final bounds: lon ({current[0][0]:.4f} to {current[-1][0]:.4f}), lat ({current[0][1]:.4f} to {current[-1][1]:.4f})")
print("Unique names in merged path:", set(merged_names))
