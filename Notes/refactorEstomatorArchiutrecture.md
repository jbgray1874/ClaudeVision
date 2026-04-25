
File
Edit
View
Window
Help
Refactor estimator architecture



.venv) PS C:\ClaudeVision> python .\src\main.py --pdf "C:\ClaudeVision\input\drawings\1315-1000x300mm Shelf Assembly REV11.PDF"
>> 
Found 1 PDF file(s).

[SCAN] 1315-1000x300mm Shelf Assembly REV11.PDF
Page count: 5
Detected labels: DWG NO, REVISION, DESCRIPTION, PROJECT TITLE, DATE, CLIENT, SHEET, SHEET SIZE, DRAWN BY, MODIFIED BY, MATERIAL, SCALE, CLIENT REF
Part numbers: 1315 - 01, 1315 - 02, 1315 - 03, 1315 - 04, 1315 - GA
Dates: 21/12/2023
Materials: None
Surface finishes: None
Colours: None
Output files:
  - C:\ClaudeVision\output\json\1315-1000x300mm Shelf Assembly REV11.json
  - C:\ClaudeVision\output\text\1315-1000x300mm Shelf Assembly REV11.txt
  - C:\ClaudeVision\output\logs\1315-1000x300mm Shelf Assembly REV11.log
  - C:\ClaudeVision\output\csv\part_estimate_inputs.csv

Part summaries:

Part: 1315 - 01
  Description: None
  Quantity: 1
  Pages: [2]
  Page roles: ['assembly']
  Materials: None
  Finishes: None
  Thicknesses: None
  Angles: 1.0
  Hole sizes: None
  Slot sizes: None
  Operations: laser_cutting, folding, powder_coating, handling
  Process notes: None
  Geometry: {'vector_path_count': 26, 'line_segments': 2415, 'rectangles': 0, 'curves': 0, 'filled_paths': 3, 'approx_total_line_length_points': 24524.72, 'approx_total_curve_length_points': 0.0, 'estimated_cut_length_mm': 8651.78, 'estimated_hole_count': 0, 'estimated_circle_like_features': 0, 'estimated_slot_like_features': 0, 'estimated_bend_line_count': 51, 'estimated_pierce_count': 0, 'contour_complexity': 2415, 'closed_path_count': 0, 'long_axis_aligned_lines': 51}
  Unit estimate: 18.33
  Extended estimate: 18.33

Part: 1315 - 02
  Description: None
  Quantity: 1
  Pages: [3]
  Page roles: ['assembly']
  Materials: None
  Finishes: None
  Thicknesses: None
  Angles: 1.0
  Hole sizes: 4.0
  Slot sizes: None
  Operations: laser_cutting, hole_machining, folding, powder_coating, handling, mirror_hand
  Process notes: 5 6 7 8 A MIRRORED B DRAWN C
  Geometry: {'vector_path_count': 28, 'line_segments': 3979, 'rectangles': 0, 'curves': 0, 'filled_paths': 4, 'approx_total_line_length_points': 22661.33, 'approx_total_curve_length_points': 0.0, 'estimated_cut_length_mm': 7994.41, 'estimated_hole_count': 0, 'estimated_circle_like_features': 0, 'estimated_slot_like_features': 0, 'estimated_bend_line_count': 43, 'estimated_pierce_count': 0, 'contour_complexity': 3979, 'closed_path_count': 0, 'long_axis_aligned_lines': 43}
  Unit estimate: 17.55
  Extended estimate: 17.55

Part: 1315 - 03
  Description: None
  Quantity: 1
  Pages: [4]
  Page roles: ['assembly']
  Materials: None
  Finishes: None
  Thicknesses: None
  Angles: 135, 1.0
  Hole sizes: None
  Slot sizes: None
  Operations: laser_cutting, folding, powder_coating, handling
  Process notes: None
  Geometry: {'vector_path_count': 28, 'line_segments': 2447, 'rectangles': 0, 'curves': 0, 'filled_paths': 4, 'approx_total_line_length_points': 29940.69, 'approx_total_curve_length_points': 0.0, 'estimated_cut_length_mm': 10562.41, 'estimated_hole_count': 0, 'estimated_circle_like_features': 0, 'estimated_slot_like_features': 0, 'estimated_bend_line_count': 45, 'estimated_pierce_count': 0, 'contour_complexity': 2447, 'closed_path_count': 0, 'long_axis_aligned_lines': 45}
  Unit estimate: 17.37
  Extended estimate: 17.37

Part: 1315 - 04
  Description: None
  Quantity: 1
  Pages: [5]
  Page roles: ['assembly']
  Materials: None
  Finishes: None
  Thicknesses: None
  Angles: 1.0
  Hole sizes: None
  Slot sizes: None
  Operations: laser_cutting, folding, powder_coating, handling
  Process notes: None
  Geometry: {'vector_path_count': 23, 'line_segments': 2230, 'rectangles': 0, 'curves': 0, 'filled_paths': 3, 'approx_total_line_length_points': 23224.41, 'approx_total_curve_length_points': 0.0, 'estimated_cut_length_mm': 8193.06, 'estimated_hole_count': 0, 'estimated_circle_like_features': 0, 'estimated_slot_like_features': 0, 'estimated_bend_line_count': 32, 'estimated_pierce_count': 0, 'contour_complexity': 2230, 'closed_path_count': 0, 'long_axis_aligned_lines': 32}
  Unit estimate: 13.97
  Extended estimate: 13.97

Part: 1315 - GA
  Description: DATE BY V 1.2mm MATERIAL UPDATE TO 11 21/12/2023 EC 1mm DWG NO. REVISION: PROJECT TITLE: 11 1000 X 300MM SHELF 1315 - GA DRAWN BY: MODIFIED BY: DATE: SCALE - IF IN DOUBT ASK! F EDWARD.COOPER 21/12/2023 SCALE: SHEET SIZE: CLIENT REF: SHEET: UNLESS OTHERWISE STATED: DIMENSIONS ARE IN MILLIMETERS (mm) 1:10 1/5 A3 LINEAR TOLERANCE ±0.5 ANGULAR TOLERANCE ±1.0° 6 7 8
  Quantity: 1
  Pages: [1]
  Page roles: ['assembly']
  Materials: None
  Finishes: None
  Thicknesses: None
  Angles: 1.0
  Hole sizes: None
  Slot sizes: None
  Operations: folding, powder_coating, handling, mirror_hand
  Process notes: 1 1315 - 01 1000x300 SHELF TOP 1 A 2 1315 - 02 SMALL BRACKET 1 3 1315 - 02 MIRRORED SMALL BRACKET 1 4 1315 - 03 SHELF BRACE 1 5 1315 - 04 FRONT L BRACKET 2 B C 355.0
  Geometry: {'vector_path_count': 21, 'line_segments': 5373, 'rectangles': 0, 'curves': 0, 'filled_paths': 2, 'approx_total_line_length_points': 48787.75, 'approx_total_curve_length_points': 0.0, 'estimated_cut_length_mm': 17211.23, 'estimated_hole_count': 0, 'estimated_circle_like_features': 0, 'estimated_slot_like_features': 0, 'estimated_bend_line_count': 149, 'estimated_pierce_count': 0, 'contour_complexity': 5373, 'closed_path_count': 0, 'long_axis_aligned_lines': 149}
  Unit estimate: 36.26
  Extended estimate: 36.26

Manufacturing observations:
  - 1315 - 01: flat pattern detected, likely laser or profile cutting required.
  - 1315 - 01: fold or bend work indicated.
  - 1315 - 02: flat pattern detected, likely laser or profile cutting required.
  - 1315 - 02: hole features detected (4.0).
  - 1315 - 02: fold or bend work indicated.
  - 1315 - 02: process notes detected (5 6 7 8 A MIRRORED B DRAWN C).
  - 1315 - 03: flat pattern detected, likely laser or profile cutting required.
  - 1315 - 03: fold or bend work indicated.
  - 1315 - 04: flat pattern detected, likely laser or profile cutting required.
  - 1315 - 04: fold or bend work indicated.
  - 1315 - GA: fold or bend work indicated.
  - 1315 - GA: process notes detected (1 1315 - 01 1000x300 SHELF TOP 1 A 2 1315 - 02 SMALL BRACKET 1 3 1315 - 02 MIRRORED SMALL BRACKET 1 4 1315 - 03 SHELF BRACE 1 5 1315 - 04 FRONT L BRACKET 2 B C 355.0).

Estimated document total: 103.48

Page text preview:

Page 1 (assembly): 1 2 3 4 5 6 7 8 ITEM NO. PartNo Description QTY. 3 1 1315 - 01 1000x300 SHELF TOP 1 A A 2 1315 - 02 SMALL BRACKET 1 1 3 1315 - 02 MIRRORED SMALL BRACKET 1 4 1315 - 03 SHELF BRACE 1 5 1315 - 04 FRONT L BRACKET 2 5 B B 2 5 991.0 INT CTITICAL C C 4 132.5 355.0 132.5 D D 383.0 995.0 EXT E E REVISION TABLE RE DRG NO DESCRIPTION DATE BY V 1.2mm MATERIAL UPDATE TO 11 21/12/2023 EC 1mm Copt Oak Barn DESCRIPTION: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough 100

