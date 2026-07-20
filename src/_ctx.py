L = open(r"C:\ClaudeVision\src\file_scan.py", encoding="utf-8").read().splitlines()
for i in range(1599, 1660):
    print(f"{i+1}|{L[i]}")
