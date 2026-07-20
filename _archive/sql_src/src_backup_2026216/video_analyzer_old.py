import os
# This stops that 'connectivity check' every time you run it
os.environ['FLAGS_use_onednn'] = '0'
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'

import cv2
import sys
from paddleocr import PaddleOCR

# Initialize OCR (This will download models on first run)
# ocr = PaddleOCR(use_angle_cls=True, lang='en', show_log=False)
# ocr = PaddleOCR(use_textline_orientation=True, lang='en')
ocr = PaddleOCR(lang='en')

def analyze_video(video_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"❌ Error: Could not open video {video_path}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = 0
    last_text_set = set()

    print(f"\n🚀 ANALYZING ERP WORKFLOW: {video_path}")
    print("-" * 50)

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        # Sample 1 frame per second to save processing power
        if frame_count % int(fps) == 0:
            timestamp = int(frame_count / fps)
            
            # Run OCR on the frame
            result = list(ocr.ocr(frame))
            #result = ocr.ocr(frame)
            #result = ocr.ocr(frame, cls=True)
            
            current_text_list = []
            if result[0]:
                for line in result[0]:
                    current_text_list.append(line[1][0]) # Extract the text string
            
            current_text_set = set(current_text_list)
            
            # Only print if new text appears (detecting a change/action)
            new_elements = current_text_set - last_text_set
            if new_elements:
                # Filter for useful ERP keywords
                relevant = [t for t in new_elements if len(t) > 2]
                if relevant:
                    print(f"[{timestamp:02d}s] Action/Change Detected: {', '.join(relevant[:5])}...")
            
            last_text_set = current_text_set

        frame_count += 1

    cap.release()
    print("-" * 50)
    print("✅ Analysis Complete.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python src/video_analyzer.py \"path/to/video.mp4\"")
    else:
        analyze_video(sys.argv[1])