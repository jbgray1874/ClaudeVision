-- Optional view: quick browse in SSMS / reporting tools.
-- Full labour/material detail remains in historical_quote_operation / historical_quote_material
-- and in historical_quote_header.readable_extract_json (indented JSON).

CREATE OR ALTER VIEW dbo.vw_historical_quote_reconciliation AS
SELECT
    h.quote_id,
    h.quote_key,
    h.source_workbook_path,
    h.source_json_path,
    h.customer_name,
    h.drawing_number,
    h.revision,
    h.quote_date,
    h.total_unit_cost_gbp,
    h.parse_confidence,
    h.readable_extract_json,
    p.quote_part_id,
    p.part_code,
    p.part_description,
    p.unit_total_cost_gbp,
    (SELECT COUNT(*) FROM dbo.historical_quote_operation o WHERE o.quote_part_id = p.quote_part_id) AS operation_row_count,
    (SELECT COUNT(*) FROM dbo.historical_quote_material m WHERE m.quote_part_id = p.quote_part_id) AS material_row_count
FROM dbo.historical_quote_header h
LEFT JOIN dbo.historical_quote_part p ON p.quote_id = h.quote_id;
GO
