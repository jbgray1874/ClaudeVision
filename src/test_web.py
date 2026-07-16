import os, config  # importing config runs your os.environ.setdefault lines

print("API key in env:", bool(os.environ.get("GOOGLE_CSE_API_KEY")))
print("CX in env     :", bool(os.environ.get("GOOGLE_CSE_CX")))

from web_search_providers import resolve_search_provider, search_web_result_urls
print("resolved provider:", resolve_search_provider())

r = search_web_result_urls("M8 flanged nutsert price uk", top_n=5)
print("ok:", r["ok"], "| provider:", r["provider"], "| error:", r.get("error"))
print("urls (after domain filter):", r["urls"])
print("hits before filter:", len(r.get("all_hits_before_filter") or []))