import json
import os
from typing import Any, Dict

try:
    import ollama  # type: ignore
except ImportError:  # pragma: no cover
    ollama = None


def reconcile_with_llm(page_context: Dict[str, Any], model: str | None = None) -> Dict[str, Any]:
    if os.getenv("ENABLE_LLM_RECONCILIATION", "").lower() not in {"1", "true", "yes"}:
        return {}
    if ollama is None:
        return {}

    selected_model = model or os.getenv("OLLAMA_RECONCILIATION_MODEL", "llama3.1")
    prompt = (
        "You are reconciling engineering drawing extraction outputs. "
        "Return strict JSON only with keys: thickness_override_mm, revision_override, "
        "process_callouts, feature_inferences, risk_flags, confidence_adjustments. "
        "Do not invent dimensions. Prefer explicit updates like 'UPDATE TO 1mm'. "
        f"Context: {json.dumps(page_context, ensure_ascii=False)[:12000]}"
    )
    try:
        response = ollama.chat(
            model=selected_model,
            messages=[{"role": "user", "content": prompt}],
            format="json",
        )
        content = response.get("message", {}).get("content", "{}")
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}
