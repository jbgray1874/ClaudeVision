import os, json, config  # config sources the keys into the env
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError

key = os.environ.get("GOOGLE_CSE_API_KEY", "")
cx  = os.environ.get("GOOGLE_CSE_CX", "")
print("key set:", bool(key), "(len", len(key), ") | cx:", (cx[:6] + "…") if cx else "MISSING")

url = "https://www.googleapis.com/customsearch/v1?" + urlencode(
    {"key": key, "cx": cx, "q": "test", "num": 3}
)
try:
    with urlopen(Request(url), timeout=20) as resp:
        data = json.loads(resp.read().decode())
        print("OK — items returned:", len(data.get("items", [])))
except HTTPError as e:
    print("HTTP", e.code)
    print(e.read().decode("utf-8", "replace"))   # <-- the reason lives here
except URLError as e:
    print("URLError:", e)