from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import config
from estimator import estimate_document, generate_client_quote_pack
from json_normaliser import normalise_json
import supplier_reference

try:
    import pyodbc  # type: ignore
except ImportError:  # pragma: no cover
    pyodbc = None


# WHICH ROWS IN THE BOUGHT-IN CATALOGUE ARE A PRICE WE ACTUALLY PAY.
#
# The table holds more than supplier prices. A live inspection before rung 3 was repointed at
# it found real net rows sitting beside web guesses, figures lifted from a single historical
# workbook, SDI's own estimates, and one row at GBP 0.0000 marked PRICE UNCONFIRMED.
#
# Rung 3 answers at 0.93 for an exact code and 0.80 otherwise -- above historical comparables
# and far above the 0.68 the web/LLM rung is deliberately capped at. Letting an indication in
# here would relabel it as firm and rank it above real evidence, which is the opposite of what
# the ceiling exists to do.
#
# AN ALLOWLIST, BECAUSE IT FAILS CLOSED. A denylist would silently admit the next indicative
# source somebody adds. A missing entry here shows up as a rung that answers nothing, which
# somebody notices; a wrongly admitted one shows up as a confident price on a quote, which
# nobody does.
_FIRM_CATALOGUE_SOURCES = (
    "migrated:",        # carried over from dbo.bought_in_parts, the old real catalogue
    "supplier_file:",   # written by supplier_price_list.py from a supplier's own price list
)