Page 2 (assembly): 1 2 3 4 5 6 7 8 A A 1.0 B B 1003.2 C 355.0 EXT C 995.0 EXT 4.5 D D 363.2 FLAT PATTERN (NOT TO SCALE) E E 6.0 EXT FOLD Copt Oak Barn DESCRIPTION: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough 1000x300 SHELF TOP TTi 1000 X 300MM SHELF 1315 - 01 11 LE12 9YE 0116 274 7040 DRAWN BY: MODIFIED BY: DATE: hello@wearesdi.com MATERIAL: MILD STEEL DO NOT SCALE - IF IN DOUBT ASK! F EDWARD.COOPER 21/12/2023 F This drawing remains the SURFACE FINISH: POWDER COATING pr

Page 3 (assembly): 1 2 3 4 5 6 7 8 A A MIRRORED 2.0 B B 383.0 DRAWN C C 142.1 FLAT PATTERN (NOT TO SCALE) D D 13.0 4.0 HANGING HOLE 22.0 EXT 50.0 PITCH H 3.0 23.0 E E R3.0 DETAIL H 383.0 SCALE 1 : 2 Copt Oak Barn DESCRIPTION: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough SMALL BRACKET TTi 1000 X 300MM SHELF 1315 - 02 11 LE12 9YE 0116 274 7040 DRAWN BY: MODIFIED BY: DATE: hello@wearesdi.com MATERIAL: MILD STEEL DO NOT SCALE - IF IN DOUBT ASK! F EDWARD.COOPER 21/12/2023 F T

Page 4 (assembly): 1 2 3 4 5 6 7 8 1.0 15.4 A A 13.5 135° B B DETAIL G SCALE 2 : 1 945.0 C C 945.0 D D 56.8 FLAT PATTERN (NOT TO SCALE) E E G Copt Oak Barn DESCRIPTION: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough SHELF BRACE TTi 1000 X 300MM SHELF 1315 - 03 11 LE12 9YE 0116 274 7040 DRAWN BY: MODIFIED BY: DATE: hello@wearesdi.com MATERIAL: MILD STEEL DO NOT SCALE - IF IN DOUBT ASK! F EDWARD.COOPER 21/12/2023 F This drawing remains the SURFACE FINISH: POWDER COATING prop

Page 5 (assembly): 1 2 3 4 5 6 7 8 1.0 A A B B 991.0 C C 12.8 4.5 D D 5.3 38.1 FLAT PATTERN (NOT TO SCALE) E E Copt Oak Barn DESCRIPTION: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough FRONT L BRACKET TTi 1000 X 300MM SHELF 1315 - 04 11 LE12 9YE 0116 274 7040 DRAWN BY: MODIFIED BY: DATE: hello@wearesdi.com MATERIAL: MILD STEEL DO NOT SCALE - IF IN DOUBT ASK! F EDWARD.COOPER 21/12/2023 F This drawing remains the SURFACE FINISH: POWDER COATING property of SDI Displays Limite

Show more
12:30

This is a good milestone: the pipeline is running end-to-end now.

It also shows exactly where the next refinement pass should go. The main issues visible in this run are:

Materials / finishes / thicknesses are still not being captured into the part summaries, even though the page text clearly contains MILD STEEL and POWDER COATING.
All detail pages are being classified as assembly; pages 2-5 should mostly be detail.
1315 - GA is being treated like a manufacturable part, when it should really be the assembly drawing record.
1.0 is being picked up as an angle on several pages, which is noise from tolerance/scale text.
process notes are too noisy; for example MIRRORED B DRAWN C is not a real manufacturing note.
Geometry is overcounting bend-style lines and producing very large cut lengths, so those estimates are still heuristic rather than trustworthy.
So the honest answer is:

the parsing is now structurally working
but no, we do not yet have the full clean manufacturing data set we want
we now have a strong diagnostic output that tells us what to fix next
The highest-value next coding fixes are:

Tighten title-block extraction so material, finish, colour, revision, and thickness come from the title-block region more reliably.
Improve page-role logic so FLAT PATTERN / DETAIL pages become detail, not assembly.
Exclude - GA assembly drawing numbers from the manufacturable part list, or treat them separately.
Filter out tolerance/scale noise so 1.0 does not become a bend angle.
Make process-note extraction more selective so it doesn’t grab surrounding junk.
Reduce geometry overcounting by treating page geometry as mixed annotation+shape content, not pure part profile.
So this run is very useful. It proves the pipeline works and gives us the exact next refinement targets.

If you want, I can work on those fixes now as the next pass:

material/finish/thickness extraction
page-role correction
assembly-vs-part separation
angle/process-note cleanup
geometry de-noising




12:30
If you want, I can work on those fixes now as the next pass: Yes please.
12:31


Worked for 1m 21s
I’ve done the next refinement pass, and it compiles cleanly.

Updated files:

extractor_patterns.py
file_scan.py
document_builder.py
What changed:

title-block extraction now falls back more intelligently to full-page text when the region misses fields like material/finish/thickness
page-role logic is less easily fooled by the word ASSEMBLY in project titles, so detail pages should classify better
- GA assembly identifiers are no longer treated as manufacturable part records
angle extraction now filters out tiny tolerance noise like 1.0
process-note extraction is more selective and less likely to keep numeric junk
mirror_hand stays as a cue, but it no longer pollutes the manufacturing operation list
Before rerunning, copy these updated files into C:\ClaudeVision\src:

Copy-Item "C:\Users\james.gray\Documents\Codex\2026-04-23-i-m-going-to-give-you\latest_src_pack\src\extractor_patterns.py" "C:\ClaudeVision\src\extractor_patterns.py" -Force
Copy-Item "C:\Users\james.gray\Documents\Codex\2026-04-23-i-m-going-to-give-you\latest_src_pack\src\file_scan.py" "C:\ClaudeVision\src\file_scan.py" -Force
Copy-Item "C:\Users\james.gray\Documents\Codex\2026-04-23-i-m-going-to-give-you\latest_src_pack\src\document_builder.py" "C:\ClaudeVision\src\document_builder.py" -Force
Then rerun:

python .\src\main.py --pdf "C:\ClaudeVision\input\drawings\1315-1000x300mm Shelf Assembly REV11.PDF"
What I’d expect from this rerun:

materials/finishes should improve
pages 2-5 should be more likely to become detail
1315 - GA should disappear from the part list
1.0 should stop appearing as a bend angle
process-note noise should reduce
Once you’ve got that output, paste it over and I’ll do the next calibration pass with you.





12:32
3 files changed
+119
-9
Undo
document_builder.py
extractor_patterns.py
file_scan.py
(.venv) PS C:\ClaudeVision> python .\src\main.py --pdf "C:\ClaudeVision\input\drawings\1315-1000x300mm Shelf Assembly REV11.PDF"
>> 
Found 1 PDF file(s).

[SCAN] 1315-1000x300mm Shelf Assembly REV11.PDF
Page count: 5
Detected labels: DWG NO, REVISION, DESCRIPTION, PROJECT TITLE, DATE, CLIENT, SHEET, SHEET SIZE, DRAWN BY, MODIFIED BY, MATERIAL, SCALE, CLIENT REF
Part numbers: 1315 - 01, 1315 - 02, 1315 - 03, 1315 - 04, 1315 - GA
Dates: 21/12/2023
Materials: MILD STEEL
Surface finishes: POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED
Colours: MILWAUKEE - RAL 3020 TRAFFIC RED SEMI GLOSS AEG - RAL 2011 DEEP ORANGE MATT RYOBI GREEN - TEXTURED [POWDER175] UNLESS OTHERWISE STATED, SEE ASSEMBLY DRAWING UNLESS OTHERWISE STATED
Output files:
  - C:\ClaudeVision\output\json\1315-1000x300mm Shelf Assembly REV11.json
  - C:\ClaudeVision\output\text\1315-1000x300mm Shelf Assembly REV11.txt
  - C:\ClaudeVision\output\logs\1315-1000x300mm Shelf Assembly REV11.log
  - C:\ClaudeVision\output\csv\part_estimate_inputs.csv

Part summaries:

Part: 1315 - 01
  Description: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough 1000x300 SHELF TOP TTi 1000 X 300MM SHELF 1315 - 01 11 LE12 9YE 0116 274 7040 DRAWN BY: MODIFIED BY: DATE: hello@wearesdi.com MATERIAL: MILD STEEL DO NOT SCALE - IF IN DOUBT ASK! F EDWARD.COOPER 21/12/2023 F This drawing remains the SURFACE FINISH: POWDER COATING property of SDI Displays Limited. This drawing, hard copy or COLOUR: SEE ASSEMBLY DRAWING UNLESS OTHERWISE STATED: CLIENT REF: SCALE: SHEET SIZE: SHEET: digital, and any attachments are ALL DIMENSIONS ARE IN MILLIMETERS (mm) confidential, legally privileged and WEIGHT: ERROR!:Weightg LINEAR TOLERANCE ±0.5 ANGULAR TOLERANCE ±1.0° 1:8 A3 2/5 protected by copyright. 1 2 3 4 5 6 7 8
  Quantity: 1
  Pages: [2]
  Page roles: ['detail']
  Materials: MILD STEEL
  Finishes: POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED
  Thicknesses: None
  Angles: None
  Hole sizes: None
  Slot sizes: None
  Operations: laser_cutting, folding, powder_coating, handling
  Process notes: None
  Geometry: {'vector_path_count': 26, 'line_segments': 2415, 'rectangles': 0, 'curves': 0, 'filled_paths': 3, 'approx_total_line_length_points': 24524.72, 'approx_total_curve_length_points': 0.0, 'estimated_cut_length_mm': 8651.78, 'estimated_hole_count': 0, 'estimated_circle_like_features': 0, 'estimated_slot_like_features': 0, 'estimated_bend_line_count': 51, 'estimated_pierce_count': 0, 'contour_complexity': 2415, 'closed_path_count': 0, 'long_axis_aligned_lines': 51}
  Unit estimate: 18.33
  Extended estimate: 18.33

