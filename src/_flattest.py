import sys
from pathlib import Path
sys.path.insert(0, r"C:\ClaudeVision\src")
import dxf_reader   # the thin loader -> loads dxf_reader.py.py
folder = Path(r"K:\Estimating\Completed\AI Estimating\Live Enquiry\1282 - Milwaukee Wall Bay")
dxfs = sorted(folder.rglob("*.DXF")) + sorted(folder.rglob("*.dxf"))
print(f"{'part':<40} {'flat?':<6} {'blank LxW':<18} {'area mm2':<12} {'bbox_fill%':<10} {'perim mm':<10} {'holes':<6} {'bends'}")
print("-"*120)
for dxf in dxfs:
    try:
        f = dxf_reader.extract_flat_pattern_data(dxf)
        L, W = f.get('blank_length_mm'), f.get('blank_width_mm')
        print(f"{dxf.name[:39]:<40} {str(f.get('flat_pattern_detected')):<6} "
              f"{f'{L}x{W}':<18} {str(f.get('blank_area_mm2')):<12} "
              f"{str(f.get('bbox_fill_pct')):<10} {str(f.get('perimeter_mm')):<10} "
              f"{str(f.get('hole_count')):<6} {f.get('bend_count')}")
    except Exception as e:
        print(f"{dxf.name[:39]:<40} ERROR: {e}")
