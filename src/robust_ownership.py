"""What a thing is, owned by the evidence that says so (Programme Robust, D-598).

A service is charged but never fitted or shipped; a section is weighed as a section; an oval's
shape is refined only by a brief clause that sizes it; the e-mail repeats the release record
and the read ledger and decides neither. No job numbers, guessed dimensions or price
overrides."""
import re
from math import isfinite
from collections.abc import Mapping


def nonphysical(part):
    """Explicit services are charges, not extra objects to fit or ship."""
    from commercial_lines import is_commercial_line
    # The marks the engine's own stubs carry: the plating line (estimator `_plating_placeholder`),
    # the plater's freight (`_plater_freight`, also a commercial placeholder), a service line.
    return bool(is_commercial_line(part) or part.get('_plating_placeholder')
                or part.get('_plater_freight') or part.get('_plater_freight_placeholder')
                or part.get('line_kind') == 'service')


def brief_oval_shape(brief, section, wall):
    """Only a matching dimensioned clause may refine an oval's shape.

    Conflicting statements stay unresolved. An unqualified oval is not proof of FSO.
    Decimal points are not sentence boundaries; no job-specific sizes are present.
    """
    candidates = set()
    number = r'(\d+(?:[.,]\d+)?)'
    pattern = number + r'\s*[x×]\s*' + number + r'(?:\s*[x×]\s*' + number + r')?'
    for clause in re.split(r'[;\n]|(?<=[.!?])\s+(?=[A-Z])', brief or ''):
        for match in re.finditer(pattern, clause, re.I):
            a, b = [float(v.replace(',', '.')) for v in match.groups()[:2]]
            if sorted((a, b)) != sorted(section[:2]):
                continue
            t = match.group(3)
            if t and wall and abs(float(t.replace(',', '.')) - float(wall)) > 1e-6:
                continue
            if re.search(r'\b(?:FSO|flat[ -]sided)\b', clause, re.I):
                candidates.add('flat_sided')
            elif re.search(r'\b(?:oval|elliptical|ellipse)\b', clause, re.I):
                candidates.add('unspecified_or_ellipse')
    return 'flat_sided' if candidates == {'flat_sided'} else None


def section_shipping(part, density):
    """Return declared-section mass, or an explicit gap; never a flat-strip fallback."""
    from section_profile import section_kg_per_m, section_form
    stock = part.get('section_stock')
    if not isinstance(stock, Mapping) or not stock:
        if str(part.get('stock_form') or '').lower() in ('tube', 'section', 'bar'):
            return {'error': 'section dimensions missing', 'basis': 'section weight unverified'}
        return None
    try:
        a, b, t = (float(stock[k]) for k in ('a', 'b', 't'))
        length = float(stock.get('length_mm') or part.get('section_length_mm') or 0)
        form = section_form(stock)
        if not form or not all(isfinite(v) for v in (a,b,t,length)) or min(a, b, t, length) <= 0:
            raise ValueError('missing section dimensions or shape')
        rate = section_kg_per_m(a, b, t, form, density_kg_m3=density)
        if rate is None or rate <= 0:
            raise ValueError('section cannot be weighed')
        return dict(length=length, width=max(a, b), thickness=t,
                    kg=rate * length / 1000, basis=f'{form}: section kg/m × cut length')
    except (TypeError, ValueError, KeyError) as exc:
        return {'error': str(exc), 'basis': 'section weight unverified'}


def _release(record):
    release = record.get('release') if isinstance(record, Mapping) else None
    return release if isinstance(release, Mapping) else None


def _held_words(release):
    """The held allowances as the release record states them, or ''."""
    try:
        held = float(release.get('held_allowances_gbp_per_unit') or 0)
    except (TypeError, ValueError):
        held = 0.0
    if held <= 0:
        return ''
    breaks = [b for b in (release.get('held_at_breaks') or []) if isinstance(b, Mapping)]
    rest = '; '.join(f"£{float(b.get('unit_excluding_held_gbp') or 0):.2f} at "
                     f"{int(b.get('quantity') or 0):,} off" for b in breaks)
    if not rest and release.get('unit_excluding_held_gbp') is not None:
        rest = f"£{float(release['unit_excluding_held_gbp']):.2f} a unit"
    return (f"£{held:.2f} a unit rests on engine allowances not confirmed for this job; the "
            f"priced subtotal excluding them is {rest or 'not stated'}")


def release_email_lines(record, summary):
    """Expose the existing final authority and ledger, never decide release again."""
    release = _release(record)
    lines = []
    if release is None:
        lines.append('Final release status is unavailable; this email is not release evidence.')
    else:
        lines.append('Final release record: ' + str(release.get('status') or 'status unknown')
                     + ('' if release.get('draft') is False else ', draft')
                     + '; to confirm: '
                     + str(release.get('to_confirm', release.get('outstanding', 'unknown'))) + '.')
        if _held_words(release):
            lines.append('Held allowances: ' + _held_words(release) + '.')
    result = summary.get('read_charge_result') if isinstance(summary, Mapping) else None
    if isinstance(result, Mapping) and result.get('applicable'):
        lines.append('Read-to-charge audit: ' + ('passed' if result.get('passed') else 'findings remain') + '.')
        for issue in result.get('issues') or []:
            lines.append('Read-to-charge: ' + str(issue.get('item') or issue.get('part') or '')
                         + ' — ' + str(issue.get('why') or issue.get('text') or issue.get('code')))
    return lines


def release_focus_lines(record, summary, section='§9'):
    """The panel's lines for the release record, the held allowances and the read ledger, each
    pointing at the section that holds the detail — plain text, for the caller to escape
    (D-598). Read from the persisted records; nothing here decides release."""
    release = _release(record)
    out = []
    if release is None:
        out.append(f'Final release status is unavailable — this e-mail is not release '
                   f'evidence. {section}.')
    else:
        out.append(f"Final release record: {release.get('status') or 'status unknown'}"
                   + ('' if release.get('draft') is False else ', a draft') + ' — '
                   + f"{release.get('to_confirm', release.get('outstanding', 'unknown'))} to "
                   + f'confirm. The e-mail repeats this record; {section} gives its reasons.')
        if _held_words(release):
            out.append(_held_words(release)[:1].upper() + _held_words(release)[1:]
                       + f'. Not a budget until they are confirmed or taken off. {section}.')
    result = summary.get('read_charge_result') if isinstance(summary, Mapping) else None
    if isinstance(result, Mapping) and result.get('applicable') and not result.get('passed'):
        unresolved = [str(i.get('item')) for i in result.get('issues') or []
                      if isinstance(i, Mapping) and i.get('code') == 'read_item_unresolved']
        others = [i for i in result.get('issues') or []
                  if isinstance(i, Mapping) and i.get('code') != 'read_item_unresolved']
        out.append('The read ledger holds the release: '
                   + (f"{len(unresolved)} item(s) the read returned reach no charge and no "
                      f"ruling ({', '.join(unresolved[:6])}{', …' if len(unresolved) > 6 else ''})"
                      if unresolved else '')
                   + ('; ' if unresolved and others else '')
                   + (f'{len(others)} other finding(s)' if others else '')
                   + f'. {section}.')
    return out