Part: 1315 - 02
  Description: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough SMALL BRACKET TTi 1000 X 300MM SHELF 1315 - 02 11 LE12 9YE 0116 274 7040 DRAWN BY: MODIFIED BY: DATE: hello@wearesdi.com MATERIAL: MILD STEEL DO NOT SCALE - IF IN DOUBT ASK! F EDWARD.COOPER 21/12/2023 F This drawing remains the SURFACE FINISH: POWDER COATING property of SDI Displays Limited. This drawing, hard copy or COLOUR: SEE ASSEMBLY DRAWING UNLESS OTHERWISE STATED: CLIENT REF: SCALE: SHEET SIZE: SHEET: digital, and any attachments are ALL DIMENSIONS ARE IN MILLIMETERS (mm) confidential, legally privileged and WEIGHT: ERROR!:Weightg LINEAR TOLERANCE ±0.5 ANGULAR TOLERANCE ±1.0° 1:4 A3 3/5 protected by copyright. 1 2 3 4 5 6 7 8
  Quantity: 1
  Pages: [3]
  Page roles: ['detail']
  Materials: MILD STEEL
  Finishes: POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED
  Thicknesses: None
  Angles: None
  Hole sizes: 4.0
  Slot sizes: None
  Operations: laser_cutting, hole_machining, folding, powder_coating, handling
  Process notes: 5 6 7 8 A MIRRORED B DRAWN C
  Geometry: {'vector_path_count': 28, 'line_segments': 3979, 'rectangles': 0, 'curves': 0, 'filled_paths': 4, 'approx_total_line_length_points': 22661.33, 'approx_total_curve_length_points': 0.0, 'estimated_cut_length_mm': 7994.41, 'estimated_hole_count': 0, 'estimated_circle_like_features': 0, 'estimated_slot_like_features': 0, 'estimated_bend_line_count': 43, 'estimated_pierce_count': 0, 'contour_complexity': 3979, 'closed_path_count': 0, 'long_axis_aligned_lines': 43}
  Unit estimate: 17.55
  Extended estimate: 17.55

Part: 1315 - 03
  Description: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough SHELF BRACE TTi 1000 X 300MM SHELF 1315 - 03 11 LE12 9YE 0116 274 7040 DRAWN BY: MODIFIED BY: DATE: hello@wearesdi.com MATERIAL: MILD STEEL DO NOT SCALE - IF IN DOUBT ASK! F EDWARD.COOPER 21/12/2023 F This drawing remains the SURFACE FINISH: POWDER COATING property of SDI Displays Limited. This drawing, hard copy or COLOUR: SEE ASSEMBLY DRAWING UNLESS OTHERWISE STATED: CLIENT REF: SCALE: SHEET SIZE: SHEET: digital, and any attachments are ALL DIMENSIONS ARE IN MILLIMETERS (mm) confidential, legally privileged and WEIGHT: ERROR!:Weightg LINEAR TOLERANCE ±0.5 ANGULAR TOLERANCE ±1.0° 1:5 A3 4/5 protected by copyright. 1 2 3 4 5 6 7 8
  Quantity: 1
  Pages: [4]
  Page roles: ['detail']
  Materials: MILD STEEL
  Finishes: POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED
  Thicknesses: None
  Angles: 135
  Hole sizes: None
  Slot sizes: None
  Operations: laser_cutting, folding, powder_coating, handling
  Process notes: None
  Geometry: {'vector_path_count': 28, 'line_segments': 2447, 'rectangles': 0, 'curves': 0, 'filled_paths': 4, 'approx_total_line_length_points': 29940.69, 'approx_total_curve_length_points': 0.0, 'estimated_cut_length_mm': 10562.41, 'estimated_hole_count': 0, 'estimated_circle_like_features': 0, 'estimated_slot_like_features': 0, 'estimated_bend_line_count': 45, 'estimated_pierce_count': 0, 'contour_complexity': 2447, 'closed_path_count': 0, 'long_axis_aligned_lines': 45}
  Unit estimate: 17.37
  Extended estimate: 17.37

Part: 1315 - 04
  Description: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough FRONT L BRACKET TTi 1000 X 300MM SHELF 1315 - 04 11 LE12 9YE 0116 274 7040 DRAWN BY: MODIFIED BY: DATE: hello@wearesdi.com MATERIAL: MILD STEEL DO NOT SCALE - IF IN DOUBT ASK! F EDWARD.COOPER 21/12/2023 F This drawing remains the SURFACE FINISH: POWDER COATING property of SDI Displays Limited. This drawing, hard copy or COLOUR: SEE ASSEMBLY DRAWING UNLESS OTHERWISE STATED: CLIENT REF: SCALE: SHEET SIZE: SHEET: digital, and any attachments are ALL DIMENSIONS ARE IN MILLIMETERS (mm) confidential, legally privileged and WEIGHT: ERROR!:Weightg LINEAR TOLERANCE ±0.5 ANGULAR TOLERANCE ±1.0° 1:4 A3 5/5 protected by copyright. 1 2 3 4 5 6 7 8
  Quantity: 1
  Pages: [5]
  Page roles: ['detail']
  Materials: MILD STEEL
  Finishes: POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED
  Thicknesses: None
  Angles: None
  Hole sizes: None
  Slot sizes: None
  Operations: laser_cutting, folding, powder_coating, handling
  Process notes: None
  Geometry: {'vector_path_count': 23, 'line_segments': 2230, 'rectangles': 0, 'curves': 0, 'filled_paths': 3, 'approx_total_line_length_points': 23224.41, 'approx_total_curve_length_points': 0.0, 'estimated_cut_length_mm': 8193.06, 'estimated_hole_count': 0, 'estimated_circle_like_features': 0, 'estimated_slot_like_features': 0, 'estimated_bend_line_count': 32, 'estimated_pierce_count': 0, 'contour_complexity': 2230, 'closed_path_count': 0, 'long_axis_aligned_lines': 32}
  Unit estimate: 13.97
  Extended estimate: 13.97

Manufacturing observations:
  - 1315 - 01: flat pattern detected, likely laser or profile cutting required.
  - 1315 - 01: fold or bend work indicated.
  - 1315 - 01: finish detected (POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED).
  - 1315 - 01: material detected (MILD STEEL).
  - 1315 - 02: flat pattern detected, likely laser or profile cutting required.
  - 1315 - 02: hole features detected (4.0).
  - 1315 - 02: fold or bend work indicated.
  - 1315 - 02: finish detected (POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED).
  - 1315 - 02: material detected (MILD STEEL).
  - 1315 - 02: process notes detected (5 6 7 8 A MIRRORED B DRAWN C).
  - 1315 - 03: flat pattern detected, likely laser or profile cutting required.
  - 1315 - 03: fold or bend work indicated.
  - 1315 - 03: finish detected (POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED).
  - 1315 - 03: material detected (MILD STEEL).
  - 1315 - 04: flat pattern detected, likely laser or profile cutting required.
  - 1315 - 04: fold or bend work indicated.
  - 1315 - 04: finish detected (POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED).
  - 1315 - 04: material detected (MILD STEEL).

Estimated document total: 67.22

Page text preview:

Page 1 (assembly): 1 2 3 4 5 6 7 8 ITEM NO. PartNo Description QTY. 3 1 1315 - 01 1000x300 SHELF TOP 1 A A 2 1315 - 02 SMALL BRACKET 1 1 3 1315 - 02 MIRRORED SMALL BRACKET 1 4 1315 - 03 SHELF BRACE 1 5 1315 - 04 FRONT L BRACKET 2 5 B B 2 5 991.0 INT CTITICAL C C 4 132.5 355.0 132.5 D D 383.0 995.0 EXT E E REVISION TABLE RE DRG NO DESCRIPTION DATE BY V 1.2mm MATERIAL UPDATE TO 11 21/12/2023 EC 1mm Copt Oak Barn DESCRIPTION: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough 100

