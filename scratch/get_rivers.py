import requests
import json
import math
import sys

def rdp(points, epsilon):
    """Ramer-Douglas-Peucker simplification algorithm."""
    if len(points) < 3:
        return points

    dmax = 0
    index = 0
    end = len(points) - 1
    for i in range(1, end):
        d = perpendicular_distance(points[i], points[0], points[end])
        if d > dmax:
            index = i
            dmax = d

    if dmax > epsilon:
        recResults1 = rdp(points[:index+1], epsilon)
        recResults2 = rdp(points[index:], epsilon)
        return recResults1[:-1] + recResults2
    else:
        return [points[0], points[end]]

def perpendicular_distance(p, a, b):
    if a[0] == b[0] and a[1] == b[1]:
        return math.sqrt((p[0] - a[0])**2 + (p[1] - a[1])**2)
    A = b[1] - a[1]
    B = a[0] - b[0]
    C = b[0]*a[1] - a[0]*b[1]
    return abs(A*p[0] + B*p[1] + C) / math.sqrt(A**2 + B**2)

def fetch_river_osm(name_zh, name_en):
    print(f"Fetching {name_zh} / {name_en}...")
    
    if name_zh == "黄河":
        query_ways = f"""[out:json][timeout:180];
        (
          way["name"="黄河"]["waterway"="river"](18,73,54,135);
          way["name:en"="Yellow River"]["waterway"="river"](18,73,54,135);
          way["name"="Huang He"]["waterway"="river"](18,73,54,135);
          way["name"="Yellow River"]["waterway"="river"](18,73,54,135);
        );
        out geom;"""
    else: # 长江
        query_ways = f"""[out:json][timeout:180];
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
        "https://overpass.nchc.org.tw/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://lz4.overpass-api.de/api/interpreter",
        "https://z.overpass-api.de/api/interpreter",
        "https://overpass-api.de/api/interpreter"
    ]
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Origin": "https://overpass-turbo.eu",
        "Referer": "https://overpass-turbo.eu/"
    }
    
    data = None
    # Query ways directly to ensure we pull all segments and synonyms (e.g. Jinsha River / headwaters)
    print("Directly querying ways (including synonyms and headwaters)...")
    for url in mirrors:
        try:
            print(f"Trying ways query on mirror: {url}")
            response = requests.post(url, data={"data": query_ways}, headers=headers, timeout=40)
            if response.status_code == 200:
                data = response.json()
                if data.get("elements"):
                    print("Successfully retrieved ways data!")
                    break
            else:
                print(f"Mirror {url} returned status code {response.status_code}")
        except Exception as e:
            print(f"Mirror {url} failed: {e}")

    if not data or not data.get("elements"):
        print(f"Could not retrieve any data for {name_zh}")
        return None
        
    elements = data["elements"]
    print(f"Found {len(elements)} elements for {name_zh}")
    
    paths = []
    for elem in elements:
        if "geometry" in elem:
            coords = [[pt["lon"], pt["lat"]] for pt in elem["geometry"]]
            paths.append(coords)
        elif "members" in elem:
            for member in elem["members"]:
                if member["type"] == "way" and "geometry" in member:
                    coords = [[pt["lon"], pt["lat"]] for pt in member["geometry"]]
                    paths.append(coords)
                    
    if not paths:
        print("No coordinate paths extracted")
        return None
        
    print(f"Extracted {len(paths)} segment paths. Merging...")
    merged_paths = merge_segments(paths)
    print(f"Merged into {len(merged_paths)} continuous paths.")
    
    merged_paths.sort(key=len, reverse=True)
    main_path = merged_paths[0]
    
    if main_path[0][0] > main_path[-1][0]:
        main_path.reverse()
        
    print(f"Main path has {len(main_path)} points.")
    return main_path

def merge_segments(paths):
    if not paths:
        return []
    
    # Filter out single point noise
    paths = [p for p in paths if len(p) >= 2]
    if not paths:
        return []
        
    unmerged = list(paths)
    
    # Start with the absolute longest segment (usually the main midstream river bed)
    longest_idx = max(range(len(unmerged)), key=lambda idx: len(unmerged[idx]))
    current = list(unmerged.pop(longest_idx))
    
    while unmerged:
        best_dist = float('inf')
        best_idx = -1
        reverse_other = False
        append_to_end = True
        
        for i, other in enumerate(unmerged):
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
        
        # A threshold of 1.2 degrees (~120km) allows bridging any digital gaps
        # (lakes, dams, missing OSM data segments) without merging separate river systems or jumping.
        if best_idx != -1 and best_dist < 1.2:
            other = unmerged.pop(best_idx)
            other_path = list(reversed(other)) if reverse_other else other
            
            if append_to_end:
                current.extend(other_path[1:])
            else:
                current = other_path[:-1] + current
        else:
            # No close segment found, stop merging
            break
            
    # Return as list of paths (here just one main path) to keep compatibility
    return [current]

def dist(p1, p2):
    return math.sqrt((p1[0] - p2[0])**2 + (p1[1] - p2[1])**2)

def main():
    # Fetch Yangtze River
    yangtze = fetch_river_osm("长江", "Yangtze River")
    if yangtze:
        simplified_yangtze = rdp(yangtze, 0.015)
        print(f"Simplified Yangtze from {len(yangtze)} to {len(simplified_yangtze)} points.")
        with open("/Users/kansen/Documents/Code/Sanguozhi/scratch/yangtze.json", "w") as f:
            json.dump(simplified_yangtze, f)
            
    # Fetch Yellow River
    # yellow = fetch_river_osm("黄河", "Yellow River")
    # if yellow:
    #     simplified_yellow = rdp(yellow, 0.015)
    #     print(f"Simplified Yellow River from {len(yellow)} to {len(simplified_yellow)} points.")
    #     with open("/Users/kansen/Documents/Code/Sanguozhi/scratch/yellow.json", "w") as f:
    #         json.dump(simplified_yellow, f)

if __name__ == "__main__":
    main()
