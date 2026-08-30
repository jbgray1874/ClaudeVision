L = open(r"C:\ClaudeVision\src\estimator.py", encoding="utf-8").read().splitlines()
for i in range(3665, 3685):
    print(f"{i+1}|{L[i]!r}")