Page 2 (detail): 1 2 3 4 5 6 7 8 A A 1.0 B B 1003.2 C 355.0 EXT C 995.0 EXT 4.5 D D 363.2 FLAT PATTERN (NOT TO SCALE) E E 6.0 EXT FOLD Copt Oak Barn DESCRIPTION: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough 1000x300 SHELF TOP TTi 1000 X 300MM SHELF 1315 - 01 11 LE12 9YE 0116 274 7040 DRAWN BY: MODIFIED BY: DATE: hello@wearesdi.com MATERIAL: MILD STEEL DO NOT SCALE - IF IN DOUBT ASK! F EDWARD.COOPER 21/12/2023 F This drawing remains the SURFACE FINISH: POWDER COATING pr

Page 3 (detail): 1 2 3 4 5 6 7 8 A A MIRRORED 2.0 B B 383.0 DRAWN C C 142.1 FLAT PATTERN (NOT TO SCALE) D D 13.0 4.0 HANGING HOLE 22.0 EXT 50.0 PITCH H 3.0 23.0 E E R3.0 DETAIL H 383.0 SCALE 1 : 2 Copt Oak Barn DESCRIPTION: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough SMALL BRACKET TTi 1000 X 300MM SHELF 1315 - 02 11 LE12 9YE 0116 274 7040 DRAWN BY: MODIFIED BY: DATE: hello@wearesdi.com MATERIAL: MILD STEEL DO NOT SCALE - IF IN DOUBT ASK! F EDWARD.COOPER 21/12/2023 F T

Page 4 (detail): 1 2 3 4 5 6 7 8 1.0 15.4 A A 13.5 135° B B DETAIL G SCALE 2 : 1 945.0 C C 945.0 D D 56.8 FLAT PATTERN (NOT TO SCALE) E E G Copt Oak Barn DESCRIPTION: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough SHELF BRACE TTi 1000 X 300MM SHELF 1315 - 03 11 LE12 9YE 0116 274 7040 DRAWN BY: MODIFIED BY: DATE: hello@wearesdi.com MATERIAL: MILD STEEL DO NOT SCALE - IF IN DOUBT ASK! F EDWARD.COOPER 21/12/2023 F This drawing remains the SURFACE FINISH: POWDER COATING prop

Page 5 (detail): 1 2 3 4 5 6 7 8 1.0 A A B B 991.0 C C 12.8 4.5 D D 5.3 38.1 FLAT PATTERN (NOT TO SCALE) E E Copt Oak Barn DESCRIPTION: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough FRONT L BRACKET TTi 1000 X 300MM SHELF 1315 - 04 11 LE12 9YE 0116 274 7040 DRAWN BY: MODIFIED BY: DATE: hello@wearesdi.com MATERIAL: MILD STEEL DO NOT SCALE - IF IN DOUBT ASK! F EDWARD.COOPER 21/12/2023 F This drawing remains the SURFACE FINISH: POWDER COATING property of SDI Displays Limite

Show more
12:34

This is a much better run.

The clear wins:

MILD STEEL is now being captured
detail pages are correctly classed as detail
1315 - GA has dropped out of the manufacturable part list
the noisy 1.0 angle issue is mostly gone
overall estimate dropped to something more believable because the assembly page is no longer being priced like a part
What is still wrong:

finish extraction is over-capturing:
POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED
it should stop at POWDER COATING
colour extraction is also over-capturing:
... UNLESS OTHERWISE STATED
that needs clipping
descriptions are still basically the whole title block text, not the real part description
thickness is still missing, even though page 1 has the revision note about 1.2mm / 1mm
process-note noise is still present on part 1315 - 02
geometry is still overcounting bend/cut features quite heavily
So we’ve moved from:

“pipeline runs but is noisy”
to
“pipeline runs and the main structure is right, but field cleanup is still needed”
The next highest-value fixes are now very clear:

Tighten labelled field extraction
make SURFACE FINISH: stop at the next label
make COLOUR: stop at the next label
do the same for DESCRIPTION:, PROJECT TITLE:, CLIENT:
Improve description logic
prefer BOM description for part pages when available
otherwise extract the short title-block description line, not the whole region
Add thickness fallback logic
detect thickness from revision notes like 1.2mm MATERIAL UPDATE TO 1mm
or from nearby title-block text when THK isn’t explicitly present
Further clean process notes
reject snippets dominated by grid letters/numbers
keep only note-like fragments with stronger wording
Reduce geometry overcounting
likely ignore a chunk of annotation lines
stop treating so many long lines as bend candidates
So yes, this is solid progress.

If you want, I’d do the next pass in this order:

field clipping for finish/colour/description
thickness fallback
process-note cleanup
then geometry de-noising
That should give you the next biggest jump in practical estimating quality.





12:34
Yes please.
12:35


Worked for 1m 18s
Done — this pass is in and compiles cleanly.

Updated files:

extractor_patterns.py
document_builder.py
What changed:

SURFACE FINISH, COLOUR, and DESCRIPTION now use label-aware clipping so they stop at the next title-block label instead of swallowing the rest of the block
thickness now has a fallback that can pick up plain 1.2mm-style values even when THK isn’t present
BOM descriptions are preferred over noisy title-block OCR for part descriptions
process-note snippets now require stronger note-like wording, so the mirrored/grid junk should reduce further
Copy these two into C:\ClaudeVision\src:

Copy-Item "C:\Users\james.gray\Documents\Codex\2026-04-23-i-m-going-to-give-you\latest_src_pack\src\extractor_patterns.py" "C:\ClaudeVision\src\extractor_patterns.py" -Force
Copy-Item "C:\Users\james.gray\Documents\Codex\2026-04-23-i-m-going-to-give-you\latest_src_pack\src\document_builder.py" "C:\ClaudeVision\src\document_builder.py" -Force
Then rerun:

python .\src\main.py --pdf "C:\ClaudeVision\input\drawings\1315-1000x300mm Shelf Assembly REV11.PDF"
What I’d expect this time:

finish should get much closer to just POWDER COATING
colour should stop before UNLESS OTHERWISE STATED
part descriptions should improve a lot
process-note noise should reduce further
thickness may start appearing if the fallback catches the mm value cleanly
Once you’ve got that output, send it over and I’ll keep tuning the remaining weak spots.





12:36
2 files changed
+152
-5
Undo
document_builder.py
extractor_patterns.py
this needs to be a generic solution also for all sorts of drawings and not hard coded for this one.
12:36

Yes — and that’s the right constraint to keep in front of us.

What I’m doing is not meant to hard-code this specific drawing number or this specific sheet. The aim is to make the extraction more generic by improving the rules around:

labeled field boundaries
part-vs-assembly page behavior
note quality filtering
BOM-preferred descriptions
thickness fallback from common mm patterns
Those are generic strategies, not 1315-specific logic.

That said, your warning is important because there’s always a risk of overfitting when we tune against one sample. So the rule I’d follow is:

no logic that depends on this drawing number
no logic that depends on this customer/job name
no logic that depends on one exact title-block wording unless it’s a broadly reusable label
prefer structural cues over one-off text quirks
Good generic examples:

stop a labeled field at the next labeled field
treat -GA as assembly-style identifier generally
prefer BOM description when present
ignore angle values below a sensible threshold like 5°
require process notes to contain real note words, not just mixed OCR fragments
Bad non-generic examples:

“if drawing contains 1315 then…”
“if description contains Shelf then…”
“if page 3 then small bracket logic…”
So yes, absolutely: this needs to stay generic.

The best way to keep it generic is:

use reusable parsing rules
validate against multiple drawings
add confidence/review flags instead of forcing bad extractions
calibrate with a small batch of varied drawings, not just one
So the next healthy step after this one drawing is:

test on 3 to 10 different drawing packs
compare failures
only keep rules that help across multiple jobs
That’s how we avoid building a “works for shelf drawing only” parser.

If you want, after the next rerun I can help you identify which rules are genuinely generic and which ones we should treat as provisional until we’ve seen more drawing styles.





12:36
Great - thanks !
12:36

Any time. Once you’ve rerun the updated files, send the output over and we’ll keep tightening it in a generic way.





12:36
are we saving down all thje JSON files or constanstly over writing. I can only see one JSON file in there.
12:38

At the moment, it saves one JSON file per PDF filename, so it overwrites the previous JSON for that same drawing each time you rerun it.

So right now:

different PDFs produce different JSON files
rerunning the same PDF replaces its existing JSON
That’s why you’re only seeing one JSON for this drawing.

The current naming pattern is basically:

output/json/<pdf-stem>.json
For your example:

C:\ClaudeVision\output\json\1315-1000x300mm Shelf Assembly REV11.json
So yes, the behavior is:

not one global file for everything
but yes, overwrite on rerun for the same source filename
If you want to keep every run, the best options are:

Timestamp every output file
example:
1315-1000x300mm Shelf Assembly REV11_2026-04-24_123500.json
Keep both
latest stable filename
plus archived timestamped copies
Write to run folders
example:
output/runs/2026-04-24_12-35-00/json/...
I’d recommend option 2:

keep the current “latest” JSON path for easy downstream use
also save a timestamped archive copy for comparison/debugging
That gives you:

stable path for the pipeline
historical snapshots for tuning
So yes, right now it overwrites the same drawing’s JSON.
If you want, I can change the code so it also writes timestamped archived copies on every run.





