import config, os, urllib.request, json
key = os.environ.get("XAI_API_KEY","").strip()
req = urllib.request.Request(
    "https://api.x.ai/v1/models",
    headers={"Authorization": f"Bearer {key}"},
)
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read())
    print("KEY WORKS. Models available:")
    for m in data.get("data", []):
        print("  ", m.get("id"))
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read().decode()[:200])
