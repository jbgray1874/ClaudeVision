"""Explicit joint-side/run inventory, independent of part names and file format (D-598h).

This is requirement capture, NOT charged-work proof. No number of members, weld
rows or hours can invent sides or passes. Existing evidenced release rulings and
calculated-cell checks retain authority. The inventory is shown on unresolved
ledger joints until a charge adapter can reconcile individual runs to hours.
"""
from math import isfinite

# WHAT EACH FINDING MEANS, in the words the release reasons and the email carry (D-598h).
_SAID = {
    "joint_runs_not_captured": "the runs per joint are not captured",
    "joint_scope_or_source_unverified": ("a captured side or run lacks its count, basis, "
                                         "process, source or author"),
    "duplicate_or_conflicting_joint_side": "a joint side is captured twice",
    "malformed_joint_inventory": "the joint inventory cannot be read",
    "malformed_joint_requirement": "an entry in the joint inventory cannot be read",
}


def said(issues):
    """The findings in words, once each, in the order raised."""
    out = []
    for code in issues:
        text = _SAID.get(code, str(code).replace("_", " "))
        if text not in out:
            out.append(text)
    return "; ".join(out) or "the joint's sides and runs are unresolved"


def _count(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and isfinite(value) and value > 0 and float(value).is_integer())


def joint_scope(summary, part):
    """Accept reader or estimator evidence; contradictory identities stay unresolved.

Each entry names one joint side, with runs PER JOINT and joints PER PRODUCT.
Source uses document+locator (page/region, CAD feature, or inspection reference),
so this is not PDF-specific. An explicit empty inventory does not mean no welds.
"""
    sources = [('reader', summary.get('weld_joint_requirements') or []),
               ('estimator', (summary.get('estimator_decisions') or {}).get('weld_joint_requirements') or [])]
    rows, issues, seen = [], [], set()
    for origin, entries in sources:
        if not isinstance(entries, list):
            issues.append('malformed_joint_inventory')
            continue
        for item in entries:
            if not isinstance(item, dict):
                issues.append('malformed_joint_requirement')
                continue
            if str(item.get('part') or '').strip().upper() != part.strip().upper():
                continue
            ident = (str(item.get('joint_id')), str(item.get('side')))
            if ident in seen:
                issues.append('duplicate_or_conflicting_joint_side')
            seen.add(ident)
            source = item.get('source') or {}
            valid = (all(isinstance(item.get(k), str) and item[k].strip()
                         for k in ('joint_id', 'side', 'process'))
                     and _count(item.get('runs_per_joint'))
                     and _count(item.get('joints_per_product'))
                     and item.get('basis') == 'per_finished_product'
                     and isinstance(source, dict) and source.get('document') and source.get('locator')
                     and (origin != 'estimator' or item.get('confirmed_by')))
            if not valid:
                issues.append('joint_scope_or_source_unverified')
            rows.append({'origin': origin, 'requirement': item,
                         'runs_per_product': (item['runs_per_joint'] * item['joints_per_product']
                                              if valid else None)})
    if not rows:
        issues.append('joint_runs_not_captured')
    return {'part': part, 'requirements': rows, 'issues': issues,
            'scope_verified': bool(rows) and not issues, 'charge_verified': False}