12:39
Yes, let's put a time stamp on these ? to show rhe evolution. Please chedk this : .venv) PS C:\ClaudeVision> python .\src\main.py --pdf "C:\ClaudeVision\input\drawings\1315-1000x300mm Shelf Assembly REV11.PDF"
>> 
Found 1 PDF file(s).

[SCAN] 1315-1000x300mm Shelf Assembly REV11.PDF
Page count: 5
Detected labels: DWG NO, REVISION, DESCRIPTION, PROJECT TITLE, DATE, CLIENT, SHEET, SHEET SIZE, DRAWN BY, MODIFIED BY, MATERIAL, SCALE, CLIENT REF
Part numbers: 1315 - 01, 1315 - 02, 1315 - 03, 1315 - 04, 1315 - GA
Dates: 21/12/2023
Materials: MILD STEEL
Surface finishes: POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED. THIS DRAWING, HARD COPY OR
Colours: MILWAUKEE - RAL 3020 TRAFFIC RED SEMI GLOSS AEG - RAL 2011 DEEP ORANGE MATT RYOBI GREEN - TEXTURED [POWDER175]
Output files:
  - C:\ClaudeVision\output\json\1315-1000x300mm Shelf Assembly REV11.json
  - C:\ClaudeVision\output\text\1315-1000x300mm Shelf Assembly REV11.txt
  - C:\ClaudeVision\output\logs\1315-1000x300mm Shelf Assembly REV11.log
  - C:\ClaudeVision\output\csv\part_estimate_inputs.csv

Part summaries:

Part: 1315 - 01
  Description: None
  Quantity: 1
  Pages: [2]
  Page roles: ['detail']
  Materials: MILD STEEL
  Finishes: POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED. THIS DRAWING, HARD COPY OR
  Thicknesses: None
  Angles: None
  Hole sizes: None
  Slot sizes: None
  Operations: laser_cutting, folding, powder_coating, handling
  Process notes: None
  Geometry: {'vector_path_count': 26, 'line_segments': 2415, 'rectangles': 0, 'curves': 0, 'filled_paths': 3, 'approx_total_line_length_points': 24524.72, 'approx_total_curve_length_points': 0.0, 'estimated_cut_length_mm': 8651.78, 'estimated_hole_count': 0, 'estimated_circle_like_features': 0, 'estimated_slot_like_features': 0, 'estimated_bend_line_count': 51, 'estimated_pierce_count': 0, 'contour_complexity': 2415, 'closed_path_count': 0, 'long_axis_aligned_lines': 51}
  Unit estimate: 18.33
  Extended estimate: 18.33

Part: 1315 - 02
  Description: None
  Quantity: 1
  Pages: [3]
  Page roles: ['detail']
  Materials: MILD STEEL
  Finishes: POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED. THIS DRAWING, HARD COPY OR
  Thicknesses: None
  Angles: None
  Hole sizes: 4.0
  Slot sizes: None
  Operations: laser_cutting, hole_machining, folding, powder_coating, handling
  Process notes: None
  Geometry: {'vector_path_count': 28, 'line_segments': 3979, 'rectangles': 0, 'curves': 0, 'filled_paths': 4, 'approx_total_line_length_points': 22661.33, 'approx_total_curve_length_points': 0.0, 'estimated_cut_length_mm': 7994.41, 'estimated_hole_count': 0, 'estimated_circle_like_features': 0, 'estimated_slot_like_features': 0, 'estimated_bend_line_count': 43, 'estimated_pierce_count': 0, 'contour_complexity': 3979, 'closed_path_count': 0, 'long_axis_aligned_lines': 43}
  Unit estimate: 17.55
  Extended estimate: 17.55

Part: 1315 - 03
  Description: None
  Quantity: 1
  Pages: [4]
  Page roles: ['detail']
  Materials: MILD STEEL
  Finishes: POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED. THIS DRAWING, HARD COPY OR
  Thicknesses: None
  Angles: 135
  Hole sizes: None
  Slot sizes: None
  Operations: laser_cutting, folding, powder_coating, handling
  Process notes: None
  Geometry: {'vector_path_count': 28, 'line_segments': 2447, 'rectangles': 0, 'curves': 0, 'filled_paths': 4, 'approx_total_line_length_points': 29940.69, 'approx_total_curve_length_points': 0.0, 'estimated_cut_length_mm': 10562.41, 'estimated_hole_count': 0, 'estimated_circle_like_features': 0, 'estimated_slot_like_features': 0, 'estimated_bend_line_count': 45, 'estimated_pierce_count': 0, 'contour_complexity': 2447, 'closed_path_count': 0, 'long_axis_aligned_lines': 45}
  Unit estimate: 17.37
  Extended estimate: 17.37

Part: 1315 - 04
  Description: None
  Quantity: 1
  Pages: [5]
  Page roles: ['detail']
  Materials: MILD STEEL
  Finishes: POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED. THIS DRAWING, HARD COPY OR
  Thicknesses: None
  Angles: None
  Hole sizes: None
  Slot sizes: None
  Operations: laser_cutting, folding, powder_coating, handling
  Process notes: None
  Geometry: {'vector_path_count': 23, 'line_segments': 2230, 'rectangles': 0, 'curves': 0, 'filled_paths': 3, 'approx_total_line_length_points': 23224.41, 'approx_total_curve_length_points': 0.0, 'estimated_cut_length_mm': 8193.06, 'estimated_hole_count': 0, 'estimated_circle_like_features': 0, 'estimated_slot_like_features': 0, 'estimated_bend_line_count': 32, 'estimated_pierce_count': 0, 'contour_complexity': 2230, 'closed_path_count': 0, 'long_axis_aligned_lines': 32}
  Unit estimate: 13.97
  Extended estimate: 13.97

Manufacturing observations:
  - 1315 - 01: flat pattern detected, likely laser or profile cutting required.
  - 1315 - 01: fold or bend work indicated.
  - 1315 - 01: finish detected (POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED. THIS DRAWING, HARD COPY OR).
  - 1315 - 01: material detected (MILD STEEL).
  - 1315 - 02: flat pattern detected, likely laser or profile cutting required.
  - 1315 - 02: hole features detected (4.0).
  - 1315 - 02: fold or bend work indicated.
  - 1315 - 02: finish detected (POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED. THIS DRAWING, HARD COPY OR).
  - 1315 - 02: material detected (MILD STEEL).
  - 1315 - 03: flat pattern detected, likely laser or profile cutting required.
  - 1315 - 03: fold or bend work indicated.
  - 1315 - 03: finish detected (POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED. THIS DRAWING, HARD COPY OR).
  - 1315 - 03: material detected (MILD STEEL).
  - 1315 - 04: flat pattern detected, likely laser or profile cutting required.
  - 1315 - 04: fold or bend work indicated.
  - 1315 - 04: finish detected (POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED. THIS DRAWING, HARD COPY OR).
  - 1315 - 04: material detected (MILD STEEL).

Estimated document total: 67.22

Page text preview:

Page 1 (assembly): 1 2 3 4 5 6 7 8 ITEM NO. PartNo Description QTY. 3 1 1315 - 01 1000x300 SHELF TOP 1 A A 2 1315 - 02 SMALL BRACKET 1 1 3 1315 - 02 MIRRORED SMALL BRACKET 1 4 1315 - 03 SHELF BRACE 1 5 1315 - 04 FRONT L BRACKET 2 5 B B 2 5 991.0 INT CTITICAL C C 4 132.5 355.0 132.5 D D 383.0 995.0 EXT E E REVISION TABLE RE DRG NO DESCRIPTION DATE BY V 1.2mm MATERIAL UPDATE TO 11 21/12/2023 EC 1mm Copt Oak Barn DESCRIPTION: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough 100

Page 2 (detail): 1 2 3 4 5 6 7 8 A A 1.0 B B 1003.2 C 355.0 EXT C 995.0 EXT 4.5 D D 363.2 FLAT PATTERN (NOT TO SCALE) E E 6.0 EXT FOLD Copt Oak Barn DESCRIPTION: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough 1000x300 SHELF TOP TTi 1000 X 300MM SHELF 1315 - 01 11 LE12 9YE 0116 274 7040 DRAWN BY: MODIFIED BY: DATE: hello@wearesdi.com MATERIAL: MILD STEEL DO NOT SCALE - IF IN DOUBT ASK! F EDWARD.COOPER 21/12/2023 F This drawing remains the SURFACE FINISH: POWDER COATING pr

Page 3 (detail): 1 2 3 4 5 6 7 8 A A MIRRORED 2.0 B B 383.0 DRAWN C C 142.1 FLAT PATTERN (NOT TO SCALE) D D 13.0 4.0 HANGING HOLE 22.0 EXT 50.0 PITCH H 3.0 23.0 E E R3.0 DETAIL H 383.0 SCALE 1 : 2 Copt Oak Barn DESCRIPTION: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough SMALL BRACKET TTi 1000 X 300MM SHELF 1315 - 02 11 LE12 9YE 0116 274 7040 DRAWN BY: MODIFIED BY: DATE: hello@wearesdi.com MATERIAL: MILD STEEL DO NOT SCALE - IF IN DOUBT ASK! F EDWARD.COOPER 21/12/2023 F T

