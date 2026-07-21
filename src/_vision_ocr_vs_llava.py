r"""READ-ONLY. vision_extraction render feeds OCR (_ocr_page_image), and the module also has Ollama/
llava knobs. Confirm: does the SAME 144-DPI pixmap also feed the llava vision-LLM call, or is that
a separate render/path? And what does _ocr_page_image use (tesseract?) — since OCR is DPI-sensitive
and 300 is the sweet spot. This decides whether bumping line 130 to 300 fixes both OCR and llava, or
just OCR. No edits — then I patch to 300 DPI."""
import re
p=r"C:\ClaudeVision\src\vision_extraction.py"
src=open(p,encoding="utf-8",errors="replace").read()
L=src.splitlines()

print("="*66); print("1 — what _ocr_page_image uses (tesseract/other)"); print("="*66)
m=re.search(r"def _ocr_page_image\b.*?(?=\ndef )", src, re.S)
if m:
    for ln in m.group(0).splitlines()[:25]:
        print("  ", ln.rstrip()[:96])
else:
    print("  _ocr_page_image not found as def — search usages:")
    for i,ln in enumerate(L):
        if "_ocr_page_image" in ln or "tesseract" in ln.lower() or "pytesseract" in ln.lower():
            print(f"    {i+1}: {ln.strip()[:90]}")

print("\n"+"="*66); print("2 — does llava/ollama use the same pixmap or its own render?"); print("="*66)
for i,ln in enumerate(L):
    if re.search(r"(llava|ollama|_ollama|vision.*model|image.*base64|b64encode|encode.*png|tobytes|\.samples|get_pixmap)", ln, re.I):
        print(f"  {i+1}: {ln.strip()[:96]}")

print("\n"+"="*66); print("3 — all get_pixmap calls in the file (how many renders?)"); print("="*66)
for i,ln in enumerate(L):
    if "get_pixmap" in ln:
        print(f"  {i+1}: {ln.strip()[:96]}")

print("\n"+"="*66); print("4 — is there a second image encode for the LLM (separate DPI)?"); print("="*66)
# look for a png/base64 encode path feeding a model
for i,ln in enumerate(L):
    if re.search(r"(base64|b64|\.png|BytesIO|tobytes\(|encode_image|image_to_)", ln):
        print(f"  {i+1}: {ln.strip()[:90]}")
