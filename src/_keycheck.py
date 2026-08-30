import config, os
k = os.environ.get("XAI_API_KEY", "")
print("length:", len(k))
print("starts:", k[:8])
print("ends:", k[-4:])
print("has whitespace:", k != k.strip())
print("has quotes:", k.startswith(("\"","\x27")) or k.endswith(("\"","\x27")))
