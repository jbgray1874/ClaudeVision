import config   # <-- loads .env so XAI_API_KEY is in the environment
import os, json
print("XAI key present:", bool(os.environ.get("XAI_API_KEY")))
print("SERP key present:", bool(os.environ.get("SERPAPI_API_KEY")))
from web_ai_price_lookup import lookup_web_ai_price
r = lookup_web_ai_price(
    {"material": "2mm Rubber", "description": "Rubber foot sticker self-adhesive", "quantity": 4},
    enable_web_search=True, enable_llm_estimate=True,
)
print(json.dumps(r, indent=2, default=str))
