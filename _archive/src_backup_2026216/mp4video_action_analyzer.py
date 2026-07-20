import os
# Must be set before importing paddle
os.environ["FLAGS_enable_pir_api"] = "0"
os.environ["FLAGS_use_onednn"] = "0"
os.environ["FLAGS_enable_jit_optim"] = "0"
os.environ["FLAGS_enable_new_executor"] = "0"

import sys
import cv2
import paddle
from paddleocr import PaddleOCR

# Force CPU
paddle.device.set_device("cpu")

# Disable extra document processing models (important for stability)
ocr = PaddleOCR(
    lang="en",
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
)

def normalize_text(text: str) -> str:
    return " ".join(text.strip().split())

def extract_text_from_result(result) -> list[str]:
    texts = []

    for res in result:
        payload = None

        if hasattr(res, "res"):
            payload = res.res
        elif isinstance(res, dict) and "res" in res:
            payload = res["res"]
        elif isinstance(res, dict):
            payload = res

        if not payload:
            continue

        rec_texts = payload.get("rec_texts", [])
        for t in rec_texts:
            t = normalize_text(str(t))
            if t:
                texts.append(t)

    return texts

def summarize_action(prev_texts: set[str], current_texts: set[str]):
    new_text = current_texts - prev_texts
    if not new_text:
        return None

    top = list(sorted(new_text))[:6]
    return " / ".join(top)

def analyze_video(video_path: str, sample_every_seconds: float = 2.0):
    cap = cv2.VideoCapture(video_path)

    if not cap.isOpened():
        print(f"❌ Error: Could not open video file at {video_path}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0:
        fps = 30.0

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    sample_interval = max(1, int(fps * sample_every_seconds))
    frame_count = 0
    prev_texts = set()

    print(f"\n🚀 ANALYZING: {video_path}")
    print(f"📊 Video Info: {total_frames} frames, {fps:.2f} FPS")
    print("-" * 60)

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_count % sample_interval == 0:
            timestamp = frame_count / fps

            # Resize for speed if large
            h, w = frame.shape[:2]
            scale = 0.75 if max(w, h) > 1280 else 1.0
            if scale != 1.0:
                frame = cv2.resize(frame, None, fx=scale, fy=scale)

            try:
                result = ocr.predict(frame)

                texts = extract_text_from_result(result)
                current_texts = set(texts)

                if not current_texts:
                    print(f"[{timestamp:06.1f}s] No text detected")
                else:
                    action = summarize_action(prev_texts, current_texts)
                    preview = ", ".join(list(texts)[:8])

                    if action:
                        print(f"[{timestamp:06.1f}s] ACTION CHANGE: {action}")
                    else:
                        print(f"[{timestamp:06.1f}s] Observed: {preview}")

                    prev_texts = current_texts

            except Exception as e:
                print(f"[{timestamp:06.1f}s] OCR Error: {type(e).__name__}: {e}")

        frame_count += 1

    cap.release()
    print("-" * 60)
    print("✅ Analysis Complete.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Usage: python src/mp4video_action_analyzer.py "input/video_name.mp4"')
    else:
        analyze_video(sys.argv[1])