Page 4 (detail): 1 2 3 4 5 6 7 8 1.0 15.4 A A 13.5 135° B B DETAIL G SCALE 2 : 1 945.0 C C 945.0 D D 56.8 FLAT PATTERN (NOT TO SCALE) E E G Copt Oak Barn DESCRIPTION: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough SHELF BRACE TTi 1000 X 300MM SHELF 1315 - 03 11 LE12 9YE 0116 274 7040 DRAWN BY: MODIFIED BY: DATE: hello@wearesdi.com MATERIAL: MILD STEEL DO NOT SCALE - IF IN DOUBT ASK! F EDWARD.COOPER 21/12/2023 F This drawing remains the SURFACE FINISH: POWDER COATING prop

Page 5 (detail): 1 2 3 4 5 6 7 8 1.0 A A B B 991.0 C C 12.8 4.5 D D 5.3 38.1 FLAT PATTERN (NOT TO SCALE) E E Copt Oak Barn DESCRIPTION: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough FRONT L BRACKET TTi 1000 X 300MM SHELF 1315 - 04 11 LE12 9YE 0116 274 7040 DRAWN BY: MODIFIED BY: DATE: hello@wearesdi.com MATERIAL: MILD STEEL DO NOT SCALE - IF IN DOUBT ASK! F EDWARD.COOPER 21/12/2023 F This drawing remains the SURFACE FINISH: POWDER COATING property of SDI Displays Limite

Show more
12:40


Worked for 40s
Yes — I’ve now added timestamped archive outputs so you can keep the evolution of each run.

Updated files:

config.py
file_scan.py
What it now does:

still writes the normal “latest” files:
output/json/<name>.json
output/text/<name>.txt
output/logs/<name>.log
output/csv/part_estimate_inputs.csv
and also writes timestamped archive copies for each run:
output/archive/json/<name>_YYYY-MM-DD_HH-MM-SS.json
output/archive/text/<name>_YYYY-MM-DD_HH-MM-SS.txt
output/archive/logs/<name>_YYYY-MM-DD_HH-MM-SS.log
output/archive/csv/<name>_YYYY-MM-DD_HH-MM-SS.csv
Copy these two into C:\ClaudeVision\src:

Copy-Item "C:\Users\james.gray\Documents\Codex\2026-04-23-i-m-going-to-give-you\latest_src_pack\src\config.py" "C:\ClaudeVision\src\config.py" -Force
Copy-Item "C:\Users\james.gray\Documents\Codex\2026-04-23-i-m-going-to-give-you\latest_src_pack\src\file_scan.py" "C:\ClaudeVision\src\file_scan.py" -Force
Then rerun your scan. After that, you should see archived versions under:

C:\ClaudeVision\output\archive\json
C:\ClaudeVision\output\archive\text
C:\ClaudeVision\output\archive\logs
C:\ClaudeVision\output\archive\csv
On the output you pasted, the key read is:

structure is improving
detail page roles are right
materials are now being found
but finish is still over-capturing
colour is now much better
descriptions and thickness are still weak
So the next extraction pass should focus on:

better finish clipping
thickness fallback from revision/title-block note text
part description recovery from BOM/title block
That run is definitely better than where we started, and now you’ll have snapshots to compare as we refine it.





12:40
2 files changed
+37
-0
Undo
config.py
file_scan.py
Ok, so I'll run again ?
12:42

Yes — run again after copying the updated config.py and file_scan.py.

Use:

python .\src\main.py --pdf "C:\ClaudeVision\input\drawings\1315-1000x300mm Shelf Assembly REV11.PDF"
This run should now:

update the normal latest files
also create timestamped archive copies
Then check:

C:\ClaudeVision\output\archive\json
C:\ClaudeVision\output\archive\text
C:\ClaudeVision\output\archive\logs
C:\ClaudeVision\output\archive\csv
If you want, after that run, paste the output again and I’ll help you compare the evolution.





12:42
excellent ! I see the extra output.
12:43

Perfect — that gives us a proper trail now, which will make the tuning much easier and safer.

From here, each rerun gives you:

the current “latest” output for the pipeline
an archived snapshot so we can compare improvements over time
That’s exactly what we want while refining extraction.

The best next step is just to keep iterating against those archived JSONs and tighten:

finish extraction
thickness extraction
descriptions
geometry noise
When you’re ready, send the next archived or latest output and I’ll keep working through the weak spots with you.





12:43
exactly. that's what we want. there is plenty of storage !
12:44

Excellent — then this is the right approach.

Keeping every run gives us:

traceability
comparison over time
easier debugging
confidence that improvements are real, not imagined
And for this project, that matters a lot because we’re tuning extraction and estimating logic iteratively.

So yes, with plenty of storage, archiving each run is the better choice. It turns the output history into part of the development process.





12:44
so, what's next ?
12:44

Next is to tighten the fields that still matter most for estimating quality, then start connecting pricing sources.

I’d do it in this order:

1. Finish extraction cleanup
Your biggest visible parsing miss right now is:

POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED...
So next we should make title-block field parsing more boundary-aware for:

finish
colour
description
thickness
That will improve both estimating and RAG quality immediately.

2. Thickness and description recovery
We still need cleaner:

part descriptions
thickness values
The next pass should:

prefer BOM descriptions where possible
infer thickness from nearby mm notes more safely
keep confidence/review flags when thickness is ambiguous
3. Geometry de-noising
The geometry is still overcounting:

cut length
bend-like lines
So next we should reduce annotation noise and make geometry outputs less aggressive.

4. Start wiring price sources
Once extraction is a bit cleaner, the next major step is:

workbook labour logic
Access database prices
supplier website fallback
That gives you the first real joined-up estimating context:

extracted manufacturing requirements
current prices/rates
historical reference
5. Historical/RAG build-out
After that:

ingest more historical estimate sheets + drawings
create clean historical_job_record entries
start using them as comparable-job references
So if we’re picking the very next coding pass, I’d choose:

fix finish/description/thickness extraction
reduce geometry noise
then connect price sources
That’s the highest-value path.

If you want, I can start now on the next extraction pass:

finish clipping
thickness fallback
description cleanup
geometry de-noising




12:44
yes, this is the correct approiach. We can then focus on the pricing and the RAG.
12:45

Agreed. That’s the right sequence:

clean extraction
stabilize manufacturing interpretation
then layer in pricing and RAG on top of something trustworthy
So the next pass should focus on:

finish clipping
thickness recovery
description cleanup
geometry de-noising
Once those are cleaner, the pricing side becomes much easier to wire properly, and the RAG records become far more useful because they’ll be built from better structured data.

After that, we’ll be in a good position to:

connect workbook labour logic
connect Access/material/component prices
add supplier web fallback
build historical comparables on top of cleaner part records
Send me the next run after the latest extraction tweaks, and I’ll keep tightening that layer before we move into pricing and RAG.





12:45
Can you see tje JSOm file : (.venv) PS C:\ClaudeVision> r 44 
python .\src\main.py --pdf "C:\ClaudeVision\input\drawings\1315-1000x300mm Shelf Assembly REV11.PDF"

Found 1 PDF file(s).

[SCAN] 1315-1000x300mm Shelf Assembly REV11.PDF
Page count: 5
Detected labels: DWG NO, REVISION, DESCRIPTION, PROJECT TITLE, DATE, CLIENT, SHEET, SHEET SIZE, DRAWN BY, MODIFIED BY, MATERIAL, SCALE, CLIENT REF
Part numbers: 1315 - 01, 1315 - 02, 1315 - 03, 1315 - 04, 1315 - GA
Dates: 21/12/2023
Materials: MILD STEEL
Surface finishes: POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED. THIS DRAWING, HARD COPY OR
Colours: MILWAUKEE - RAL 3020 TRAFFIC RED SEMI GLOSS AEG - RAL 2011 DEEP ORANGE MATT RYOBI GREEN - TEXTURED [POWDER175]
Output files:
  - C:\ClaudeVision\output\json\1315-1000x300mm Shelf Assembly REV11.json
  - C:\ClaudeVision\output\text\1315-1000x300mm Shelf Assembly REV11.txt
  - C:\ClaudeVision\output\logs\1315-1000x300mm Shelf Assembly REV11.log
  - C:\ClaudeVision\output\csv\part_estimate_inputs.csv

Part summaries:

Part: 1315 - 01
  Description: None
  Quantity: 1
  Pages: [2]
  Page roles: ['detail']
  Materials: MILD STEEL
  Finishes: POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED. THIS DRAWING, HARD COPY OR
  Thicknesses: None
  Angles: None
  Hole sizes: None
  Slot sizes: None
  Operations: laser_cutting, folding, powder_coating, handling
  Process notes: None
  Geometry: {'vector_path_count': 26, 'line_segments': 2415, 'rectangles': 0, 'curves': 0, 'filled_paths': 3, 'approx_total_line_length_points': 24524.72, 'approx_total_curve_length_points': 0.0, 'estimated_cut_length_mm': 8651.78, 'estimated_hole_count': 0, 'estimated_circle_like_features': 0, 'estimated_slot_like_features': 0, 'estimated_bend_line_count': 51, 'estimated_pierce_count': 0, 'contour_complexity': 2415, 'closed_path_count': 0, 'long_axis_aligned_lines': 51}
  Unit estimate: 18.33
  Extended estimate: 18.33

