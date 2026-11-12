"""Quick check that document_builder imports without NameError."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import document_builder  # noqa: F401

print("OK: document_builder imported")
print("  _non_metal_label_from_text:", document_builder._non_metal_label_from_text("PETG MATERIAL"))
