import os
# MUST be the absolute first things in the file
os.environ['FLAGS_enable_pir_api'] = '0'
os.environ['FLAGS_use_onednn'] = '0'
os.environ['FLAGS_enable_jit_optim'] = '0'
# This forces the stable executor
os.environ['FLAGS_enable_new_executor'] = '0' 

import cv2
import sys
import paddle

# Set device globally
paddle.device.set_device('cpu')
# Turn off the PIR engine inside the code too
paddle.set_flags({'FLAGS_enable_pir_api': 0})

from paddleocr import PaddleOCR

# --- THE STABLE INITIALIZATION ---
ocr = PaddleOCR(lang='en', ocr_version='PP-OCRv4')

def analyze_video(video_path):
    cap = cv2.VideoCapture(video_path)
    
    if not cap.isOpened():
        print(f"❌ Error: Could not open video file at {video_path}")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame_count = 0
    
    print(f"\n🚀 ANALYZING: {video_path}")
    print(f"📊 Video Info: {total_frames} frames, {fps:.2f} FPS")
    print("-" * 50)

    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break

        # Process 1 frame every 2 seconds (int(fps * 2))
        if frame_count % int(fps * 2) == 0:
            timestamp = int(frame_count / fps)
            
            # Resize for speed
            small_frame = cv2.resize(frame, (0,0), fx=0.5, fy=0.5)
            
            try:
                result = ocr.ocr(small_frame)
                
                if not result or result[0] is None:
                    # Optional: print(f"[{timestamp:02d}s] No text detected.")
                    frame_count += 1
                    continue

                current_text_list = []
                for line in result[0]:
                    text_str = line[1][0]
                    current_text_list.append(text_str)
                
                if current_text_list:
                    # Prints the first 5 unique-ish items found in the ERP screen
                    found_text = ", ".join(current_text_list[:5])
                    print(f"[{timestamp:02d}s] Observed: {found_text}")
                
            except Exception as e:
                print(f"[{timestamp:02d}s] OCR Error: {e}")
        
        frame_count += 1

    cap.release()
    print("-" * 50)
    print("✅ Analysis Complete.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python src/video_analyzer.py \"input/video_name.mp4\"")
    else:
        analyze_video(sys.argv[1])