Part: 1315 - 02
  Description: None
  Quantity: 1
  Pages: [3]
  Page roles: ['detail']
  Materials: MILD STEEL
  Finishes: POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED. THIS DRAWING, HARD COPY OR
  Thicknesses: None
  Angles: None
  Hole sizes: 4.0
  Slot sizes: None
  Operations: laser_cutting, hole_machining, folding, powder_coating, handling
  Process notes: None
  Geometry: {'vector_path_count': 28, 'line_segments': 3979, 'rectangles': 0, 'curves': 0, 'filled_paths': 4, 'approx_total_line_length_points': 22661.33, 'approx_total_curve_length_points': 0.0, 'estimated_cut_length_mm': 7994.41, 'estimated_hole_count': 0, 'estimated_circle_like_features': 0, 'estimated_slot_like_features': 0, 'estimated_bend_line_count': 43, 'estimated_pierce_count': 0, 'contour_complexity': 3979, 'closed_path_count': 0, 'long_axis_aligned_lines': 43}
  Unit estimate: 17.55
  Extended estimate: 17.55

Part: 1315 - 03
  Description: None
  Quantity: 1
  Pages: [4]
  Page roles: ['detail']
  Materials: MILD STEEL
  Finishes: POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED. THIS DRAWING, HARD COPY OR
  Thicknesses: None
  Angles: 135
  Hole sizes: None
  Slot sizes: None
  Operations: laser_cutting, folding, powder_coating, handling
  Process notes: None
  Geometry: {'vector_path_count': 28, 'line_segments': 2447, 'rectangles': 0, 'curves': 0, 'filled_paths': 4, 'approx_total_line_length_points': 29940.69, 'approx_total_curve_length_points': 0.0, 'estimated_cut_length_mm': 10562.41, 'estimated_hole_count': 0, 'estimated_circle_like_features': 0, 'estimated_slot_like_features': 0, 'estimated_bend_line_count': 45, 'estimated_pierce_count': 0, 'contour_complexity': 2447, 'closed_path_count': 0, 'long_axis_aligned_lines': 45}
  Unit estimate: 17.37
  Extended estimate: 17.37

Part: 1315 - 04
  Description: None
  Quantity: 1
  Pages: [5]
  Page roles: ['detail']
  Materials: MILD STEEL
  Finishes: POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED. THIS DRAWING, HARD COPY OR
  Thicknesses: None
  Angles: None
  Hole sizes: None
  Slot sizes: None
  Operations: laser_cutting, folding, powder_coating, handling
  Process notes: None
  Geometry: {'vector_path_count': 23, 'line_segments': 2230, 'rectangles': 0, 'curves': 0, 'filled_paths': 3, 'approx_total_line_length_points': 23224.41, 'approx_total_curve_length_points': 0.0, 'estimated_cut_length_mm': 8193.06, 'estimated_hole_count': 0, 'estimated_circle_like_features': 0, 'estimated_slot_like_features': 0, 'estimated_bend_line_count': 32, 'estimated_pierce_count': 0, 'contour_complexity': 2230, 'closed_path_count': 0, 'long_axis_aligned_lines': 32}
  Unit estimate: 13.97
  Extended estimate: 13.97

Manufacturing observations:
  - 1315 - 01: flat pattern detected, likely laser or profile cutting required.
  - 1315 - 01: fold or bend work indicated.
  - 1315 - 01: finish detected (POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED. THIS DRAWING, HARD COPY OR).
  - 1315 - 01: material detected (MILD STEEL).
  - 1315 - 02: flat pattern detected, likely laser or profile cutting required.
  - 1315 - 02: hole features detected (4.0).
  - 1315 - 02: fold or bend work indicated.
  - 1315 - 02: finish detected (POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED. THIS DRAWING, HARD COPY OR).
  - 1315 - 02: material detected (MILD STEEL).
  - 1315 - 03: flat pattern detected, likely laser or profile cutting required.
  - 1315 - 03: fold or bend work indicated.
  - 1315 - 03: finish detected (POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED. THIS DRAWING, HARD COPY OR).
  - 1315 - 03: material detected (MILD STEEL).
  - 1315 - 04: flat pattern detected, likely laser or profile cutting required.
  - 1315 - 04: fold or bend work indicated.
  - 1315 - 04: finish detected (POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED. THIS DRAWING, HARD COPY OR).
  - 1315 - 04: material detected (MILD STEEL).

Estimated document total: 67.22

Page text preview:

Page 1 (assembly): 1 2 3 4 5 6 7 8 ITEM NO. PartNo Description QTY. 3 1 1315 - 01 1000x300 SHELF TOP 1 A A 2 1315 - 02 SMALL BRACKET 1 1 3 1315 - 02 MIRRORED SMALL BRACKET 1 4 1315 - 03 SHELF BRACE 1 5 1315 - 04 FRONT L BRACKET 2 5 B B 2 5 991.0 INT CTITICAL C C 4 132.5 355.0 132.5 D D 383.0 995.0 EXT E E REVISION TABLE RE DRG NO DESCRIPTION DATE BY V 1.2mm MATERIAL UPDATE TO 11 21/12/2023 EC 1mm Copt Oak Barn DESCRIPTION: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough 100

Page 2 (detail): 1 2 3 4 5 6 7 8 A A 1.0 B B 1003.2 C 355.0 EXT C 995.0 EXT 4.5 D D 363.2 FLAT PATTERN (NOT TO SCALE) E E 6.0 EXT FOLD Copt Oak Barn DESCRIPTION: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough 1000x300 SHELF TOP TTi 1000 X 300MM SHELF 1315 - 01 11 LE12 9YE 0116 274 7040 DRAWN BY: MODIFIED BY: DATE: hello@wearesdi.com MATERIAL: MILD STEEL DO NOT SCALE - IF IN DOUBT ASK! F EDWARD.COOPER 21/12/2023 F This drawing remains the SURFACE FINISH: POWDER COATING pr

Page 3 (detail): 1 2 3 4 5 6 7 8 A A MIRRORED 2.0 B B 383.0 DRAWN C C 142.1 FLAT PATTERN (NOT TO SCALE) D D 13.0 4.0 HANGING HOLE 22.0 EXT 50.0 PITCH H 3.0 23.0 E E R3.0 DETAIL H 383.0 SCALE 1 : 2 Copt Oak Barn DESCRIPTION: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough SMALL BRACKET TTi 1000 X 300MM SHELF 1315 - 02 11 LE12 9YE 0116 274 7040 DRAWN BY: MODIFIED BY: DATE: hello@wearesdi.com MATERIAL: MILD STEEL DO NOT SCALE - IF IN DOUBT ASK! F EDWARD.COOPER 21/12/2023 F T

Page 4 (detail): 1 2 3 4 5 6 7 8 1.0 15.4 A A 13.5 135░ B B DETAIL G SCALE 2 : 1 945.0 C C 945.0 D D 56.8 FLAT PATTERN (NOT TO SCALE) E E G Copt Oak Barn DESCRIPTION: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough SHELF BRACE TTi 1000 X 300MM SHELF 1315 - 03 11 LE12 9YE 0116 274 7040 DRAWN BY: MODIFIED BY: DATE: hello@wearesdi.com MATERIAL: MILD STEEL DO NOT SCALE - IF IN DOUBT ASK! F EDWARD.COOPER 21/12/2023 F This drawing remains the SURFACE FINISH: POWDER COATING prop

Page 5 (detail): 1 2 3 4 5 6 7 8 1.0 A A B B 991.0 C C 12.8 4.5 D D 5.3 38.1 FLAT PATTERN (NOT TO SCALE) E E Copt Oak Barn DESCRIPTION: CLIENT: PROJECT TITLE: DWG NO. REVISION: Ridgefield Business Park Copt Oak, Loughborough FRONT L BRACKET TTi 1000 X 300MM SHELF 1315 - 04 11 LE12 9YE 0116 274 7040 DRAWN BY: MODIFIED BY: DATE: hello@wearesdi.com MATERIAL: MILD STEEL DO NOT SCALE - IF IN DOUBT ASK! F EDWARD.COOPER 21/12/2023 F This drawing remains the SURFACE FINISH: POWDER COATING property of SDI Displays Limite

(.venv) PS C:\ClaudeVision> 

Show more
12:56

Yes — I can see the run output you pasted, and it’s enough to assess the current state.

I can’t see the JSON file contents directly from that message unless you paste them or ask me to inspect the file itself, but I can already tell from this run that:

page roles are now right: pages 2-5 are detail
1315 - GA is no longer being priced as a part
material extraction is working: MILD STEEL
hole/angle cues are partly working: 4.0 hole, 135 angle
The main remaining issues are still:

finish over-capture:
POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED...
descriptions missing
thickness still missing
geometry still overestimates cut/bend features
So this is definitely progress.

If you want me to inspect the actual JSON structure next, either:

paste the JSON, or
tell me to inspect:
C:\ClaudeVision\output\json\1315-1000x300mm Shelf Assembly REV11.json
The next coding pass should be:

