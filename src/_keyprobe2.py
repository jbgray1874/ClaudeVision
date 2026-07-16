import os, urllib.request, json
key = "PASTE_THE_OTHER_FULL_KEY_HERE".strip()
req = urllib.request.Request("https://api.x.ai/v1/models",
    headers={"Authorization": f"Bearer {key}"})
try:
    with urllib.request.urlopen(req, timeout=20) as r:
        print("KEY WORKS:", [m["id"] for m in json.loads(r.read()).get("data",[])][:5])
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read().decode()[:150])
