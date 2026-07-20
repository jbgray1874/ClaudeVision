src = open(r"C:\ClaudeVision\src\dxf_reader.py.py", encoding="utf-8").read()
checks = {
  "call site": "    outline  = _exact_perimeter_and_area(cut_lines, cut_arcs, scale)",
  "cut_circs collected": "    cut_circs = _get_layer_entities(msp, CUT_LAYERS, {\"CIRCLE\"})",
  "return area_method anchor": '        "bbox_fill_pct":   fill_pct,\n    }',
  "old signature": "def _exact_perimeter_and_area(\n    cut_lines: List[Any],\n    cut_arcs:  List[Any],\n    scale: float,\n) -> Dict[str, float]:",
  "already patched?": "_shapely_net_area_mm2",
}
for label, needle in checks.items():
    print(f"{label:<28}: count={src.count(needle)}")