finish clipping
description recovery
thickness fallback
geometry de-noising
That’s the right next move before pricing/RAG.





12:56

1315-1000x300mm Shelf Assembly REV11_2026-04-24_12-42-56.json
this it the latest JSOn file also.
12:58



Worked for 6s
Yes, I can see it, and it’s very useful.

The JSON confirms a few important things:

What’s improved

detail page roles are correct for pages 2 to 5.
1315 - GA is no longer being treated as a priced part.
MILD STEEL is being extracted consistently.
thicknesses_mm now appears at document level as 1.2 and 1, so the fallback is partly working.
hole/angle/pitch/radius/fold cues are being found at document level.
What’s still wrong

surface_finishes still over-captures badly:
POWDER COATING PROPERTY OF SDI DISPLAYS LIMITED...
descriptions are still unusable at document/page level.
drawing_numbers are still missing.
revisions are wrong:
TABLE, PROJECT
drawn_by, modified_by, clients, scale, sheet_refs are polluted by nearby labels/text.
part-level thicknesses_mm are still not getting through cleanly.
overall_length_mm / overall_width_mm are wrong at document level:
300.0 and 1.2
geometry is still massively overcounting bend features and cut length.
Big takeaway
The JSON shows the current weakness is now mostly title-block field parsing, not overall pipeline structure. The scan/orchestration is working; the field boundary logic still needs another step up.

Best next coding pass

Make labeled field extraction the primary path for:
drawing number
revision
description
drawn by
modified by
client
scale
sheet
finish
colour
Only fall back to broad regex when labeled extraction fails.
Prevent thickness values like 1.2 from being treated as overall dimensions.
Push primary_thickness_mm down into parts when a detail page only has one clear thickness candidate.
Reduce geometry influence on bend counts until we calibrate it better.
So yes, this JSON is exactly what we needed. It shows we’re past the “does it run?” stage and now firmly in the “clean structured field extraction” stage.

If you want, I can work on that next pass now:

title-block labeled field parsing cleanup
revision/drawing-number fixes
thickness-to-part propagation
dimension ranking cleanup




12:58









Summary

LATEST_CODE_PACK.md

src

estimator.py

main.py

spreadsheet_formula_parser.py

source_connectors

estimate_template_parser.py

2026-04-23-i-m-going-to-give-you
latest_src_pack
src
estimate_template_parser.py


import json
import re
from pathlib import Path
from typing import Any, Dict, List

from extractor_patterns import normalize_text
from spreadsheet_formula_parser import extract_workbook_formulas


def _dedupe(values: List[Any]) -> List[Any]:
    seen: List[Any] = []
    for value in values:
        if value not in (None, "", []) and value not in seen:
            seen.append(value)
    return seen


def _sheet_lookup(workbook_data: Dict[str, Any], target_name: str) -> Dict[str, Any]:
    for sheet in workbook_data.get("sheets", []):
        if sheet.get("sheet_name", "").lower() == target_name.lower():
            return sheet
    return {}


def _classify_formula_entry(sheet_name: str, entry: Dict[str, Any]) -> List[str]:
    formula = str(entry.get("formula", ""))
    labels = " ".join(
        [
            str(entry.get("label_left", "")),
            str(entry.get("label_left_2", "")),
            str(entry.get("label_right", "")),
        ]
    ).upper()
    sheet_upper = sheet_name.upper()
    formula_upper = formula.upper()
    tags: List[str] = []

    if "LOOKUP(" in formula_upper:
        tags.append("lookup")
    if "SUM(" in formula_upper:
        tags.append("sum")
    if any(token in formula_upper for token in ["ROUNDUP(", "*7.85", "/1000", "MATERIAL PRICE BREAK"]):
        tags.append("material_cost_logic")
    if any(token in labels for token in ["UNIT COST", "MATERIAL", "POWDER", "PALLET", "DELIVERY"]):
        tags.append("material_or_bought_in")
    if any(token in labels for token in ["LASM", "FOLD", "LABOUR", "ROUTE", "RATE"]) or sheet_upper == "LABOUR":
        tags.append("labour_or_operation")
    if re.search(r"ESTIMATE!\$H\$\d+:\$H\$\d+", formula_upper, flags=re.IGNORECASE):
        tags.append("operation_table_lookup")
    if "MATERIAL PRICE BREAK" in formula_upper or sheet_upper == "MATERIAL PRICE BREAK":
        tags.append("material_break_table")
    if any(token in formula_upper for token in ["IF(", "LOOKUP(", "ROUNDUP("]) and any(
        token in formula_upper for token in ["H38", "J38", "K38", "L38", "Q38", "V38"]
    ):
        tags.append("sheet_nesting_or_runrate")
    if any(token in formula_upper for token in ["*H", "/I", "/60", "SETUP", "MIN"]):
        tags.append("time_or_rate_logic")

    return _dedupe(tags)


def _summarize_key_formulas(entries: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    summary = {
        "material_formulas": [],
        "labour_formulas": [],
        "total_formulas": [],
        "lookup_formulas": [],
    }

    for entry in entries:
        tags = entry.get("tags", [])
        compact = {
            "sheet": entry["sheet"],
            "address": entry["address"],
            "value": entry["value"],
            "formula": entry["formula"],
            "labels": entry["labels"],
            "tags": tags,
        }
        if "material_cost_logic" in tags or "material_or_bought_in" in tags or "material_break_table" in tags:
            summary["material_formulas"].append(compact)
        if "labour_or_operation" in tags or "operation_table_lookup" in tags or "time_or_rate_logic" in tags:
            summary["labour_formulas"].append(compact)
        if "sum" in tags and any(token in compact["address"] for token in ["59", "101", "105"]):
            summary["total_formulas"].append(compact)
        if "lookup" in tags:
            summary["lookup_formulas"].append(compact)

    for key in summary:
        summary[key] = summary[key][:40]
    return summary


def _extract_key_cells(entries: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    key_cells = {
        "quantity_drivers": [],
        "material_unit_prices": [],
        "operation_rows": [],
        "totals": [],
    }

    for entry in entries:
        address = str(entry.get("address", "")).upper()
        sheet = str(entry.get("sheet", "")).upper()
        tags = entry.get("tags", [])
        compact = {
            "sheet": entry["sheet"],
            "address": entry["address"],
            "value": entry["value"],
            "formula": entry["formula"],
            "labels": entry["labels"],
            "tags": tags,
        }

        if sheet == "ESTIMATE" and address == "D6":
            key_cells["quantity_drivers"].append(compact)
        if sheet == "ESTIMATE" and re.match(r"J(1[1-9]|2[0-3])$", address):
            key_cells["material_unit_prices"].append(compact)
        if sheet == "ESTIMATE" and re.match(r"[A-Z]+6[3-9]$", address):
            key_cells["operation_rows"].append(compact)
        if sheet == "ESTIMATE" and address in {"L59", "L101", "L105", "M59", "M101", "M105"}:
            key_cells["totals"].append(compact)

    return key_cells


def parse_estimate_template(workbook_path: str | Path) -> Dict[str, Any]:
    workbook = Path(workbook_path).resolve()
    workbook_data = extract_workbook_formulas(workbook)

    parsed_entries: List[Dict[str, Any]] = []
    for sheet in workbook_data.get("sheets", []):
        sheet_name = sheet.get("sheet_name", "")
        for entry in sheet.get("formulas", []):
            labels = {
                "left": normalize_text(str(entry.get("label_left", ""))),
                "left_2": normalize_text(str(entry.get("label_left_2", ""))),
                "right": normalize_text(str(entry.get("label_right", ""))),
            }
            parsed_entries.append(
                {
                    "sheet": sheet_name,
                    "address": entry.get("address"),
                    "value": entry.get("value"),
                    "formula": entry.get("formula"),
                    "number_format": entry.get("number_format"),
                    "labels": labels,
                    "tags": _classify_formula_entry(sheet_name, entry),
                }
            )

    return {
        "schema_version": "estimate_template_parse.v1",
        "workbook_path": str(workbook),
        "workbook_name": workbook_data.get("workbook_name", workbook.name),
        "sheet_names": [sheet.get("sheet_name") for sheet in workbook_data.get("sheets", [])],
        "sheet_overview": [
            {
                "sheet_name": sheet.get("sheet_name"),
                "rows": sheet.get("rows"),
                "cols": sheet.get("cols"),
                "formula_count": len(sheet.get("formulas", [])),
            }
            for sheet in workbook_data.get("sheets", [])
        ],
        "estimate_sheet": _sheet_lookup(workbook_data, "Estimate"),
        "labour_sheet": _sheet_lookup(workbook_data, "Labour"),
        "material_price_break_sheet": _sheet_lookup(workbook_data, "Material Price Break"),
        "parsed_entries": parsed_entries,
        "key_formula_summary": _summarize_key_formulas(parsed_entries),
        "key_cells": _extract_key_cells(parsed_entries),
    }


def write_estimate_template_parse(workbook_path: str | Path, output_path: str | Path) -> Path:
    parsed = parse_estimate_template(workbook_path)
    output = Path(output_path).resolve()
    output.write_text(json.dumps(parsed, indent=2, ensure_ascii=False), encoding="utf-8")
    return output
