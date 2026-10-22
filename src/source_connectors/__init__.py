from .access_prices import AccessPriceConnector
from .sqlserver_prices import SqlServerPriceConnector
from .spreadsheet_prices import SpreadsheetPriceConnector
from .web_prices import WebPriceConnector

# Layer 0 of the source waterfall — the native SolidWorks extract. Pure field mapping;
# it never opens SolidWorks itself, so importing it is safe on Linux/CI where pywin32
# is absent and the pipeline runs on PDF + DXF alone.
from .solidworks import (
    NativeJob,
    apply_native_to_part_estimates,
    apply_native_to_pre_estimate,
    native_extract_for_job,
    normalize_native_extract,
)

__all__ = [
    "AccessPriceConnector",
    "SqlServerPriceConnector",
    "SpreadsheetPriceConnector",
    "WebPriceConnector",
    "NativeJob",
    "native_extract_for_job",
    "normalize_native_extract",
    "apply_native_to_pre_estimate",
    "apply_native_to_part_estimates",
]
