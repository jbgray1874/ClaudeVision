from typing import Any, Dict, List


def build_process_routing(part: Dict[str, Any]) -> List[Dict[str, Any]]:
    routing: List[Dict[str, Any]] = []
    operations = part.get("textual_operations", [])
    if "laser_cutting" in operations:
        routing.append({"operation": "laser_cutting", "phase": "profile", "driver": "cut_length_and_pierces", "source": "geometry_or_flat_pattern"})
    if "hole_machining" in operations:
        routing.append({"operation": "hole_machining", "phase": "secondary", "driver": "hole_count", "source": "text_or_geometry"})
    if "tapping" in operations:
        routing.append({"operation": "tapping", "phase": "secondary", "driver": "thread_features", "source": "process_notes"})
    if "countersinking" in operations:
        routing.append({"operation": "countersinking", "phase": "secondary", "driver": "csk_features", "source": "process_notes"})
    if "folding" in operations:
        routing.append({"operation": "folding", "phase": "forming", "driver": "bend_count_and_length", "source": "angles_folds_geometry"})
    if "welding" in operations:
        routing.append({"operation": "welding", "phase": "assembly", "driver": "weld_notes", "source": "process_notes"})
    if "powder_coating" in operations:
        routing.append({"operation": "powder_coating", "phase": "finish", "driver": "finish_requirement", "source": "title_block"})
    routing.append({"operation": "handling", "phase": "logistics", "driver": "part_count", "source": "default"})
    return routing
