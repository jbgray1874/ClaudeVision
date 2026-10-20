"""
SDIAIVision — Learning Engine
================================
Fires at three points in the scan pipeline:

  1. PRE-SCAN   — inject known corrections before AI sees the drawing
  2. POST-SCAN  — catch known error patterns after AI inference
  3. BATCH      — intra-batch propagation: if error seen on job 1,
                  auto-fix jobs 2-N in same batch before they complete

Wiring into main.py (two lines):
    from learning_engine import LearningEngine
    le = LearningEngine()

    # Before estimate:
    summary = le.pre_scan(summary, dxf_paths)

    # After estimate:
    summary = le.post_scan(summary)

    # At batch level (optional, for Ed's weekly runs):
    le.register_batch(job_list)
    # ... scans run ...
    le.batch_complete()
"""

import re
import json
import logging
from typing import Dict, Any, List, Optional

log = logging.getLogger("learning_engine")

try:
    import corrections_db as db
    # Only verify connection — do NOT re-create schema on every scan.
    # Run `python src/corrections_db.py` once for initial setup.
    _DB_AVAILABLE = db.test_connection()
except Exception as e:
    log.warning(f"corrections_db not available: {e}")
    _DB_AVAILABLE = False


class LearningEngine:
    """
    Plugs into the scan pipeline to inject known corrections
    and prevent repeated mistakes across drawings.
    """

    def __init__(self):
        self._batch_errors: List[Dict] = []    # errors seen this batch
        self._batch_jobs:   List[str]  = []    # jobs queued this batch
        self._overrides_cache: Optional[List[Dict]] = None
        self._reload_overrides()

    # ── Override cache ─────────────────────────────────────────────────────────

    def _reload_overrides(self):
        """Load active override rules from database."""
        if not _DB_AVAILABLE:
            self._overrides_cache = []
            return
        try:
            self._overrides_cache = db.get_active_overrides()
            log.info(f"[learning] {len(self._overrides_cache)} override rules loaded")
        except Exception as e:
            log.warning(f"[learning] Could not load overrides: {e}")
            self._overrides_cache = []

    # ── PRE-SCAN: inject known corrections ────────────────────────────────────

    def pre_scan(self, summary: Dict[str, Any],
                 dxf_paths: list = None) -> Dict[str, Any]:
        """
        Called AFTER augment_summary_with_dxf, BEFORE estimate_document.
        Injects known-correct values for part numbers we've seen before.
        Returns modified summary.
        """
        if not _DB_AVAILABLE:
            return summary

        parts = (summary.get("manufacturing_writeup") or {}).get("parts") or []
        overrides_applied = 0

        for part in parts:
            pn = part.get("part_number") or ""

            # ── 1. Known part number lookup ────────────────────────────────────
            if pn:
                known = db.lookup_part(pn)
                if known and known["confidence"] >= 0.8:
                    if known.get("material") and not _is_reliable_material(part):
                        old = part.get("normalized_material")
                        part["normalized_material"] = known["material"]
                        part["material_source"] = f"knowledge_base ({known['confidence']:.0%})"
                        if old != known["material"]:
                            overrides_applied += 1
                            log.info(f"[KB] {pn}: material {old!r} → {known['material']!r}")
                    if known.get("thickness_mm") and not _is_reliable_thickness(part):
                        part["kb_thickness_mm"] = known["thickness_mm"]

            # ── 2. DXF filename override rules ─────────────────────────────────
            dxf_fn = str(part.get("dxf_source_file") or "").upper()
            if dxf_fn:
                for rule in (self._overrides_cache or []):
                    if rule["pattern_type"] == "dxf_filename":
                        if rule["trigger_value"].upper() in dxf_fn:
                            if not _is_reliable_material(part):
                                part[rule["correction_field"]] = rule["correction_value"]
                                part["material_source"] = f"override_rule:{rule['rule_name']}"
                                overrides_applied += 1
                                db.fire_override(rule["id"])
                                log.info(f"[RULE:{rule['rule_name']}] {pn}: "
                                         f"DXF filename contains '{rule['trigger_value']}' "
                                         f"→ {rule['correction_value']}")
                                break

            # ── 3. Material value override rules ───────────────────────────────
            mat = str(part.get("normalized_material") or "").upper()
            if mat:
                for rule in (self._overrides_cache or []):
                    if rule["pattern_type"] == "material_value":
                        trigger = rule["trigger_value"].upper()
                        if mat == trigger or mat.startswith(trigger):
                            ctx = json.loads(rule.get("trigger_context") or "{}")
                            if _check_context(part, ctx):
                                old = part.get("normalized_material")
                                part[rule["correction_field"]] = rule["correction_value"]
                                part["material_source"] = f"override_rule:{rule['rule_name']}"
                                overrides_applied += 1
                                db.fire_override(rule["id"])
                                log.info(f"[RULE:{rule['rule_name']}] {pn}: "
                                         f"material {old!r} → {rule['correction_value']!r}")
                                break

        if overrides_applied:
            print(f"   [learning] {overrides_applied} override(s) applied from knowledge base")
            summary["_learning_overrides_applied"] = overrides_applied

        return summary

    # ── POST-SCAN: validate and catch known error patterns ───────────────────

    def post_scan(self, summary: Dict[str, Any]) -> Dict[str, Any]:
        """
        Called AFTER estimate_document.
        Detects known error patterns, flags low-confidence estimates,
        and feeds new errors into the intra-batch propagation system.
        """
        if not _DB_AVAILABLE:
            return summary

        parts = (summary.get("manufacturing_writeup") or {}).get("parts") or []
        errors_found = []

        for part in parts:
            pn = part.get("part_number") or ""
            mat = str(part.get("normalized_material") or "").upper()
            cost = float(part.get("unit_estimate") or 0)
            geo_src = str(part.get("geometry_source") or "")

            # ── Detect: steel part priced at £0 ────────────────────────────────
            if mat == "MILD_STEEL" and cost == 0.0 and "dxf" in geo_src:
                errors_found.append({
                    "part_number": pn,
                    "error_type":  "zero_cost_steel",
                    "detail":      f"MILD_STEEL with DXF but £0 cost",
                })
                part["_learning_flag"] = "ZERO_COST_STEEL — review material/thickness"

            # ── Detect: material still unknown after all inference ──────────────
            if not mat or mat in ("UNKNOWN", "NONE", "LED", "?"):
                errors_found.append({
                    "part_number": pn,
                    "error_type":  "unknown_material",
                    "detail":      f"material={mat!r} after all inference",
                })
                part["_learning_flag"] = f"UNKNOWN MATERIAL — was: {mat!r}"

            # ── Detect: tolerance table thickness (0.5,1.0,1.5,2.0,3) ──────────
            thicknesses = part.get("thicknesses") or []
            if isinstance(thicknesses, list):
                thk_set = set(round(float(t), 1) for t in thicknesses
                              if t is not None)
                if thk_set == {0.5, 1.0, 1.5, 2.0, 3.0}:
                    part["_learning_flag"] = (
                        (part.get("_learning_flag") or "")
                        + " | TOLERANCE TABLE THICKNESS — no real thickness extracted"
                    ).lstrip(" | ")

        # Propagate new errors to batch system
        if errors_found:
            self._batch_errors.extend(errors_found)
            print(f"   [learning] {len(errors_found)} issue(s) flagged for review")

        summary["_learning_errors"] = errors_found
        return summary

    # ── BATCH: intra-batch propagation ────────────────────────────────────────

    def register_batch(self, job_list: List[str]) -> None:
        """Register a batch of jobs to be scanned this session."""
        self._batch_jobs = list(job_list)
        self._batch_errors = []
        print(f"[learning] Batch registered: {len(job_list)} jobs")

    def get_batch_warnings(self) -> List[str]:
        """
        Returns warnings to display before scanning remaining batch jobs.
        Called between jobs so errors from job 1 are flagged before job 2.
        """
        if not self._batch_errors:
            return []
        seen = {}
        for err in self._batch_errors:
            key = err["error_type"]
            seen[key] = seen.get(key, 0) + 1
        warnings = []
        for err_type, count in seen.items():
            if err_type == "unknown_material":
                warnings.append(
                    f"⚠️  ACTIVE PATTERN: {count} part(s) with unknown material "
                    f"— check DXF filename contains _MS_ / _PETG_ / JOINERY"
                )
            elif err_type == "zero_cost_steel":
                warnings.append(
                    f"⚠️  ACTIVE PATTERN: {count} steel part(s) priced £0 "
                    f"— thickness not extracted, check DXF filename format"
                )
        return warnings

    def batch_complete(self) -> Dict[str, Any]:
        """Called at end of batch. Returns summary of what learning occurred."""
        total_errors = len(self._batch_errors)
        error_types = {}
        for e in self._batch_errors:
            t = e["error_type"]
            error_types[t] = error_types.get(t, 0) + 1
        result = {
            "jobs_in_batch":  len(self._batch_jobs),
            "errors_detected": total_errors,
            "error_breakdown": error_types,
        }
        if total_errors:
            print(f"\n[learning] Batch complete — {total_errors} issue(s) detected")
            for t, c in error_types.items():
                print(f"   {t}: {c}")
            print("   → Submit corrections via xlsx button to improve future scans")
        return result

    # ── CORRECTION SUBMISSION ──────────────────────────────────────────────────

    def submit_correction(self, scan_id: str, part_number: str,
                          job_number: str, field: str,
                          ai_value: str, correct_value: str,
                          corrected_by: str = "estimator",
                          notes: str = "") -> None:
        """
        Called when an estimator submits a correction from the xlsx button.
        Immediately updates the knowledge base and reloads overrides.
        """
        if not _DB_AVAILABLE:
            return

        # Log the correction
        correction_id = db.log_correction(
            scan_id, part_number, job_number, field,
            ai_value, correct_value, corrected_by, notes
        )

        # Immediately update part knowledge
        db.update_part_knowledge(
            part_number, field, correct_value,
            source="estimator_correction",
            corrected_by=corrected_by
        )

        # Check if this pattern is seen 3+ times — if so, auto-generate rule
        self._check_auto_rule(field, ai_value, correct_value)

        # Reload overrides so next scan uses latest knowledge
        self._reload_overrides()

        print(f"[learning] Correction logged: {part_number} {field}: "
              f"{ai_value!r} → {correct_value!r} (by {corrected_by})")

    def _check_auto_rule(self, field: str, ai_value: str,
                         correct_value: str) -> None:
        """If same correction pattern seen 3+ times, auto-generate an override rule."""
        if not _DB_AVAILABLE:
            return
        try:
            import corrections_db as db2
            with db2._connect() as conn:
                count = conn.execute("""
                    SELECT COUNT(*) FROM corrections
                    WHERE field_name=? AND ai_value=? AND correct_value=?
                """, (field, ai_value, correct_value)).fetchone()[0]

                if count >= 3:
                    rule_name = (f"auto_{field}_{re.sub(r'[^a-z0-9]', '_', ai_value.lower())}"
                                 f"_to_{re.sub(r'[^a-z0-9]', '_', correct_value.lower())}")
                    existing = conn.execute(
                        "SELECT id FROM live_overrides WHERE rule_name=?",
                        (rule_name,)
                    ).fetchone()
                    if not existing:
                        conn.execute("""
                            INSERT INTO live_overrides
                            (rule_name, pattern_type, trigger_field, trigger_value,
                             trigger_context, correction_field, correction_value,
                             confidence, auto_generated)
                            VALUES (?,?,?,?,?,?,?,0.85,1)
                        """, (rule_name, "material_value", field, ai_value,
                              "{}", field, correct_value))
                        conn.commit()
                        print(f"[learning] AUTO-RULE generated: {rule_name}")
                        self._reload_overrides()
        except Exception as e:
            log.warning(f"Auto-rule check failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _is_reliable_material(part: Dict) -> bool:
    """Return True if part already has a reliable material from a strong source."""
    mat = str(part.get("normalized_material") or "").upper()
    src = str(part.get("material_source") or "").lower()
    if not mat or mat in ("UNKNOWN", "NONE", "?", "LED", "CARD"):
        return False
    # Already overridden by knowledge base or rule — don't override again
    if "knowledge_base" in src or "override_rule" in src:
        return True
    return False


def _is_reliable_thickness(part: Dict) -> bool:
    """Return True if part has a real (non-tolerance-table) thickness."""
    thk = part.get("thicknesses") or []
    if not thk:
        return False
    if isinstance(thk, list):
        clean = [float(t) for t in thk if t is not None]
        if not clean:
            return False
        tol_table = {0.5, 1.0, 1.5, 2.0, 3.0}
        return not set(round(t, 1) for t in clean).issubset(tol_table)
    return False


def _check_context(part: Dict, context: Dict) -> bool:
    """Evaluate context conditions for an override rule."""
    if not context:
        return True
    for key, val in context.items():
        if key == "geometry_source_contains":
            gs = str(part.get("geometry_source") or "").lower()
            if val.lower() not in gs:
                return False
        elif key == "part_number_prefix":
            pn = str(part.get("part_number") or "")
            if not pn.startswith(val):
                return False
    return True


# ── Singleton instance for use across a scan session ──────────────────────────
_engine: Optional[LearningEngine] = None


def get_engine() -> LearningEngine:
    global _engine
    if _engine is None:
        _engine = LearningEngine()
    return _engine


if __name__ == "__main__":
    engine = LearningEngine()
    print("Learning Engine ready.")
    print(f"Override rules loaded: {len(engine._overrides_cache)}")

    # Test a correction
    engine.submit_correction(
        scan_id="10886-25-01_test",
        part_number="10886-25-01",
        job_number="10886",
        field="normalized_material",
        ai_value="LED",
        correct_value="MILD_STEEL",
        corrected_by="Tim",
        notes="Corner protector always mild steel"
    )
    print("Correction submitted.")
