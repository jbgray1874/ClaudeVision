#!/usr/bin/env python3
r"""
_probe_setup_granularity.py  —  READ-ONLY.  No writes, no DDL, SELECT only.

THE DEFECT WE ARE MEASURING
---------------------------
The WB books SETUP on EVERY labour row:

    hours = (qty / throughput) * order_qty  +  (setup_mins / 60)

P.Coat setup is 15 min at £355.43/hr = £88.86. So every P.Coat ROW adds £88.86.

  1310: 2 P.Coat rows -> 2 x £88.86 = £177.72 / 50 units = £3.55/unit setup
        Tim charges £2.00 for P.Coat IN TOTAL.

  1282: 4 P.Coat rows -> £355.44 of setup / 10 units = £35.54/unit — 82% of its powder cost.
        The powder-pointer fix takes it to NINE rows. ~£800 of setup for what is, on the
        floor, ONE colour through ONE line in ONE oven run.

Same shape on Assemble/pack: 1310 books two pack lines (£1.04) where Tim packs the finished
product once (£0.29).

THE QUESTION — and we MEASURE it, we do not guess
--------------------------------------------------
For each operation: does the estimator write ONE line per JOB, or ONE line per PART?

If P.Coat is always 1 line no matter how many parts a job has, setup is per-JOB and the fix
is unambiguous. If it scales with part count, it is genuinely per-part and the engine is
right to repeat it. Fold, for instance, probably IS per-part (different tooling per part) —
so a blanket "one row per op" fix would be wrong and would swing us into under-costing.

Guessing this from the shop floor risks flipping a known over-charge into an unknown
under-charge. 1,982 historical jobs already contain the answer. Same source the existing
_THROUGHPUT_DEFAULTS came from ("Tim: very consistent at 424").

ALSO ANSWERED IN THE SAME PASS: Robomac's throughput and setup — the last number missing
from 1310 (Tim charges £0.17 and we have no ROBO rate, so nothing is currently costed).

Usage (from C:\ClaudeVision\src):
    C:\ClaudeVision\.venv\Scripts\python.exe _probe_setup_granularity.py
"""
from __future__ import annotations
import sys
import statistics

try:
    import config
except Exception as e:
    sys.exit(f"cannot import config: {e}")


def get_conn():
    for name in ("get_connection", "get_conn", "connect"):
        fn = getattr(config, name, None)
        if callable(fn):
            return fn()
    sys.exit("no connection helper found on config (tried get_connection/get_conn/connect)")


def show(cur, sql, title, note=""):
    print("\n" + "=" * 100)
    print(title)
    if note:
        print(note)
    print("=" * 100)
    try:
        cur.execute(sql)
    except Exception as e:
        print(f"  !! query failed: {e}")
        return []
    cols = [c[0] for c in cur.description]
    rows = cur.fetchall()
    if not rows:
        print("  (no rows)")
        return []
    w = [max(len(str(c)), 12) for c in cols]
    for r in rows:
        for i, v in enumerate(r):
            w[i] = max(w[i], len(str(v)))
    print("  " + " | ".join(str(c).ljust(w[i]) for i, c in enumerate(cols)))
    print("  " + "-+-".join("-" * x for x in w))
    for r in rows:
        print("  " + " | ".join(str(v).ljust(w[i]) for i, v in enumerate(r)))
    return rows


