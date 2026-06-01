import requests

query = """[out:json][timeout:180];
(
  way["name"="长江"]["waterway"="river"](18,73,54,135);
);
out geom;"""

url = "https://overpass-api.de/api/interpreter"
res = requests.post(url, data={"data": query})
print("STATUS:", res.status_code)
print("CONTENT:", res.text[:500])