def standard_commodity_price(part: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """A stable, reproducible provisional for a generically-named standard bought-in — a
    PALLET, a perforated-panel clip — from config.STANDARD_COMMODITY_PRICE_GBP, keyed on the
    DESCRIPTION, or None.

    DB-FREE ON PURPOSE, AND MODULE-LEVEL SO THE ENGINE CAN REACH IT WITHOUT A PRICINGSERVICE.
    A fixed config number needs no database and no network, yet the only route to it used to
    run inside PricingService._get_web_ai_fallback — reachable only with a live DB connection
    AND only after _web_ai_fallback_allowed let the part through. So a known commodity on a box
    whose DB rung was unavailable, or whose class-word code ('STD PART') steered the lookup, got
    £0 despite a deterministic price sitting in config. The estimator now consults THIS function
    directly as a last resort (see estimator._resolve_part_system_cost), so the provisional is
    reached wherever a real catalogue/UDEF rate was not — the reproducible figure the whole
    'commodity before the market guess' idea was for.

    Reproducible (a fixed config number, same every run), so it prices the line AND clears
    price_not_reproducible — unlike the market guess it stands in front of. Flagged for review:
    it is a provisional, not a quote."""
    table = getattr(config, "STANDARD_COMMODITY_PRICE_GBP", {}) or {}
    if not table:
        return None
    _desc_u = " ".join(str(v) for v in (
        part.get("description"), part.get("part_number")) if v).upper()
    if not _desc_u.strip():
        return None
    for _tok, _c in table.items():
        # A key may name ONE token ("PALLET") or several joined by "+" ("PERFO+CLIP"), in which
        # case EVERY token must appear in the description. This keeps a generically-named
        # commodity from over-matching: "PERFO+CLIP" prices the perforated-panel locking clip
        # without also capturing a fabricated clip or a plain cable clip that happens to carry
        # the word "CLIP". A single-token key is the len==1 case, so existing entries behave
        # exactly as before.
        _needed = [t.strip() for t in str(_tok).upper().split("+") if t.strip()]
        if _needed and all(t in _desc_u for t in _needed):
            try:
                _price = float(_c.get("price_gbp") or 0)
            except (TypeError, ValueError):
                continue
            if _price <= 0:
                continue
            return {
                "source": "standard_commodity_provisional",
                "source_type": "standard_commodity_provisional",
                "price_is_reproducible": True,      # a fixed config number, same every run
                "unit_price_gbp": round(_price, 2),
                "confidence": 0.5,
                "provenance": f"Standard commodity provisional: {_c.get('label', _tok)}",
                "review_flag": True,
                "review_reason": ("Provisional standard-commodity price — confirm against a "
                                  "supplier quote or add the item to the purchasing catalogue."),
                "supplier_name": "SDI standard commodity (provisional)",
            }
    return None


class PricingService:
    """Workbook-first pricing engine with joined source provenance."""

    def __init__(self, conn: Any = None, connection_factory: Optional[Callable[[], Any]] = None) -> None:
        self._connection_factory = connection_factory or self._get_db_connection
        self.conn = conn or self._connection_factory()
        self._web_ai_calls = 0        # per-job budget counter for the web/LLM price fallback
        # CATALOGUE ROWS REFUSED FOR A BAD UNIT, so the refusal is visible rather than
        # merely correct. Falling through silently looks exactly like an empty catalogue,
        # and would send somebody chasing price files that are already loaded.
        self.catalogue_quarantine: List[str] = []

    def __enter__(self) -> "PricingService":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        try:
            if self.conn is not None:
                self.conn.close()
        except Exception:
            pass

    def _get_db_connection(self):
        if pyodbc is None:
            raise RuntimeError("pyodbc is required for PricingService")
        c = config.PRICE_SOURCE_CONFIG.get("sqlserver", {})
        conn_str = (
            f"DRIVER={{{c.get('driver', 'ODBC Driver 18 for SQL Server')}}};"
            f"SERVER={c.get('server')};DATABASE={c.get('database')};"
            f"UID={c.get('username')};PWD={c.get('password')};"
            "Encrypt=yes;TrustServerCertificate=yes;"
        )
        _conn = pyodbc.connect(conn_str, timeout=30)   # login/connect timeout
        # QUERY-execution timeout — the connect timeout above does NOT bound a running query, so a
        # slow/locked query on SDILive blocks the whole estimate forever (0 CPU). Bound it: a query
        # that overruns raises instead of hanging, and _fetch_*_with_retry degrades to no-price for
        # that part (flagged) while the run finishes. Config lever, default 30s.
        try:
            _pol = getattr(config, "FALLBACK_PRICING_POLICY", {}) or {}
            _conn.timeout = int(_pol.get("sql_query_timeout_s", 30))
        except Exception:
            pass
        return _conn

    def _is_connection_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        tokens = ("connection", "closed", "08s01", "08003", "communication link failure")
        return any(token in message for token in tokens)

    def _is_query_timeout(self, exc: Exception) -> bool:
        """A pyodbc query-execution timeout (conn.timeout). SQLSTATE HYT00 / 'timeout expired'."""
        message = str(exc).lower()
        return "hyt00" in message or "timeout expired" in message or "query timeout" in message

    def _rounding_mode(self) -> str:
        policy = getattr(config, "ROUNDING_POLICY", {}) or {}
        return str(policy.get("mode", "final_total_only")).strip().lower()

    def _money_decimals(self) -> int:
        policy = getattr(config, "ROUNDING_POLICY", {}) or {}
        return int(policy.get("money_decimals", 2))

    def _round_money(self, value: Any) -> float:
        try:
            numeric = float(value or 0.0)
        except (TypeError, ValueError):
            numeric = 0.0
        return round(numeric, self._money_decimals())

    def _fetch_one_with_retry(self, query: str, params: List[Any]) -> Any:
        for attempt in range(2):
            cursor = None
            try:
                cursor = self.conn.cursor()
                cursor.execute(query, params)
                return cursor.fetchone()
            except Exception as exc:
                if attempt == 0 and self._is_connection_error(exc):
                    self.conn = self._connection_factory()
                    continue
                if self._is_query_timeout(exc):
                    # slow/locked query — abandon this lookup (part flags 'no price'), reconnect so
                    # subsequent parts still price, and never block the whole run on one query.
                    print(f"   [pricing] SQL query timed out — skipping this lookup, run continues", flush=True)
                    try:
                        self.conn = self._connection_factory()
                    except Exception:
                        pass
                    return None
                raise
            finally:
                if cursor is not None:
                    try:
                        cursor.close()
                    except Exception:
                        pass
        return None

    def _fetch_all_with_retry(self, query: str, params: List[Any]) -> List[Any]:
        for attempt in range(2):
            cursor = None
            try:
                cursor = self.conn.cursor()
                cursor.execute(query, params)
                return cursor.fetchall()
            except Exception as exc:
                if attempt == 0 and self._is_connection_error(exc):
                    self.conn = self._connection_factory()
                    continue
                if self._is_query_timeout(exc):
                    print(f"   [pricing] SQL query timed out — skipping this lookup, run continues", flush=True)
                    try:
                        self.conn = self._connection_factory()
                    except Exception:
                        pass
                    return []
                raise
            finally:
                if cursor is not None:
                    try:
                        cursor.close()
                    except Exception:
                        pass
        return []

    def _freshness_adjustment(self, raw_date: Any) -> Dict[str, Any]:
        if raw_date is None:
            return {"bucket": "unknown", "age_days": None, "penalty": 0.15}
        parsed = None
        text = str(raw_date).strip().replace("T", " ")
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d/%m/%Y"):
            try:
                parsed = datetime.strptime(text[:19], fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            return {"bucket": "unknown", "age_days": None, "penalty": 0.15}
        age_days = max(0, (datetime.now(timezone.utc).date() - parsed.date()).days)
        if age_days <= 30:
            return {"bucket": "fresh", "age_days": age_days, "penalty": 0.0}
        if age_days <= 120:
            return {"bucket": "stale", "age_days": age_days, "penalty": 0.08}
        return {"bucket": "old", "age_days": age_days, "penalty": 0.2}

    _BOUGHT_IN_PART_NUMBER_RE = re.compile(
        r"^(M\d|ESSENTRA|ESS-|LED|LAMP|SCREW|NUT|BOLT|WASHER|RIVET|PIN|STUD|CLIP|SPRING|BEARING|WHEEL|CASTOR|SWIVEL)",
        re.IGNORECASE,
    )
    _BOUGHT_IN_DESC_KEYWORDS = (
        "SCREW", "NUT", "BOLT", "WASHER", "RIVET", "FASTENER",
        "LED LIGHT", "LED PANEL", "LIGHT PANEL", "LENS COVER", "GRAPHIC",
        "ESSENTRA", "NYLON", "THUMB SCREW", "KNURLED",
        "CASTOR", "WHEEL", "BEARING", "SPRING",
    )

    @staticmethod
    def _is_bought_in_heuristic(part: Dict[str, Any]) -> bool:
        pn = str(part.get("part_number") or "").strip().upper()
        desc = str(part.get("description") or "").strip().upper()
        if PricingService._BOUGHT_IN_PART_NUMBER_RE.match(pn):
            return True
        return any(kw in desc for kw in PricingService._BOUGHT_IN_DESC_KEYWORDS)

    def _get_udef_anchor(self, part: Dict[str, Any]) -> Dict[str, Any] | None:
        """
        UDEF anchor lookup against dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING.

        Live column names (confirmed via sp_help 2026-05-15):
          [Part code], [Part rev], [Description], [UOM], [System cost per],
          [Supplier code], [Supplier name], [WO Est lab cost], [WO Est mat cost],
          [WO Actual lab cost], [WO Actual mat cost]

        Collation: Latin1_General_BIN (binary, case-sensitive).
        [Supplier name] exists directly on UDEF — no SUP_TBL join needed.
        WO cost columns are surfaced for parity comparison.
        """
        part_code = str(part.get("part_number") or "").strip()
        desc = str(part.get("description") or "").strip()

        # A CATEGORY WORD IS NOT A CODE, AND THE GUARD IN lookup_keys DID NOT REACH HERE.
        # Refusing FIXING as a supplier-reference key stopped the two reference arms below
        # asking about it. It did nothing about the query at the bottom of this method, which
        # takes part["part_number"] raw — so `[Part code] = 'FIXING'` was still being asked.
        #
        # THAT DID NOT MISPRICE ANYTHING, AND IT DID SOMETHING ELSE INSTEAD. The catch-all
        # FIXING row in UDEF is priced GBP 0.00, so the price check below returns None and no
        # figure escapes. But the query is TOP 1 ordered exact-code-first, so the £0.00 row is
        # the ONE row that comes back and the description arm of the same query never gets to
        # answer. A generic fixing line therefore left UDEF empty-handed whether or not its
        # description matched something — blinded rather than mispriced. The ~900 MISC rows,
        # all £0.00, do exactly the same to every line coded MISC.
        #
        # Dropping the code here restores the description arm and costs nothing: a category
        # word could never have matched a real part by equality anyway.
        if part_code and self._is_category_word(part_code):
            part_code = ""
        code_param = part_code or None

        if not part_code and len(desc) < 8:
            return None

        # ── THE MANUFACTURER'S OWN NUMBER IS TRIED FIRST ────────────────────────────
        # The exact arm below can only ever match a code somebody typed into UDEF. When the
        # part number is one this engine minted — BI-BINDINGSCREW — that arm misses by
        # construction on every run, and the line falls to the description LIKE arm or to
        # nothing. 11650's feet, knobs and catches came out at GBP 0.00 that way while their
        # real references (466122, 246.41.745) sat unread in the descriptions they were
        # printed in.
        #
        # EXACT ONLY, AND THAT IS WHAT MAKES IT SAFE. A reference recovered from a description
        # is a guess about which characters are the key; matched loosely it could attach a
        # hinge's price to a foot. Matched exactly it either finds the row that carries that
        # article number or finds nothing, so a wrong guess costs one query and never a price.
        for key in supplier_reference.lookup_keys(part):
            if key == part_code:
                continue                      # the query below already tries the part's own code
            hit = self._fetch_one_with_retry(
                """
                SELECT TOP 1
                    u.[Part code], u.[Description], u.[Supplier name],
                    CAST(u.[System cost per] AS decimal(18,4)), u.[UOM],
                    u.[WO Est lab cost], u.[WO Est mat cost],
                    u.[WO Actual lab cost], u.[WO Actual mat cost]
                FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING u
                WHERE u.[Part code] = LTRIM(RTRIM(?)) AND u.[System cost per] > 0
                ORDER BY u.[Part code] ASC
                """,
                [key],
            )
            if hit:
                anchor = self._udef_row_to_anchor(hit, exact=True)
                if anchor:
                    anchor["matched_on"] = key
                    anchor["provenance"] += f" | matched on manufacturer reference {key}"
                    return anchor

        # ── AND UDEF IS NOT KEYED ON THE MANUFACTURER'S NUMBER ──────────────────────
        # [Part code] holds SDI's own code — FIXING1081, VINYL76 — so the exact arm above can
        # only fire once somebody loads a supplier price file on their article numbers. That
        # is the point of it. But the reference is already IN this table, in the description:
        # FIXING1081 reads "Essentra Ref. 466122 - Levelling Foot", and 466122 is exactly what
        # 11650's unpriced "ESSENTRA FOOT-466122" line carries. GBP 0.22 a foot, sitting in
        # the catalogue, unreachable because nobody looked in the text.
        #
        # LIKE, AND SAFE, FOR ONE REASON ONLY: EXACTLY ONE ROW MAY MATCH. A six-digit article
        # number inside a description is specific — but "specific" is a judgement and
        # "unique" is a fact, so the fact is what decides. Two matches is an ambiguity nobody
        # here can resolve, and this engine's existing rule for that (see the vinyl SKU
        # lookup) is to price nothing and say so rather than pick the dearer. Short keys are
        # refused outright: a three-character string appears inside a thousand descriptions.
        for key in supplier_reference.lookup_keys(part):
            if len(key) < 5 or supplier_reference.is_synthesised_key(key):
                continue
            rows = self._fetch_all_with_retry(
                """
                SELECT TOP 2
                    u.[Part code], u.[Description], u.[Supplier name],
                    CAST(u.[System cost per] AS decimal(18,4)), u.[UOM],
                    u.[WO Est lab cost], u.[WO Est mat cost],
                    u.[WO Actual lab cost], u.[WO Actual mat cost]
                FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING u
                WHERE u.[Description] LIKE '%' + LTRIM(RTRIM(?)) + '%'
                  AND u.[System cost per] > 0
                ORDER BY u.[Part code] ASC
                """,
                [key],
            ) or []
            if len(rows) != 1:
                continue
            anchor = self._udef_row_to_anchor(rows[0], exact=True)
            if anchor:
                anchor["matched_on"] = key
                anchor["provenance"] += (
                    f" | matched on manufacturer reference {key} found in the catalogue "
                    f"description (sole match)")
                return anchor

        row = self._fetch_one_with_retry(
            """
            SELECT TOP 1
                u.[Part code],
                u.[Description],
                u.[Supplier name],
                CAST(u.[System cost per] AS decimal(18,4)),
                u.[UOM],
                u.[WO Est lab cost],
                u.[WO Est mat cost],
                u.[WO Actual lab cost],
                u.[WO Actual mat cost]
            FROM dbo.UDEF_PARTS_TABLE_FOR_ESTIMATING u
            WHERE
                u.[Part code] = LTRIM(RTRIM(?))
                OR (
                    LEN(LTRIM(RTRIM(?))) >= 8
                    AND u.[Description] LIKE '%' + LTRIM(RTRIM(?)) + '%'
                )
            ORDER BY
                CASE WHEN u.[Part code] = LTRIM(RTRIM(?)) THEN 0 ELSE 1 END,
                u.[System cost per] DESC,
                u.[Part code] ASC,
                u.[Supplier name] ASC
            """,
            [code_param, desc, desc, code_param],
        )
        if not row:
            return None

        price = float(row[3] or 0.0)
        if price <= 0:
            return None

        matched_code = str(row[0] or "").strip()
        is_exact_code = bool(part_code) and part_code.upper() == matched_code.upper()

        # Fix A: UDEF's loose arms (part-code prefix LIKE, or description LIKE) can match a
        # generic stem to an unrelated expensive row, and the price-DESC tiebreaker then picks
        # the dearest (e.g. token "ELECTRICS" -> "ELECTRICS001" TTi LED panels £539.42;
        # "Foam Tape" -> "3M 5952F VHB roll" £131.50). For NON-exact matches, require genuine
        # token overlap between the query and the matched description, exactly as RAG does, so
        # a loose mismatch is rejected (-> falls through to RAG / LLM estimate) rather than
        # returning a wrong, expensive price. Exact part-code matches bypass the guard.
        if not is_exact_code:
            _query_tokens = self._tokenize(f"{desc} {str(part.get('normalized_material') or '')}")
            _match_score = self._token_overlap_score(_query_tokens, str(row[1] or ""))
            if _match_score < 0.45:
                return None

        return self._udef_row_to_anchor(row, exact=is_exact_code)

    def _udef_row_to_anchor(self, row: Any, *, exact: bool) -> Dict[str, Any] | None:
        """One UDEF row, as a priced anchor. Shared so the reference arm and the code arm
        cannot describe the same table differently."""
        price = float(row[3] or 0.0)
        if price <= 0:
            return None
        base_confidence = 0.95 if exact else 0.82
        freshness = self._freshness_adjustment(None)  # UDEF has no effective_date column

        wo_parity: Dict[str, Any] = {}
        wo_est_lab = float(row[5]) if row[5] is not None else None
        wo_est_mat = float(row[6]) if row[6] is not None else None
        wo_act_lab = float(row[7]) if row[7] is not None else None
        wo_act_mat = float(row[8]) if row[8] is not None else None
        if any(v is not None for v in [wo_est_lab, wo_est_mat, wo_act_lab, wo_act_mat]):
            wo_parity = {
                "wo_est_lab_cost": wo_est_lab,
                "wo_est_mat_cost": wo_est_mat,
                "wo_actual_lab_cost": wo_act_lab,
                "wo_actual_mat_cost": wo_act_mat,
                "wo_total_est": (wo_est_lab or 0) + (wo_est_mat or 0) if wo_est_lab or wo_est_mat else None,
                "wo_total_actual": (wo_act_lab or 0) + (wo_act_mat or 0) if wo_act_lab or wo_act_mat else None,
            }

        return {
            "source": "UDEF_PARTS_TABLE_FOR_ESTIMATING",
            "unit_price_gbp": price,
            "provenance": f"UDEF: {row[0]} — {row[1]} | supplier={row[2] or 'Unknown'} | uom={row[4] or 'each'}",
            "confidence": max(0.3, round(base_confidence - freshness["penalty"], 2)),
            "effective_date": None,
            "supplier_name": str(row[2] or "Unknown"),
            "uom": str(row[4] or "each"),
            "freshness": freshness,
            "wo_parity": wo_parity,
        }

    @staticmethod
    def _is_category_word(code: str) -> bool:
        """FIXING names a drawer; FIXING41 names a screw. Only one of them is a key.

        One predicate, imported rather than restated, so the code arms of this file and
        supplier_reference.lookup_keys cannot come to disagree about what a code is. Imported
        inside the function because part_code_conventions is an engine-side module and this
        file is imported by the backend service too.
        """
        try:
            from part_code_conventions import is_category_not_a_code   # noqa: PLC0415
        except ImportError:                                            # pragma: no cover
            return False
        return is_category_not_a_code(code)

    # ── TOKEN OVERLAP SCORING HELPERS ────────────────────────────────────────
    @staticmethod
    def _tokenize(text: str) -> set:
        """
        Split text into meaningful tokens for overlap scoring.
        Strips short/generic words common across SDI descriptions.
        """
        _STOP = {
            "the", "a", "an", "of", "for", "and", "or", "with", "to", "at",
            "in", "on", "by", "mm", "x", "thru", "all", "see", "do", "not",
            "drawing", "scale", "sheet", "rev", "date", "mild", "steel",
            "aluminium", "aluminum", "material", "matl", "finish", "colour",
        }
        tokens = re.findall(r"[A-Za-z0-9]+", str(text or "").upper())
        return {t for t in tokens if len(t) >= 2 and t.lower() not in _STOP}

    @staticmethod
    def _token_overlap_score(query_tokens: set, candidate_text: str) -> float:
        """Jaccard token overlap: intersection / union (0.0–1.0)."""
        if not query_tokens:
            return 0.0
        cand_tokens = PricingService._tokenize(candidate_text)
        if not cand_tokens:
            return 0.0
        intersection = len(query_tokens & cand_tokens)
        union = len(query_tokens | cand_tokens)
        return round(intersection / union, 4) if union else 0.0

    @staticmethod
    def _match_quality_label(score: float) -> str:
        if score >= 0.35:
            return "strong"
        if score >= 0.15:
            return "moderate"
        return "weak"

    def _get_pma_purchased(self, part: Dict[str, Any]) -> Dict[str, Any] | None:
        """
        Tier 1.5 — dbo.PMA_TBL (Access Supply Chain parts master).

        Purchased items: ``PMA_PROC_CODE = 'P'``. Unit material cost: ``PMA_COST_MAT`` (per unit).

        Match: exact ``PMA_PART_ONLY``, else token overlap on ``PMA_DESC_3`` (min score 0.35).
        """
        part_code = (part.get("part_number") or "").strip()
        description = (part.get("description") or "").strip()

        # THE ARM THAT COULD ACTUALLY RETURN A WRONG FIGURE. Unlike UDEF above, this query
        # filters PMA_COST_MAT > 0 in SQL, so a catch-all row here is not saved by being
        # priced zero — it is EXCLUDED from being zero. If Access Supply Chain holds any row
        # whose PMA_PART_ONLY is literally FIXING or MISC and carries a cost, the loop below
        # takes it on the exact-code branch at score 1.0 and returns it at confidence 0.88.
        # A socket cap screw, a button head and an aluminium rivet would all cost the same,
        # with the strongest confidence the chain can express, because an exact code match is
        # never ambiguous. It is just wrong.
        #
        # Dropping the code also takes the class word out of query_tokens below, which is
        # right: "FIXING" scoring against PMA_DESC_3 rewards rows for being fixings.
        if part_code and self._is_category_word(part_code):
            part_code = ""
        code_param = part_code or None

        if not part_code and not description:
            return None

        query = """
            SELECT TOP (60)
                PMA_PART_ONLY,
                PMA_DESC_3,
                PMA_COST_MAT,
                PMA_PRIME_SUP
            FROM dbo.PMA_TBL
            WHERE PMA_PROC_CODE = 'P'
              AND PMA_COST_MAT IS NOT NULL
              AND PMA_COST_MAT > 0
              AND (
                  LTRIM(RTRIM(PMA_PART_ONLY)) = LTRIM(RTRIM(?))
                  OR PMA_DESC_3 LIKE '%' + LTRIM(RTRIM(?)) + '%'
              )
            ORDER BY
                CASE WHEN LTRIM(RTRIM(PMA_PART_ONLY)) = LTRIM(RTRIM(?)) THEN 0 ELSE 1 END,
                PMA_COST_MAT DESC
        """
        desc_keyword = description[:60] if description else part_code
        try:
            rows = self._fetch_all_with_retry(query, [code_param, desc_keyword, code_param])
        except Exception:
            return None
        if not rows:
            return None

        query_tokens = self._tokenize(f"{part_code} {description}")
        best_row = None
        best_score = 0.0

        for row in rows:
            pn, desc3, cost_mat, supplier = row
            if pn and pn.strip().upper() == part_code.upper():
                best_row = row
                best_score = 1.0
                break
            candidate_text = f"{pn or ''} {desc3 or ''}"
            score = self._token_overlap_score(query_tokens, candidate_text)
            if score > best_score:
                best_score = score
                best_row = row

        if best_row is None or best_score < 0.35:
            return None

        pn, desc3, cost_mat, supplier = best_row
        unit_price = float(cost_mat)
        if unit_price <= 0:
            return None

        match_label = self._match_quality_label(best_score)
        confidence = min(0.88, 0.55 + best_score * 0.35)

        return {
            "source": "PMA_TBL",
            "source_type": "erp_parts_master",
            "unit_price_gbp": round(unit_price, 4),
            "confidence": round(confidence, 3),
            "provenance": (
                f"ERP Parts Master [{match_label}]: {pn} — {(desc3 or '')[:60]}"
                f" | supplier={supplier or 'SDI'} | PMA_COST_MAT={unit_price:.4f}"
            ),
            "supplier_name": supplier or "SDI",
            "part_code": pn,
            "review_required": best_score < 0.65,
            "review_reason": (
                None
                if best_score >= 0.65
                else f"PMA match confidence {best_score:.0%} — verify part number"
            ),
        }

    def _get_historical_rag(self, part: Dict[str, Any]) -> Dict[str, Any] | None:
        """
        RAG lookup against dbo.historical_quote_material_line with token overlap scoring.

        Fetches up to 40 LIKE candidates from SQL then re-ranks in Python by
        Jaccard token overlap against the part description + material.
        """
        # With the broad per-token candidate fetch above, a low threshold lets weak/wrong
        # matches through (e.g. "Earth strap" -> "Strap Mount" at 0.33, "GU10 downlight" ->
        # "LED Support" at 0.25). 0.45 cleanly keeps genuine matches (loom 0.75, adhesive
        # cable / dome rivet / foam tape all 0.50) while rejecting the junk so those items
        # correctly fall through to the LLM/market estimate instead of a wrong historical price.
        _MIN_OVERLAP = 0.45
        _CANDIDATES = 80

        desc = str(part.get("description") or "").strip()
        material = str(part.get("normalized_material") or "").strip()
        if not desc and not material:
            return None

        query_tokens = self._tokenize(f"{desc} {material}")
        if not query_tokens:
            return None

        # Fetch candidates by ANY individual significant token (broad fetch), then let the
        # Jaccard scorer below rank precisely. The previous whole-phrase LIKE required the
        # entire description as one contiguous substring, so near-perfect matches were never
        # even fetched (e.g. "ELECTRICS - 50cm LOOM" does not contain the full phrase
        # "50cm LOOM LIGHTING ELECTRICS"). Broad fetch + precise score is the correct design.
        # Use the longest tokens first (most distinctive) and cap how many drive the OR.
        like_tokens = sorted(query_tokens, key=len, reverse=True)[:6]
        if not like_tokens:
            return None
        like_clause = " OR ".join(
            ["UPPER(hml.line_description) LIKE '%' + UPPER(?) + '%'"] * len(like_tokens)
        )

        try:
            rows = self._fetch_all_with_retry(
                f"""
                SELECT TOP (?)
                    hml.line_description,
                    hml.unit_price_gbp,
                    hml.line_total_gbp,
                    hh.drawing_number,
                    hh.quote_date,
                    hml.part_code,
                    hml.supplier_name
                FROM dbo.historical_quote_material_line hml
                LEFT JOIN dbo.historical_quote_header hh
                    ON hml.quote_id = hh.quote_id
                WHERE hml.unit_price_gbp IS NOT NULL
                  AND hml.unit_price_gbp > 0
                  AND ({like_clause})
                ORDER BY
                    CASE WHEN hh.quote_date IS NOT NULL THEN 0 ELSE 1 END,
                    hh.quote_date DESC,
                    -- NOT line_total_gbp. That column is unit_price multiplied by something
                    -- that is not a quantity: 1.8568 x 259,061,659,935, and the multiplier
                    -- 7,350,844 is a PART NUMBER -- 7350845 is a lens cover in our own
                    -- catalogue. Ordering by it resolves a same-date tie in favour of
                    -- whichever line has the bigger part code, which is a coin toss wearing
                    -- a suit. The unit price is at least a real number about this part.
                    COALESCE(hml.unit_price_gbp, 0) DESC
                """,
                [_CANDIDATES] + like_tokens,
            )
        except Exception:
            return None

        if not rows:
            return None

        scored: List[tuple] = []
        for row in rows:
            score = self._token_overlap_score(query_tokens, str(row[0] or ""))
            if score >= _MIN_OVERLAP and row[1] is not None and float(row[1] or 0) > 0:
                scored.append((score, row))

        # No "take the first priced row anyway" fallback: with the broad per-token fetch,
        # the first fetched row is often unrelated. If nothing clears _MIN_OVERLAP, return
        # None so the item correctly falls through to the LLM/market estimate rather than
        # being assigned a wrong historical price.
        if not scored:
            return None

        best_score, best_row = max(scored, key=lambda x: x[0])
        price = float(best_row[1] or 0.0)
        freshness = self._freshness_adjustment(best_row[4])

        return {
            "source": "historical_quote_material_line",
            "unit_price_gbp": price,
            "provenance": (
                f"Historical RAG [{best_score:.0%} match]: {best_row[0]} "
                f"| Drawing: {best_row[3] or 'unknown'} "
                f"| Date: {str(best_row[4] or 'unknown')[:10]} "
                f"| Part: {best_row[5] or 'unknown'} "
                f"| Supplier: {best_row[6] or 'unknown'}"
            ),
            "confidence": max(0.3, round((0.75 + best_score * 0.15) - freshness["penalty"], 2)),
            "token_overlap_score": best_score,
            "effective_date": str(best_row[4])[:10] if best_row[4] else None,
            "drawing_number": best_row[3],
            "part_code": best_row[5],
            "supplier_name": best_row[6],
            "freshness": freshness,
        }

    def get_top_historical_matches(self, part: Dict[str, Any], k: int) -> List[Dict[str, Any]]:
        """
        Top-k historical material line matches for parity reporting (overlap-ranked).
        """
        desc = str(part.get("description") or "").strip()
        part_code = str(part.get("part_number") or "").strip()
        material = str(part.get("normalized_material") or "").strip()
        search_term = desc or part_code or material
        if not search_term:
            return []
        top_k = max(1, min(25, int(k)))
        fetch_n = max(top_k, 40)
        try:
            rows = self._fetch_all_with_retry(
                """
                SELECT TOP (?)
                    hml.line_description,
                    hml.unit_price_gbp,
                    hml.line_total_gbp,
                    hml.part_code,
                    hh.drawing_number,
                    hh.quote_date,
                    hh.customer_name,
                    hml.qty_per_unit,
                    hml.supplier_name
                FROM dbo.historical_quote_material_line hml
                LEFT JOIN dbo.historical_quote_header hh
                    ON hml.quote_id = hh.quote_id
                WHERE hml.unit_price_gbp IS NOT NULL
                  AND hml.unit_price_gbp > 0
                  AND UPPER(hml.line_description) LIKE '%' + UPPER(LTRIM(RTRIM(?))) + '%'
                ORDER BY
                    CASE WHEN hh.quote_date IS NOT NULL THEN 0 ELSE 1 END,
                    hh.quote_date DESC,
                    -- NOT line_total_gbp. That column is unit_price multiplied by something
                    -- that is not a quantity: 1.8568 x 259,061,659,935, and the multiplier
                    -- 7,350,844 is a PART NUMBER -- 7350845 is a lens cover in our own
                    -- catalogue. Ordering by it resolves a same-date tie in favour of
                    -- whichever line has the bigger part code, which is a coin toss wearing
                    -- a suit. The unit price is at least a real number about this part.
                    COALESCE(hml.unit_price_gbp, 0) DESC
                """,
                [fetch_n, search_term],
            )
        except Exception:
            try:
                rows = self._fetch_all_with_retry(
                    """
                    -- THE HEADER IS JOINED HERE TOO, AND IT WAS NOT BEFORE.
                    --
                    -- This fallback took TOP (n) ordered by line_total_gbp, which is the only
                    -- sort key -- so it did not merely break a tie, it decided which rows were
                    -- CONSIDERED AT ALL before any token scoring happened. And that column is
                    -- unit_price multiplied by a part number, so the candidate pool was ranked
                    -- by part-code magnitude. A comparable that never gets fetched cannot be
                    -- scored, and nothing downstream could tell it had been passed over.
                    --
                    -- Recency is what the primary query already sorts by, and what
                    -- _freshness_adjustment already values. Same rule in both places.
                    SELECT TOP (?)
                        hml.line_description, hml.unit_price_gbp, hml.line_total_gbp,
                        hml.part_code, NULL, hh.quote_date, NULL, hml.qty_per_unit,
                        hml.supplier_name
                    FROM dbo.historical_quote_material_line hml
                    LEFT JOIN dbo.historical_quote_header hh ON hml.quote_id = hh.quote_id
                    WHERE hml.unit_price_gbp IS NOT NULL AND hml.unit_price_gbp > 0
                      AND UPPER(hml.line_description) LIKE '%' + UPPER(LTRIM(RTRIM(?))) + '%'
                    ORDER BY
                        CASE WHEN hh.quote_date IS NOT NULL THEN 0 ELSE 1 END,
                        hh.quote_date DESC,
                        COALESCE(hml.unit_price_gbp, 0) DESC
                    """,
                    [fetch_n, search_term],
                )
            except Exception:
                return []

        query_tokens = self._tokenize(f"{desc} {material}")
        scored_rows: List[tuple] = []
        for row in rows:
            score = self._token_overlap_score(query_tokens, str(row[0] or "")) if query_tokens else 0.0
            scored_rows.append((score, row))
        scored_rows.sort(key=lambda x: -x[0])

        matches: List[Dict[str, Any]] = []
        for score, row in scored_rows[:top_k]:
            freshness = self._freshness_adjustment(row[5])
            matches.append({
                "line_description": row[0],
                "unit_price_gbp": float(row[1]),
                "line_total_gbp": float(row[2] or 0.0),
                "part_code": row[3],
                "drawing_number": row[4],
                "quote_date": str(row[5])[:10] if row[5] else None,
                "customer_name": row[6],
                "qty_per_unit": float(row[7]) if row[7] else None,
                "supplier_name": row[8],
                "token_overlap_score": score,
                "match_quality": self._match_quality_label(score),
                "confidence": max(0.3, round((0.65 + score * 0.15) - freshness["penalty"], 2)),
                "freshness": freshness,
                "source": "historical_quote_material_line",
            })
        return matches

    def _get_bought_in_part(self, part: Dict[str, Any]) -> Dict[str, Any] | None:
        part_code = str(part.get("part_number") or "").strip()
        desc = str(part.get("description") or "").strip()
        if not part_code and len(desc) < 5:
            return None
        # THE TABLE THE INGESTER ACTUALLY WRITES TO.
        #
        # This read dbo.bought_in_parts, which a migration emptied by setting every row
        # is_active = 0. The successor is AIEstimating.BoughtInCatalogue, and that is where
        # supplier_price_list.py -> catalogue_loader.upsert_catalogue puts every price file.
        # So the rung was reading one table while the only thing that fills it wrote to
        # another: load Elite, Eagle and Thermaset perfectly and rung 3 still returns
        # nothing, silently, with the work feeling done.
        #
        # WHY THE SOURCE FILTER IS NOT OPTIONAL. Inspecting the successor's live rows before
        # repointing found four kinds of price sitting side by side:
        #
        #     migrated:dbo.bip                 real net, carried over from the old table
        #     supplier_file:<name>             a supplier's own price list
        #     web_indicative:<date>            A WEB GUESS
        #     rag_fallback:workbook:<job>      a figure lifted from one historical workbook
        #     sdi_estimate:<date>              our own estimate of what something costs
        #     parallel-run:<job> ? UNCONFIRMED and one of these at GBP 0.0000
        #
        # Rung 3 answers at 0.93 / 0.80 -- above historical comparables, and far above the
        # 0.68 ceiling the web/LLM rung is deliberately capped at. Serving those last four
        # here would launder an indication into a firm price and rank it above real evidence.
        # This table is supposed to mean WHAT WE PAY.
        #
        # An ALLOWLIST, which fails closed. A denylist would admit the next indicative source
        # somebody adds, and admit it silently; a missing allowlist entry shows up as a rung
        # that answers nothing, which is visible. _FIRM_CATALOGUE_SOURCES is the one place.
        firm = "(" + " OR ".join(["c.source LIKE ?"] * len(_FIRM_CATALOGUE_SOURCES)) + ")"
        row = self._fetch_one_with_retry(
            f"""
            SELECT TOP 1 c.supplier_sku, c.description, c.unit_price_gbp, s.name, c.uom
            FROM AIEstimating.BoughtInCatalogue c
            LEFT JOIN AIEstimating.Supplier s ON s.supplier_id = c.supplier_id
            WHERE c.effective_to IS NULL
              AND c.unit_price_gbp > 0
              AND {firm}
              AND (
                  UPPER(LTRIM(RTRIM(c.supplier_sku))) = UPPER(LTRIM(RTRIM(?)))
                  OR (LEN(LTRIM(RTRIM(?))) >= 5 AND UPPER(c.description) LIKE '%' + UPPER(LTRIM(RTRIM(?))) + '%')
              )
            ORDER BY
                CASE WHEN UPPER(LTRIM(RTRIM(c.supplier_sku))) = UPPER(LTRIM(RTRIM(?))) THEN 0 ELSE 1 END,
                c.effective_from DESC,
                c.unit_price_gbp ASC,
                c.item_id ASC
            """,
            [*(f"{s}%" for s in _FIRM_CATALOGUE_SOURCES), part_code, desc, desc, part_code],
        )
        if not row or row[2] is None:
            return None
        price = float(row[2] or 0.0)
        if price <= 0:
            return None

        # QUARANTINE A ROW WHOSE UNIT ARGUES WITH ITS OWN DESCRIPTION.
        #
        # FIXING1784 is in this table now: "Edging Seal Strip 10m Roll (Rubusec)", uom
        # "metre", GBP 29.80. That figure is the ROLL. Per metre it is GBP 2.98, so two
        # metres of edging cost GBP 59.60 instead of GBP 5.96 -- and nothing downstream
        # questions it, because the price and the unit are each plausible and only wrong
        # together. It is a migrated: row, so the allowlist admits it.
        #
        # DONE HERE AND NOT ONLY IN THE LOADER. The loader guards what it writes; these
        # twenty-two rows were written by a migration long before it existed. A check only
        # the importer runs cannot protect a table that was filled before the importer was.
        #
        # It FALLS THROUGH rather than raising. The next rung is historical comparables --
        # where this line went yesterday and where it goes again. A worse answer than a good
        # catalogue row, and a far better one than a tenfold overcharge.
        try:
            from unit_parsing import unit_conflicts
            why = unit_conflicts(str(row[1] or ""), str(row[4] or ""))
        except Exception:                                        # noqa: BLE001
            why = ""                                             # never fail a price over this
        if why:
            note = (f"{row[0]}: {why}. Priced from the next source instead -- correct the "
                    f"uom or the price in AIEstimating.BoughtInCatalogue.")
            if note not in self.catalogue_quarantine:
                self.catalogue_quarantine.append(note)
            return None

        matched = str(row[0] or "").strip().upper()
        base_confidence = 0.93 if part_code.strip().upper() == matched else 0.80
        return {
            # The KEY stays "bought_in_parts" -- it names the RUNG, and the parity report,
            # the audit and the provenance icons all key off it. The human-readable line
            # names the table actually read, so nobody hunts for this row in the empty one.
            "source": "bought_in_parts",
            "unit_price_gbp": price,
            "provenance": (f"Bought-in catalogue: {row[0]} ({row[1]}) "
                           f"supplier={row[3] or 'unrecorded'} per {row[4] or 'each'} "
                           f"[AIEstimating.BoughtInCatalogue]"),
            "confidence": base_confidence,
            "supplier_name": row[3] or "Unknown",
            "uom": row[4] or "each",
        }

    def _get_supplier_catalog(self, part: Dict[str, Any]) -> Dict[str, Any] | None:
        material_hint = str(part.get("normalized_material") or "").strip()
        desc = str(part.get("description") or "").strip()
        search = material_hint or desc
        if not search:
            return None
        try:
            row = self._fetch_one_with_retry(
                """
                SELECT TOP 1
                    catalog_url,
                    material_hint,
                    unit_price_gbp,
                    sort_order
                FROM dbo.estimating_supplier_catalog_url
                WHERE UPPER(material_hint) LIKE '%' + UPPER(LTRIM(RTRIM(?))) + '%'
                ORDER BY sort_order ASC, unit_price_gbp ASC, catalog_url_id ASC
                """,
                [search],
            )
        except Exception:
            return None
        if not row or row[2] is None:
            return None
        price = float(row[2] or 0.0)
        if price <= 0:
            return None
        return {
            "source": "estimating_supplier_catalog_url",
            "unit_price_gbp": price,
            "provenance": f"Supplier catalog: {row[1]} — {row[0]}",
            "catalog_url": row[0],
            "material_hint": row[1],
            "sort_order": row[3],
            "confidence": 0.65,
            "review_flag": True,
            "review_reason": "Indicative catalog price — verify against current supplier quote.",
        }

    def _select_anchor_price_source(self, part: Dict[str, Any]) -> Dict[str, Any]:
        udef = self._get_udef_anchor(part)
        if udef:
            return udef
        pma = self._get_pma_purchased(part)
        if pma:
            return pma
        bought = self._get_bought_in_part(part)
        if bought:
            return bought
        historical = self._get_historical_rag(part)
        if historical:
            return historical
        catalog = self._get_supplier_catalog(part)
        if catalog:
            return catalog
        fallback_policy = getattr(config, "FALLBACK_PRICING_POLICY", {}) or {}
        if fallback_policy.get("enable_web_ai_fallback") and self._web_ai_fallback_allowed(part, fallback_policy):
            self._web_ai_calls += 1
            web_result = self._get_web_ai_fallback(part)
            if web_result:
                return web_result
        is_bought_in = self._is_bought_in_heuristic(part)
        return {
            "source": "fallback",
            "unit_price_gbp": 0.0,
            "confidence": 0.0,
            "provenance": "No price source found — add to bought_in_parts or UDEF_PARTS_TABLE_FOR_ESTIMATING",
            "review_required": True,
            "review_reason": (
                "Standard bought-in item with no price in UDEF or bought_in_parts. "
                "Add to Access Supply Chain or enable web/AI fallback."
                if is_bought_in else
                "No price found in any source. Add material to material_prices table or enable web/AI fallback."
            ),
        }

    def _web_ai_fallback_allowed(self, part: Dict[str, Any], fallback_policy: Dict[str, Any]) -> bool:
        """Gate the web/LLM fallback so it prices without ever hanging the run:
          - skip rollup/assembly parents (no own price; searching them is wasted time), and
          - stop once the per-job budget is spent (the rest flag 'estimator to confirm').
        """
        # A MARKET PRICE ONLY MEANS ANYTHING FOR SOMETHING YOU CAN BUY. The question here is
        # not "does this look like a parent" but "do we make this part?" — because if we make
        # it, there is no market price to find, and asking produces a confident number for a
        # code no supplier has ever listed. 12120-01-101 and -103 are ours; an LLM priced
        # them anyway, and those figures reached the total.
        #
        # Fabrication evidence is the general test — geometry we could actually cut from, or
        # an operation a purchased component can never incur. It keys on what the part IS, so
        # a drawing nobody has seen yet is judged the same way. The parent heuristics below
        # stay as a second net for records that arrive without either.
        try:
            from bought_in_policy import FABRICATION_OPS, has_fabrication_evidence
            _ops = {str(o).strip().lower() for o in
                    ((part.get("textual_operations") or []) + (part.get("inferred_operations") or []))}
            if has_fabrication_evidence(part) or (_ops & FABRICATION_OPS):
                return False
        except ImportError:
            pass
        if part.get("bom_children") or part.get("children"):
            return False       # it has parts under it, so its cost comes from them

        if fallback_policy.get("skip_rollup_parents", True):
            _pn = str(part.get("part_number") or "").upper()
            _desc = str(part.get("description") or "").upper()
            _is_parent = (
                bool(part.get("is_assembly_parent")) or bool(part.get("is_sub_assembly"))
                or "weldment_parent_material_suppressed" in [str(f).lower() for f in (part.get("reliability_flags") or [])]
                or str(part.get("cost_method") or "").lower().startswith("weldment_parent")
                or _pn.endswith("-GA") or "-GA-" in _pn
                or any(t in _desc for t in ("WELDMENT", "ASSEMBLY", "SUB ASSEMBLY", "SUB-ASSEMBLY"))
            )
            if _is_parent:
                return False
        try:
            _budget = int(fallback_policy.get("max_web_ai_lookups_per_job", 25))
        except (TypeError, ValueError):
            _budget = 25
        if _budget >= 0 and self._web_ai_calls >= _budget:
            if self._web_ai_calls == _budget:
                # log once when the cap is first hit
                try:
                    print(f"   [pricing] web/AI fallback budget reached ({_budget}) — remaining "
                          f"unpriced parts flagged 'estimator to confirm' (config "
                          f"FALLBACK_PRICING_POLICY.max_web_ai_lookups_per_job)", flush=True)
                except Exception:
                    pass
                self._web_ai_calls += 1  # advance so the message prints only once
            return False
        return True

    def _standard_commodity_price(self, part: Dict[str, Any]) -> Dict[str, Any] | None:
        """A stable, reproducible provisional for a generically-named standard bought-in (a
        pallet) from config.STANDARD_COMMODITY_PRICE_GBP, or None. Reproducible (a fixed config
        number), so it prices the line AND clears price_not_reproducible — unlike the market
        guess it stands in front of. Flagged for review: it is a provisional, not a quote.

        The matching itself is DB-free config, so it lives in the module-level
        standard_commodity_price() below and the engine can reach the SAME table without a
        PricingService instance (see estimator._resolve_part_system_cost)."""
        return standard_commodity_price(part)

    def _get_web_ai_fallback(self, part: Dict[str, Any]) -> Dict[str, Any] | None:
        # STANDARD COMMODITY BEFORE THE MARKET GUESS. A generically-named bought-in the purchasing
        # DB cannot match — "PALLET", "STD PART" — reached this fallback and got a per-run LLM
        # number that changes every run (the castor moved £4.54 -> £8.54) or a £0. A config
        # provisional for a known standard commodity holds the line still at a sensible, REPRODUCIBLE
        # figure. Consulted only here, on the fallback path, so a real DB catalogue rate still wins.
        _commodity = self._standard_commodity_price(part)
        if _commodity is not None:
            return _commodity
        try:
            from web_ai_price_lookup import lookup_web_ai_price
        except ImportError:
            return None
        fallback_policy = getattr(config, "FALLBACK_PRICING_POLICY", {}) or {}
        conf_cap = float(fallback_policy.get("fallback_confidence_cap", 0.68))
        geom = part.get("normalized_geometry") or {}
        ops = list(dict.fromkeys(
            (part.get("textual_operations") or []) + (part.get("inferred_operations") or [])
        ))
        _spec = {
            "material": part.get("normalized_material") or part.get("material"),
            "description": part.get("description"),
            "thickness_mm": part.get("thickness_mm"),
            "part_code": part.get("part_number"),
            "finish": next(iter(part.get("surface_finishes") or []), None),
            "colour": next(iter(part.get("colours") or []), None),
            "quantity": part.get("quantity"),
            "length_mm": geom.get("blank_length_mm") or part.get("length_mm"),
            "width_mm": geom.get("blank_width_mm") or part.get("width_mm"),
            "weight_kg": geom.get("weight_kg"),
            "operations": ops[:6],
        }
        # HARD wall-clock timeout: run the (multi-call, network+LLM) lookup on a worker thread and
        # abandon it if it exceeds the budget. Even if an inner call has no timeout of its own, the
        # run never blocks — a slow part just falls through to 'no price, estimator to confirm'.
        try:
            _timeout_s = float(fallback_policy.get("web_ai_call_timeout_s", 25))
        except (TypeError, ValueError):
            _timeout_s = 25.0
        import concurrent.futures as _futures

        def _compute() -> Dict[str, Any]:
            # The lookup is multi-call (network + LLM) and can hang; run it on a worker thread
            # and abandon it past the budget so the run never blocks. A miss returns {} — never
            # stored, so tomorrow asks again rather than inheriting today's network problem.
            try:
                with _futures.ThreadPoolExecutor(max_workers=1) as _ex:
                    _fut = _ex.submit(lookup_web_ai_price, _spec,
                                      enable_web_search=True, enable_llm_estimate=True)
                    return _fut.result(timeout=_timeout_s) or {}
            except _futures.TimeoutError:
                print(f"   [pricing] web/AI fallback timed out ({_timeout_s:.0f}s) on "
                      f"{part.get('part_number') or _spec.get('description')} — flagged "
                      f"'estimator to confirm', run continues", flush=True)
                return {}
            except Exception:                                    # noqa: BLE001
                return {}

        # ASK ONCE PER SPECIFICATION AND STORE IT. A generated price that comes back GBP 4.54 one
        # run and GBP 8.54 the next is not a price the workbook will put in the column — it gets
        # withheld as a hint beside a zero, which on a pack of everyday bought-ins is most of the
        # BOM reading as free. The same content-addressed cache the sheet rates use makes this
        # per-piece figure hold still, so it is reproducible from the first run and PRICES the
        # line (tagged indicative), which is the whole point of asking the market at all.
        try:
            import generated_price_cache as _gpc
            _model = str(fallback_policy.get("llm_model") or "auto")
            result = _gpc.cached_estimate(_spec, "web_ai_price_lookup", _model, _compute)
        except Exception:                                        # noqa: BLE001
            result = _compute()          # the cache is a bonus, never a dependency
        if not result or not result.get("found") or not result.get("price_gbp"):
            return None
        capped_conf = min(float(result.get("confidence") or 0.45), conf_cap)
        return {
            "source": result.get("source_type", "web_ai_fallback"),
            "source_type": "web_ai_fallback",
            # Reproducible once cached: the same spec returns the same number next run, so the
            # column prices it instead of withholding it as an unrepeatable guess.
            "price_is_reproducible": bool(result.get("price_is_reproducible")),
            # WHICH ENGINE ANSWERED. The lookup records it and nothing carried it forward, so
            # the estimating sheet could only say "an AI" — true, but an estimator asking
            # where a price came from deserves the actual name, and if the provider is ever
            # switched the sheet says so without anybody editing a label.
            "llm_provider": result.get("llm_provider"),
            "unit_price_gbp": float(result["price_gbp"]),
            "confidence": capped_conf,
            "provenance": (
                f"Web/AI fallback: {result.get('source_type')} — "
                f"{result.get('price_basis', '')[:80]}"
            ),
            "review_flag": True,
            "review_reason": result.get("review_reason", "Indicative web/AI price — verify before quoting."),
            "web_query": result.get("web_query"),
            "supplier_name": result.get("supplier_name", "web/AI estimate"),
            "price_date": result.get("price_date"),
            "low_estimate_gbp": result.get("low_estimate_gbp"),
            "high_estimate_gbp": result.get("high_estimate_gbp"),
            "verify_against": result.get("verify_against", []),
        }

    def _get_labour_rate_from_db(self, operation_code: str) -> Dict[str, Any] | None:
        if not operation_code:
            return None
        op_map = {
            "laser_cutting": "LASM",
            "folding": "FOLD",
            "welding": "WELD",
            "powder_coating": "P/C",
            "wet_spray": "SPRY",
            "hole_machining": "DRIL",
            "cnc": "CNC",
            "bench_work": "BENC",
            "diamond_polish": "DPOL",
            "dress_welds": "DRES",
            "glue": "GLUE",
            "handling": "PACM",
            "assembly": "PACM",
        }
        dept_code = op_map.get(operation_code, operation_code.upper())
        try:
            row = self._fetch_one_with_retry(
                """
                SELECT TOP 1
                    operation_code,
                    hourly_rate_gbp,
                    department_code,
                    effective_date
                FROM dbo.labour_rates
                WHERE is_active = 1
                  AND (
                      LOWER(LTRIM(RTRIM(operation_code))) = LOWER(LTRIM(RTRIM(?)))
                      OR UPPER(LTRIM(RTRIM(department_code))) = UPPER(LTRIM(RTRIM(?)))
                  )
                ORDER BY effective_date DESC, hourly_rate_gbp ASC, labour_rate_id ASC
                """,
                [operation_code, dept_code],
            )
        except Exception:
            return None
        if not row or row[1] is None:
            return None
        rate = float(row[1] or 0.0)
        if rate <= 0:
            return None
        freshness = self._freshness_adjustment(row[3])
        return {
            "source": "dbo.labour_rates",
            "operation_code": row[0],
            "department_code": row[2],
            "hourly_rate_gbp": rate,
            "effective_date": str(row[3])[:10] if row[3] else None,
            "freshness": freshness,
            "confidence": max(0.5, round(0.95 - freshness["penalty"], 2)),
        }

    def _get_historical_operations(self, part: Dict[str, Any], k: int = 3) -> List[Dict[str, Any]]:
        desc = str(part.get("description") or "").strip()
        if not desc:
            return []
        try:
            rows = self._fetch_all_with_retry(
                """
                SELECT TOP (?)
                    hqo.operation_code,
                    hqo.department_code,
                    hqo.run_min_per_unit,
                    hqo.hourly_rate_gbp,
                    hqo.operation_cost_gbp,
                    hqo.setup_min,
                    hh.drawing_number,
                    hh.quote_date
                FROM dbo.historical_quote_operation hqo
                JOIN dbo.historical_quote_part hqp
                    ON hqo.quote_part_id = hqp.quote_part_id
                JOIN dbo.historical_quote_header hh
                    ON hqp.quote_id = hh.quote_id
                WHERE UPPER(hqp.normalized_description) LIKE '%' + UPPER(LTRIM(RTRIM(?))) + '%'
                  AND hqo.operation_cost_gbp IS NOT NULL
                ORDER BY hh.quote_date DESC, hqo.operation_cost_gbp DESC
                """,
                [k, desc],
            )
        except Exception:
            return []
        result: List[Dict[str, Any]] = []
        for row in rows:
            result.append({
                "operation_code": row[0],
                "department_code": row[1],
                "run_min_per_unit": float(row[2]) if row[2] else None,
                "hourly_rate_gbp": float(row[3]) if row[3] else None,
                "operation_cost_gbp": float(row[4]) if row[4] else None,
                "setup_min": float(row[5]) if row[5] else None,
                "drawing_number": row[6],
                "quote_date": str(row[7])[:10] if row[7] else None,
                "source": "historical_quote_operation",
            })
        return result

    def estimate_assembly_pack_labour(self, quantity: int = 1) -> Dict[str, Any]:
        """E2: per-bay assembly/pack labour, learned from dbo.historical_quote_operation.
        Takes the median run_min_per_unit of ASSEMBLE/PACK/COLLATE/PALLET/BULK operations
        and applies the config PACM (Assemble/pack) rate. History-derived and flagged;
        falls back to a config default, or flags 'not costed' — never a free guess."""
        pacm_rate = float((getattr(config, "HOURLY_RATES_GBP", {}) or {}).get("assembly") or 28.56)
        pol = getattr(config, "ASSEMBLY_LABOUR_POLICY", {}) or {}
        default_min = float(pol.get("default_minutes_per_bay") or 0.0)
        rows = []
        try:
            rows = self._fetch_all_with_retry(
                """
                SELECT TOP 400 hqo.operation_code, hqo.run_min_per_unit
                FROM dbo.historical_quote_operation hqo
                WHERE hqo.run_min_per_unit IS NOT NULL AND hqo.run_min_per_unit > 0
                  AND (UPPER(hqo.operation_code) LIKE '%ASSEMBLE%'
                    OR UPPER(hqo.operation_code) LIKE '%PACK%'
                    OR UPPER(hqo.operation_code) LIKE '%COLLATE%'
                    OR UPPER(hqo.operation_code) LIKE '%PALLET%'
                    OR UPPER(hqo.operation_code) LIKE '%BULK%')
                """,
                [],
            ) or []
        except Exception:
            rows = []
        mins = sorted(float(r[1]) for r in rows if r[1] and float(r[1]) > 0)
        if mins:
            median, basis, flag, sample = mins[len(mins) // 2], "historical_quote_operation_median", None, len(mins)
        elif default_min > 0:
            median, basis, flag, sample = default_min, "config_default", \
                "ASSEMBLY LABOUR PROVISIONAL \u2014 no history match; using config default", 0
        else:
            return {
                "assembly_minutes_per_bay": None, "rate_gbp_per_hour": pacm_rate,
                "cost_per_bay_gbp": None, "sample_size": 0, "basis": "unavailable",
                "flag": "ASSEMBLY LABOUR NOT COSTED \u2014 no history and no config default",
            }
        return {
            "assembly_minutes_per_bay": round(median, 1),
            "rate_gbp_per_hour": pacm_rate,
            "cost_per_bay_gbp": round(median / 60.0 * pacm_rate, 2),
            "sample_size": sample, "basis": basis, "flag": flag,
        }

    def _add_missing_weld_time(self, part: Dict[str, Any], wb_part: Dict[str, Any]) -> None:
        risk_flags = part.get("risk_flags") or []
        if "weld_required" not in risk_flags:
            return
        proc = wb_part.get("process_estimate") or {}
        times = proc.get("times_min") or {}
        if times.get("welding") or times.get("spot_welding"):
            return
        weld_policy = getattr(config, "WELD_TIME_POLICY", {}) or {}
        default_weld_min = float(weld_policy.get("default_weld_minutes_per_weldment", 15.0))
        default_dress_min = float(weld_policy.get("default_dress_weld_minutes", 10.0))
        fold_count = len(part.get("fold_values_mm") or []) or int(part.get("fold_count_textual") or 0)
        desc_upper = str(part.get("description") or "").upper()
        if "WELDMENT" in desc_upper or "ASSEMBLY" in desc_upper:
            weld_min = default_weld_min * max(1, min(fold_count, 4))
        else:
            weld_min = default_weld_min
        times["welding"] = round(weld_min, 1)
        if not times.get("dress_welds"):
            times["dress_welds"] = round(default_dress_min, 1)
        proc["times_min"] = times
        proc["weld_time_injected"] = True
        wb_part["process_estimate"] = proc

    def _resolve_effective_material_cost(
        self,
        part: Dict[str, Any],
        quantity: int,
        workbook_material_cost_gbp: float,
        anchor_price_source: Dict[str, Any],
    ) -> Dict[str, Any]:
        confidence = float(anchor_price_source.get("confidence", 0.0) or 0.0)
        unit_price = float(anchor_price_source.get("unit_price_gbp", 0.0) or 0.0)
        weight_kg = float((part.get("normalized_geometry") or {}).get("weight_kg") or 0.0)
        policy = getattr(config, "PRICING_SERVICE_POLICY", {}) or {}
        anchor_threshold = float(
            policy.get("anchor_override_min_confidence", 0.90)
        )
        scrap_factor = float(policy.get("anchor_override_scrap_factor", 1.04))

        is_bought_in = self._is_bought_in_heuristic(part)
        src = str(anchor_price_source.get("source") or "").lower()
        per_each_sources = (
            "udef_parts_table_for_estimating",
            "bought_in_parts",
            "pma_tbl",
        )

        if src == "pma_tbl" and unit_price > 0.0 and confidence >= 0.55:
            system_cost = unit_price * quantity
            return {
                "material_cost_gbp": float(system_cost),
                "material_pricing_mode": "pma_cost_mat_each",
                "anchor_applied": True,
                "anchor_threshold": anchor_threshold,
                "anchor_inputs": {
                    "confidence": confidence,
                    "unit_price_gbp": unit_price,
                    "weight_kg": weight_kg,
                    "note": "PMA_TBL PMA_COST_MAT — purchased part, per unit not per kg",
                },
            }

        if (
            is_bought_in
            and src in per_each_sources
            and unit_price > 0.0
            and confidence >= 0.70
        ):
            system_cost = unit_price * quantity
            return {
                "material_cost_gbp": float(system_cost),
                "material_pricing_mode": "system_cost_bought_in",
                "anchor_applied": True,
                "anchor_threshold": anchor_threshold,
                "anchor_inputs": {
                    "confidence": confidence,
                    "unit_price_gbp": unit_price,
                    "weight_kg": weight_kg,
                    "note": "bought-in item — priced each, not by weight",
                },
            }

        if src == "web_ai_fallback" and unit_price > 0.0:
            system_cost = unit_price * quantity
            return {
                "material_cost_gbp": float(system_cost),
                "material_pricing_mode": "web_ai_fallback",
                "anchor_applied": True,
                "anchor_threshold": anchor_threshold,
                "anchor_inputs": {
                    "confidence": confidence,
                    "unit_price_gbp": unit_price,
                    "weight_kg": weight_kg,
                    "note": "indicative web/AI price — verify before quoting",
                },
            }

        if confidence >= anchor_threshold and unit_price > 0.0 and weight_kg > 0.0:
            anchor_material_cost = weight_kg * unit_price * quantity * scrap_factor
            return {
                "material_cost_gbp": float(anchor_material_cost),
                "material_pricing_mode": "anchor_override",
                "anchor_applied": True,
                "anchor_threshold": anchor_threshold,
                "anchor_inputs": {
                    "confidence": confidence,
                    "unit_price_gbp": unit_price,
                    "weight_kg": weight_kg,
                    "scrap_factor": scrap_factor,
                },
            }

        return {
            "material_cost_gbp": float(workbook_material_cost_gbp),
            "material_pricing_mode": "workbook_primary",
            "anchor_applied": False,
            "anchor_threshold": anchor_threshold,
            "anchor_inputs": {
                "confidence": confidence,
                "unit_price_gbp": unit_price,
                "weight_kg": weight_kg,
                "scrap_factor": scrap_factor,
            },
        }

    def calculate_estimate(
        self,
        drawing_json: Dict[str, Any],
        historical_top_k: int = 5,
        save_to_db: bool = True,
    ) -> Dict[str, Any]:
        drawing_json = normalise_json(drawing_json)
        from config import WORKBOOK_INPUT_DEFAULTS, DEFAULT_JOB_QUANTITY
        default_qty = int(
            (WORKBOOK_INPUT_DEFAULTS or {}).get("default_job_quantity", DEFAULT_JOB_QUANTITY)
            or DEFAULT_JOB_QUANTITY or 1
        )
        if not drawing_json.get("assumed_job_quantity") and not drawing_json.get("quantity"):
            drawing_json["assumed_job_quantity"] = default_qty
        parts = drawing_json.get("manufacturing_writeup", {}).get("parts") or drawing_json.get("parts", [])
        workbook_estimate = estimate_document(parts, summary=drawing_json)
        part_estimates = workbook_estimate.get("part_estimates", [])
        estimate_lookup = {
            str(item.get("part_number") or ""): item for item in part_estimates if item.get("part_number")
        }
        priced_parts: List[Dict[str, Any]] = []

        rounding_mode = self._rounding_mode()
        for part in parts:
            part_number = str(part.get("part_number") or "")
            qty = max(1, int(round(float(part.get("quantity", 1) or 1))))
            wb = estimate_lookup.get(part_number, {})
            self._add_missing_weld_time(part, wb)
            historical_matches = self.get_top_historical_matches(part, k=historical_top_k)
            historical_operations = self._get_historical_operations(part, k=3)
            wb_breakdown = wb.get("cost_breakdown", {})
            wb_material = wb_breakdown.get("material", {})
            wb_labour = wb_breakdown.get("labour", {})
            db_rate_validation: Dict[str, Any] = {}
            for op_code in (wb_labour.get("costs_gbp") or {}).keys():
                db_rate = self._get_labour_rate_from_db(op_code)
                if db_rate:
                    config_rate = float(
                        (getattr(config, "HOURLY_RATES_GBP", {}) or {}).get(op_code) or 0.0
                    )
                    db_rate_validation[op_code] = {
                        "db_rate_gbp_hr": db_rate["hourly_rate_gbp"],
                        "config_rate_gbp_hr": config_rate,
                        "dept_code": db_rate.get("department_code"),
                        "rate_source": db_rate["source"],
                        "variance_pct": round(
                            abs(db_rate["hourly_rate_gbp"] - config_rate) / max(config_rate, 0.01) * 100, 1
                        ) if config_rate else None,
                        "effective_date": db_rate.get("effective_date"),
                    }
            anchor_price_source = self._select_anchor_price_source(part)
            workbook_unit_total_cost = float(wb.get("unit_total_cost_gbp") or 0.0)
            workbook_extended_total_cost = float(wb.get("extended_total_cost_gbp") or 0.0)
            workbook_material_cost = float(wb_material.get("extended_material_cost_gbp") or 0.0)
            labour_cost = float(wb_labour.get("total_labour_cost_gbp") or 0.0)
            effective_material = self._resolve_effective_material_cost(
                part=part,
                quantity=qty,
                workbook_material_cost_gbp=workbook_material_cost,
                anchor_price_source=anchor_price_source,
            )
            material_cost = float(effective_material["material_cost_gbp"])
            computed_extended_total_cost = material_cost + labour_cost
            unit_total_cost = computed_extended_total_cost / qty if qty else 0.0

            pricing_basis = wb_breakdown.get("costing_basis")
            if str(pricing_basis or "").startswith("system_cost_per_part"):
                computed_extended_total_cost = workbook_extended_total_cost
                unit_total_cost = workbook_unit_total_cost
            raw_extended_total_cost = float(computed_extended_total_cost)
            raw_unit_total_cost = float(unit_total_cost)

            priced_parts.append(
                {
                    "part_number": part_number,
                    "description": part.get("description"),
                    "quantity": qty,
                    "material_cost_gbp": self._round_money(material_cost),
                    "labour_cost_gbp": self._round_money(labour_cost),
                    "unit_total_cost_gbp": self._round_money(unit_total_cost),
                    "extended_total_cost_gbp": self._round_money(computed_extended_total_cost),
                    "unit_total_cost_raw_gbp": raw_unit_total_cost,
                    "extended_total_cost_raw_gbp": raw_extended_total_cost,
                    "pricing_basis": pricing_basis,
                    "price_source": anchor_price_source,
                    "joined_sources": {
                        "reverse_engineered_workbook": {
                            "material": wb_material,
                            "labour": wb_labour,
                            "system_cost": wb_breakdown.get("system_cost", {}),
                            "assumptions": wb_breakdown.get("assumptions", {}),
                        },
                        "anchor_lookup": anchor_price_source,
                        "material_decision": effective_material,
                    },
                    "top_historical_matches": historical_matches,
                    "historical_operations": historical_operations,
                    "db_labour_rate_validation": db_rate_validation,
                }
            )

        workbook_equivalent = workbook_estimate.get("workbook_equivalent_pricing", {})
        if rounding_mode == "per_line":
            material_total_raw = sum(float(item.get("material_cost_gbp") or 0.0) for item in priced_parts)
            labour_total_raw = sum(float(item.get("labour_cost_gbp") or 0.0) for item in priced_parts)
            grand_total_cost_raw = sum(float(item.get("extended_total_cost_gbp") or 0.0) for item in priced_parts)
        else:
            material_total_raw = sum(float(item.get("material_cost_gbp") or 0.0) for item in priced_parts)
            labour_total_raw = sum(float(item.get("labour_cost_gbp") or 0.0) for item in priced_parts)
            grand_total_cost_raw = sum(float(item.get("extended_total_cost_raw_gbp") or item.get("extended_total_cost_gbp") or 0.0) for item in priced_parts)
        if rounding_mode == "per_section":
            grand_total_cost_raw = material_total_raw + labour_total_raw
        material_total = self._round_money(material_total_raw)
        labour_total = self._round_money(labour_total_raw)
        grand_total_cost = self._round_money(grand_total_cost_raw)
        workbook_sell_price = workbook_equivalent.get("l111_sell_price_gbp")
        manufacturing_only = bool(getattr(config, "OUTPUT_MANUFACTURING_COST_ONLY", False))
        if manufacturing_only:
            sell_price = grand_total_cost
            margin_pct = None
        else:
            ws = float(workbook_sell_price or 0.0)
            sell_price = ws if ws > 0 else grand_total_cost * 1.30
            margin_pct = round(((sell_price - grand_total_cost) / sell_price) * 100.0, 1) if sell_price else None
        default_job_qty = int((getattr(config, "WORKBOOK_INPUT_DEFAULTS", {}) or {}).get("default_job_quantity", 1))
        order_qty = max(1, int(round(float(drawing_json.get("quantity", default_job_qty) or default_job_qty))))
        run_uuid = drawing_json.get("run_uuid") or str(uuid.uuid4())

        result = {
            "schema": "priced_estimate.v1",
            "drawing_source": drawing_json.get("source_file", "unknown"),
            "run_at": datetime.now(timezone.utc).isoformat(),
            "run_uuid": run_uuid,
            "parts": priced_parts,
            "summary": {
                "total_material_gbp": self._round_money(material_total),
                "total_labour_gbp": self._round_money(labour_total),
                "grand_total_cost_gbp": self._round_money(grand_total_cost),
                "sell_price_per_unit_gbp": None
                if manufacturing_only
                else (self._round_money(sell_price / order_qty) if order_qty else 0.0),
                "total_sell_price_gbp": None if manufacturing_only else self._round_money(sell_price),
                "margin_pct": margin_pct,
                "rounding_mode": rounding_mode,
                "ignored_markup_cells": list(getattr(config, "WORKBOOK_IGNORED_MARKUP_CELLS", [])),
                "output_manufacturing_cost_only": manufacturing_only,
            },
            "workbook_equivalent_pricing": workbook_equivalent,
            "estimate_source_extract": workbook_estimate.get("estimate_source_extract", {}),
            "historical_comparison_projection": workbook_estimate.get("historical_comparison_projection", {}),
            "powder_coating_summary": workbook_estimate.get("powder_coating_summary", {}),
            "estimate_policy_manifest": workbook_estimate.get("estimate_policy_manifest", {}),
            "estimate_review_signals": workbook_estimate.get("estimate_review_signals", {}),
            "estimate_workbook_inputs": workbook_estimate.get("estimate_workbook_inputs", {}),
            "client_quote_pack": generate_client_quote_pack({**drawing_json, "estimate_summary": workbook_estimate}),
            "provenance": "reverse-engineered workbook first, with UDEF/historical/catalog joined as anchors",
        }
        if save_to_db:
            self._save_to_database(result, run_uuid)
        return result

    def _save_to_database(self, priced_result: Dict[str, Any], run_uuid: Optional[str] = None) -> None:
        for attempt in range(2):
            cursor = None
            try:
                cursor = self.conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO dbo.drawing_priced_estimate (run_uuid, priced_json, total_cost_gbp, sell_price_gbp)
                    VALUES (?, ?, ?, ?)
                    """,
                    run_uuid or str(uuid.uuid4()),
                    json.dumps(priced_result, ensure_ascii=False),
                    priced_result["summary"]["grand_total_cost_gbp"],
                    priced_result["summary"]["total_sell_price_gbp"]
                    if priced_result["summary"].get("total_sell_price_gbp") is not None
                    else priced_result["summary"]["grand_total_cost_gbp"],
                )
                self.conn.commit()
                return
            except Exception as exc:
                if attempt == 0 and self._is_connection_error(exc):
                    self.conn = self._connection_factory()
                    continue
                raise
            finally:
                if cursor is not None:
                    try:
                        cursor.close()
                    except Exception:
                        pass


if __name__ == "__main__":
    path = Path(r"C:\ClaudeVision\output\json\YOUR_DRAWING_v4.json")
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    with PricingService() as engine:
        result = engine.calculate_estimate(data)
    print(json.dumps(result["summary"], indent=2))
    print("\nSaved to drawing_priced_estimate table")