def main():
    conn = get_conn()
    cur = conn.cursor()

    # ---------------------------------------------------------------- 0. shape
    show(cur, """
        SELECT TOP 5 *
        FROM dbo.historical_quote_labour_line
    """, "0. SHAPE OF dbo.historical_quote_labour_line",
        "If this fails, the labour lines live under another name — the column list below\n"
        "tells us what we are actually working with before any conclusions are drawn.")

    show(cur, """
        SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_NAME LIKE 'historical_quote%'
        ORDER BY TABLE_NAME, ORDINAL_POSITION
    """, "0b. ALL historical_quote* COLUMNS",
        "So the queries below can be re-pointed at the real column names if they differ.")

    # ------------------------------------------- 1. THE CORE QUESTION
    show(cur, """
        WITH job_parts AS (
            SELECT quote_id, COUNT(DISTINCT part_number) AS n_parts
            FROM dbo.historical_quote_material_line
            WHERE part_number IS NOT NULL
            GROUP BY quote_id
        ),
        op_lines AS (
            SELECT quote_id, operation, COUNT(*) AS n_lines
            FROM dbo.historical_quote_labour_line
            WHERE operation IS NOT NULL
            GROUP BY quote_id, operation
        )
        SELECT TOP 40
            o.operation,
            COUNT(*)                                   AS jobs,
            AVG(CAST(p.n_parts AS FLOAT))              AS avg_parts_in_job,
            AVG(CAST(o.n_lines AS FLOAT))              AS avg_op_lines,
            MIN(o.n_lines)                             AS min_lines,
            MAX(o.n_lines)                             AS max_lines,
            AVG(CAST(o.n_lines AS FLOAT))
              / NULLIF(AVG(CAST(p.n_parts AS FLOAT)),0) AS lines_per_part
        FROM op_lines o
        JOIN job_parts p ON p.quote_id = o.quote_id
        WHERE p.n_parts >= 3
        GROUP BY o.operation
        HAVING COUNT(*) >= 10
        ORDER BY lines_per_part ASC
    """, "1. *** THE ANSWER *** — LINES PER OPERATION vs PARTS PER JOB",
        "Only jobs with 3+ parts, so per-part and per-job are actually distinguishable.\n\n"
        "  lines_per_part near 0    -> ONE LINE PER JOB. Setup charged once. The engine is\n"
        "                              repeating it per part and OVER-CHARGING.\n"
        "  lines_per_part near 1.0  -> genuinely PER-PART. Engine behaviour is correct;\n"
        "                              do NOT collapse these or we swing into under-costing.\n\n"
        "Read P.Coat, Assemble/pack, Weld, Laser, Fold off this table directly.")

    # ---------------------------------- 2. distribution for the suspect ops
    show(cur, """
        WITH job_parts AS (
            SELECT quote_id, COUNT(DISTINCT part_number) AS n_parts
            FROM dbo.historical_quote_material_line
            WHERE part_number IS NOT NULL
            GROUP BY quote_id
        ),
        op_lines AS (
            SELECT quote_id, operation, COUNT(*) AS n_lines
            FROM dbo.historical_quote_labour_line
            WHERE operation IS NOT NULL
            GROUP BY quote_id, operation
        )
        SELECT
            o.operation,
            CASE WHEN p.n_parts BETWEEN 3 AND 5   THEN '3-5 parts'
                 WHEN p.n_parts BETWEEN 6 AND 10  THEN '6-10 parts'
                 WHEN p.n_parts BETWEEN 11 AND 20 THEN '11-20 parts'
                 ELSE '20+ parts' END              AS job_size,
            COUNT(*)                               AS jobs,
            AVG(CAST(o.n_lines AS FLOAT))          AS avg_lines
        FROM op_lines o
        JOIN job_parts p ON p.quote_id = o.quote_id
        WHERE p.n_parts >= 3
          AND o.operation IN ('P.Coat','Assemble/pack (Metal)','Weld (CO2)',
                              'Laser (Metal)','Fold','Punch','Robomac')
        GROUP BY o.operation,
            CASE WHEN p.n_parts BETWEEN 3 AND 5   THEN '3-5 parts'
                 WHEN p.n_parts BETWEEN 6 AND 10  THEN '6-10 parts'
                 WHEN p.n_parts BETWEEN 11 AND 20 THEN '11-20 parts'
                 ELSE '20+ parts' END
        ORDER BY o.operation, job_size
    """, "2. DOES THE LINE COUNT GROW WITH THE JOB? (the decisive cut)",
        "If avg_lines stays ~1 as the job grows from 3 parts to 20+, the operation is\n"
        "PER-JOB beyond doubt. If it climbs with part count, it is PER-PART. This is the\n"
        "cut that cannot be argued with.")

    # ------------------------------------------------- 3. Robomac
    show(cur, """
        SELECT TOP 30
            operation, quote_id, quantity, hours, setup_mins, cost_gbp
        FROM dbo.historical_quote_labour_line
        WHERE operation LIKE '%obomac%' OR operation LIKE 'ROBO%'
        ORDER BY quote_id DESC
    """, "3. ROBOMAC — raw lines",
        "1310 needs a ROBO throughput. Tim charges £0.17. We have no rate, so we currently\n"
        "cost NOTHING. Deriving one from his single number would be fitting, not measuring.")

    show(cur, """
        SELECT
            COUNT(*)                                              AS lines,
            AVG(CAST(setup_mins AS FLOAT))                        AS avg_setup_mins,
            AVG(CASE WHEN hours > 0 THEN CAST(quantity AS FLOAT)/hours END) AS avg_throughput_per_hr,
            MIN(CASE WHEN hours > 0 THEN CAST(quantity AS FLOAT)/hours END) AS min_throughput,
            MAX(CASE WHEN hours > 0 THEN CAST(quantity AS FLOAT)/hours END) AS max_throughput
        FROM dbo.historical_quote_labour_line
        WHERE (operation LIKE '%obomac%' OR operation LIKE 'ROBO%')
          AND quantity > 0
    """, "3b. ROBOMAC — derived throughput + setup",
        "The median here is the number to put in _THROUGHPUT_DEFAULTS — derived the same way\n"
        "every other default in that table was ('Tim: very consistent at 424').")

    # ------------------------------------ 4. setup per op (cross-check)
    show(cur, """
        SELECT TOP 40
            operation,
            COUNT(*)                        AS lines,
            AVG(CAST(setup_mins AS FLOAT))  AS avg_setup_mins,
            MIN(setup_mins)                 AS min_setup,
            MAX(setup_mins)                 AS max_setup
        FROM dbo.historical_quote_labour_line
        WHERE operation IS NOT NULL
        GROUP BY operation
        HAVING COUNT(*) >= 10
        ORDER BY avg_setup_mins DESC
    """, "4. SETUP MINUTES BY OPERATION (cross-check against the WB dept table)",
        "The WB dept table says P.Coat setup = 15 min @ £355.43/hr = £88.86 PER ROW.\n"
        "Confirm that is what the estimators actually book — and how often.")

    conn.close()

    print("""
====================================================================================
WHAT WE DO WITH THIS

  Any operation with lines_per_part near 0 and avg_lines flat as the job grows is a
  PER-JOB operation. The engine is booking its setup once per PART, and every extra
  part in a job invents another machine setup that never happens.

  P.Coat is the big one: £88.86 of setup PER ROW. 1282 currently books four rows
  (£355 of setup, 82% of its powder cost) and the powder-pointer fix takes it to NINE.

  DO NOT collapse operations the data shows to be genuinely per-part (Fold almost
  certainly is — different tooling for each part). A blanket fix would trade a known
  over-charge for an unknown under-charge, which is strictly worse: we would stop
  being able to see it.

  Then: Robomac's median throughput goes into _THROUGHPUT_DEFAULTS, 1310 gets its
  £0.17, and the job can be closed out with a parity report that stands up.
====================================================================================
""")


if __name__ == "__main__":
    main()
