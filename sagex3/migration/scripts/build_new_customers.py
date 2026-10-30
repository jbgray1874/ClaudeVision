"""New customer accounts: rows for YA004BPC and YA004BPCDL from the Access details.

Input is the output of sql/new_customer_details.sql, saved as one tab-delimited file:
  grid 1  migration.vw_BPC for the accounts (22 columns)
  grid 2  dbo.SL_ADDRESSES for the same accounts (110 columns)
plus Customers_to_add.xlsx for the new codes.

Each address becomes a customer row in the 34-column layout of the clean-run customer
file (out_v8/YA004BPC_load6_customers.txt), with the same rules as the clean run:
  * Ethan's character rule on names and addresses, cut to what the field already holds
  * address code = the Access address number (AD_CODE), three digits; the address Access
    flags as the account's main one is the default (BPAADDFLG 2, and BPAINV/BPAPYR/BPAADD/BPDADD)
  * tax rule from the Access VAT code: DOM stays DOM / DOM, anything else ROW / ROWC (X3 has
    no EU rule; UNI100 loaded this way)
  * country from the address when Access left it as GB but the address names another country
  * UK postcodes tidied, and moved out of the address lines when they were typed there
  * VAT number (EECNUM) only when it is valid as it stands, or a UK number missing its GB;
    anything else is blanked and listed for Finance
Then the delivery addresses are built from the rows, as build_v8_track2.py does.

Usage:
    python build_new_customers.py <details .txt> <Customers_to_add.xlsx> <out folder>
"""
import csv
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from openpyxl import load_workbook

BASE = "/tmp/claude-0/-home-user-ClaudeVision/e9ffe9d9-c7dd-5e34-8a16-6cb3c65dadea/scratchpad"
V8 = f"{BASE}/out_v8"
ENC = "cp850"

COUNTRY = {
    "GERMANY": "DE", "DEUTSCHLAND": "DE", "IRELAND": "IE", "EIRE": "IE", "REPUBLIC OF IRELAND": "IE",
    "AUSTRIA": "AT", "SWITZERLAND": "CH", "FRANCE": "FR", "NETHERLANDS": "NL", "THE NETHERLANDS": "NL",
    "HOLLAND": "NL", "BELGIUM": "BE", "DENMARK": "DK", "ITALY": "IT", "SWEDEN": "SE", "NORWAY": "NO",
    "POLAND": "PL", "SPAIN": "ES", "PORTUGAL": "PT", "FINLAND": "FI", "LUXEMBOURG": "LU",
    "CZECH REPUBLIC": "CZ", "CZECHIA": "CZ", "HUNGARY": "HU", "SLOVAKIA": "SK", "SLOVENIA": "SI",
    "CROATIA": "HR", "ROMANIA": "RO", "BULGARIA": "BG", "GREECE": "GR", "LITHUANIA": "LT",
    "LATVIA": "LV", "ESTONIA": "EE", "AUSTRALIA": "AU", "CHINA": "CN", "HONG KONG": "HK",
    "UNITED STATES": "US", "USA": "US", "U.S.A.": "US", "UNITED STATES OF AMERICA": "US",
    "CANADA": "CA", "UNITED ARAB EMIRATES": "AE", "UAE": "AE", "SAUDI ARABIA": "SA", "JAPAN": "JP",
    "SINGAPORE": "SG", "MEXICO": "MX", "JERSEY": "JE", "GUERNSEY": "GG", "ISLE OF MAN": "IM",
}
EU = {"AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU", "IE", "IT", "LV",
      "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES", "SE"}
VAT_PREFIX = EU | {"GB", "XI", "EL", "NO", "CH"}
VAT_FORMAT = {"DE": r"\d{9}", "FR": r"[0-9A-Z]{2}\d{9}", "IT": r"\d{11}", "NL": r"\d{9}B\d{2}",
              "PL": r"\d{10}", "AT": r"U\d{8}", "DK": r"\d{8}", "HU": r"\d{8}", "IE": r"\d[0-9A-Z]\d{5}[A-Z]{1,2}",
              "BE": r"[01]\d{9}", "ES": r"[0-9A-Z]\d{7}[0-9A-Z]", "SE": r"\d{12}", "CZ": r"\d{8,10}"}
UK_PC = re.compile(r"^([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})$")
LIG, NAME, SHORT, DESC, TOWN, PC = 47, 35, 10, 40, 25, 10   # what the clean-run file holds


def x3(v):
    """Ethan's character rule - the same function as build_v8_track2.py."""
    for x, y in (("Ø", "DIA "), ("ø", "dia "), ("°", " deg"), ("½", "1/2"),
                 ("¼", "1/4"), ("–", "-"), ("—", "-"), ("’", "'")):
        v = v.replace(x, y)
    v = re.sub("(?<=[A-Za-z])£(?=s\\b)", "", v)
    v = re.sub("£s\\b", " GBP", v).replace("£", " GBP ")
    v = v.replace(" ? ", " - ")
    v = unicodedata.normalize("NFKD", v)
    v = "".join(ch for ch in v if not unicodedata.combining(ch))
    v = v.replace("&", " AND ").replace("/", "-")
    return " ".join(re.sub(r"[^A-Za-z0-9._\- ]", "", v).split())


def short(name):
    w = [x for x in name.upper().split() if x != "THE"]
    return " ".join(w[:2]) if w and len(w[0]) <= 3 else (w[0] if w else name.upper())


def dname(r, multi):
    """Delivery address description - the same as build_v8_track2.py."""
    if multi[r[1]] == 1:
        return r[18].strip()[:30].rstrip()
    who, pc = short(r[18]), r[22].strip().upper()
    room = 30 - len(who) - len(pc) - 2
    line = " ".join(r[19].upper().split())[:max(room, 0)].rstrip()
    return " ".join(" ".join(x for x in (who, line, pc) if x).split())[:30].rstrip()


def read_v8(p):
    with open(p, newline="", encoding=ENC) as f:
        return [r for r in csv.reader(f, delimiter=";") if r and r[0].strip()]


def write(p, rows):
    with open(p, "w", newline="", encoding=ENC) as f:
        csv.writer(f, delimiter=";", lineterminator="\r\n").writerows(rows)


def split_lines(v):
    """Access keeps several lines in one field, either padded to 30 or run together."""
    v = v.rstrip()
    if not v:
        return []
    parts = [p for p in re.split(r"\s{2,}", v) if p.strip()]
    out = []
    for p in parts:
        p = " ".join(p.split()).strip(" ,")
        while len(p) > LIG:                      # word-wrap anything too long for one line
            cut = p.rfind(" ", 0, LIG + 1)
            cut = cut if cut > 0 else LIG
            out.append(p[:cut].strip(" ,"))
            p = p[cut:].strip(" ,")
        if p:
            out.append(p)
    return out


def uk_postcode(v):
    m = UK_PC.match(" ".join(v.upper().split()))
    return f"{m.group(1)} {m.group(2)}" if m else ""


def address(a, store, report, code):
    """Lines, postcode, country for one SL_ADDRESSES row."""
    lines = ([store] if store else []) + split_lines(a[3])
    for k in (52, 53, 65):
        lines += split_lines(a[k])
    cry = a[67].strip().upper() or "GB"
    named = [COUNTRY[l.upper().strip(" .,")] for l in lines if l.upper().strip(" .,") in COUNTRY]
    if named:
        lines = [l for l in lines if l.upper().strip(" .,") not in COUNTRY]
        if named[-1] != cry and cry == "GB":
            report.append([code, a[1], "country", "GB", named[-1], "the address names another country"])
            cry = named[-1]
    pc = " ".join(a[4].split()).upper()
    if cry == "GB":
        tidy = uk_postcode(pc)
        if tidy:
            pc = tidy
        elif not pc:
            for l in reversed(lines):
                tidy = uk_postcode(l)
                if tidy:
                    lines.remove(l)
                    pc = tidy
                    report.append([code, a[1], "postcode", "", pc, "moved out of the address lines"])
                    break
    lines = [x3(l)[:LIG].rstrip() for l in lines]
    lines = [l for l in lines if l]
    town = ""
    if len(lines) > 3 and len(lines[-1]) <= TOWN:
        town = lines.pop()
    while len(lines) > 3:                         # fold the rest into the nearest line with room
        extra = lines.pop(3)
        for i in (2, 1):
            if len(lines[i]) + 1 + len(extra) <= LIG:
                lines[i] = f"{lines[i]} {extra}"
                break
        else:
            report.append([code, a[1], "address line", extra, "", "did not fit in three lines - left out"])
    return lines + [""] * (3 - len(lines)), pc[:PC], cry, town


def vat(v, cry, report, code):
    v = re.sub(r"[\s.\-]", "", v.upper())
    if not v:
        return ""
    if re.fullmatch(r"GB(\d{9}|\d{12})", v):
        return v
    if cry == "GB" and re.fullmatch(r"\d{9}|\d{12}", v):
        return "GB" + v
    if v[:2] in VAT_PREFIX and v[:2] != "GB" and re.fullmatch(r"[A-Z]{2}[0-9A-Z]{5,13}", v):
        return v
    # The number without its country letters. Suggest them when the format fits the main
    # address's country, but don't load it: the account may be invoiced under another country.
    fits = VAT_FORMAT.get(cry)
    hint = f"{cry}{v}" if fits and re.fullmatch(fits, v) else ""
    report.append([code, "001", "VAT number", v, hint,
                   "no country prefix - blank until Finance confirms" + (f"; {hint} fits the {cry} format" if hint else "")])
    return ""


def main(details, to_add, out):
    text = open(details, encoding="utf-8", newline="").read().split("\r\n")
    head = [l.split("\t") for l in text if l.count("\t") == 21]
    addrs = [l.split("\t") for l in text if l.count("\t") == 109]
    ws = load_workbook(to_add, read_only=True)["Customers to add"]
    plan = {r[0]: r for r in ws.iter_rows(min_row=2, values_only=True) if r[0]}
    by_cus = defaultdict(list)
    for a in addrs:
        by_cus[a[0].strip()].append(a)

    rows, report, held = [], [], []
    for h in head:
        old = h[1].strip()
        p = plan[old]
        if p[5] != "Add":
            held.append([old, h[2], p[5]])
            continue
        new = p[6]
        name = x3(h[2])[:NAME].rstrip()
        tax = "DOM" if h[7] == "DOM" else "ROWC"
        cat = "DOM" if tax == "DOM" else "ROW"
        mine = sorted(by_cus[old], key=lambda a: int(a[1]))
        main_a = next((a for a in mine if a[13] == "1"), mine[0])
        default = f"{int(main_a[1]):03d}"
        _, _, cry_main, _ = address(main_a, "", [], old)
        crn = re.sub(r"\s", "", h[5]).upper()
        if crn.startswith("GB") and not re.fullmatch(r"GB(\d{9}|\d{12})", crn):
            crn = ""
        eec = vat(h[6], cry_main, report, new)
        emails = [e for e in re.split(r"[\s;,]+", h[19]) if "@" in e]
        if (cry_main == "GB") != (cat == "DOM"):
            report.append([new, default, "tax rule", h[7], f"{cat} / {tax}",
                           f"Access VAT code kept; the main address is in {cry_main} - Finance to confirm"])
        for a in mine:
            store = "" if a is main_a else (a[21].strip() or re.sub(r"^\d+\s+", "", a[11].strip()))
            if x3(store).upper() == name.upper():
                store = ""
            lines, pc, cry, town = address(a, store, report, new)
            is_main = a is main_a
            if not is_main and not any(lines) and not pc and not town:
                report.append([new, f"{int(a[1]):03d}", "address", "", "", "blank in Access - left out"])
                continue
            rows.append([
                cat, new, name, "", x3(h[2])[:SHORT].rstrip(), default, default, default, default, h[4],
                crn, "", eec, new, tax, h[8], "STD", f"{int(a[1]):03d}", x3(h[2])[:DESC].rstrip(),
                *lines, pc, "", cry,
                h[17].strip() if is_main else "", h[18].strip() if is_main else "",
                emails[1] if is_main and len(emails) > 1 else "", emails[0] if is_main and emails else "",
                "", "", "", "2" if is_main else "1", x3(town)[:TOWN].rstrip(),
            ])

    # the rule's own checks, as in build_v8_track2.py
    bad = re.compile(r"[^A-Za-z0-9._\- ]")
    assert all(len(r) == 34 for r in rows)
    assert len({(r[1], r[17]) for r in rows}) == len(rows)
    assert not any(bad.search(r[c]) for r in rows for c in (2, 4, 18, 19, 20, 21, 23, 33))
    existing = read_v8(f"{V8}/YA004BPC_load6_customers.txt")
    assert not ({r[1] for r in rows} & {r[1] for r in existing}), "a new code is already in the customer file"

    # delivery addresses, the clean-run way
    multi = Counter(r[1] for r in rows)
    bpcdl = [[r[1], r[17], x3(dname(r, multi))] for r in rows]
    # Store chains repeat (BAUHAUS, TESCO) and overseas postcodes sit in the address lines,
    # so some descriptions come out the same. The address code at the end tells them apart.
    seen = Counter((d[0], d[2]) for d in bpcdl)
    for d in bpcdl:
        if seen[(d[0], d[2])] > 1:
            d[2] = f"{d[2][:29 - len(d[1])].rstrip()} {d[1]}"
    assert len({(d[0], d[2]) for d in bpcdl}) == len(bpcdl)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    write(out / "YA004BPC_new_customers.txt", rows)
    write(out / "YA004BPCDL_new_delivery_addresses.txt", bpcdl)
    write(out / "YA004BPC_load7_customers.txt", existing + rows)
    write(out / "YA004BPCDL_load3_delivery_addresses.txt",
          read_v8(f"{V8}/YA004BPCDL_load2_delivery_addresses.txt") + bpcdl)
    print(len({r[1] for r in rows}), "customers,", len(rows), "address rows;", len(held), "held;",
          Counter(x[2] for x in report))
    return existing, rows, bpcdl, report, held


def sheets(existing, rows, bpcdl, report, held):
    """The mapped spreadsheets: the full clean-run files, and the new accounts alone for UAT now."""
    import build_bp_sheets as bp
    from openpyxl.styles import Font

    n_cus = len({r[1] for r in rows})
    check_head = ["New code", "Address", "What", "Access had", "Now / suggested", "Note"]
    by_kind = Counter(x[2] for x in report)
    country = Counter(x[0] for x in report if x[2] == "country")
    check = [x for x in report if x[2] != "country"] + [
        [c, "", "country", "GB", f"{n} addresses", "Access had GB on addresses that name another country - "
                                                   "the named country is used"] for c, n in country.most_common()]
    notes = [
        ["New accounts", f"{n_cus} customers that were missing from X3, {len(rows)} address rows, from the Access "
                         "details of 27 Oct. Codes as in Customers_to_add.xlsx (TIE02E = TEC103, TIE02POL = TEC104)"],
        ["Address codes", "The Access address number, three digits. The address Access flags as the main one is the "
                          "default (column AG = 2, and columns F to I)"],
        ["Tax rule", f"From the Access VAT code: DOM stays DOM / DOM, EU becomes ROW / ROWC. "
                     f"{by_kind['tax rule']} accounts where the main address's country says otherwise are on the "
                     "Check tab for Finance"],
        ["VAT number", f"{by_kind['VAT number']} numbers held without their country letters are blank, with the "
                       "prefixed number suggested on the Check tab where it fits the country's format"],
        ["Country", f"{sum(country.values())} addresses that Access had as GB but which name another country "
                    "(GERMANY, SWITZERLAND ...) now carry that country"],
        ["Postcodes", f"UK postcodes tidied; {by_kind['postcode']} moved out of the address lines"],
        ["Left out", f"{by_kind['address']} blank addresses; {by_kind['address line']} address lines that did not "
                     "fit in three lines (on the Check tab). " + "; ".join(f"{h[0]} {h[1]}: {h[2]}" for h in held)],
        ["Names and addresses", "Ethan's character rule, as the rest of the file. Emails and phones untouched"],
    ]
    out = f"{BASE}/out_sheets"
    # Complete files only - no new-accounts-only file (runbook, rule 1b)
    bp.build("YA004BPC", "Customers", bp.CUSTOMER, existing + rows, bp.read(f"{BASE}/upl2/bpc.txt"), [
        ["Tax rule", "10 EU customers (56 address rows) set to ROW / ROWC, as UNI100 which loaded. Finance to confirm"],
        ["VAT number", "ROL100's GB76361992 is 8 digits - blanked. Finance to supply the real one"],
        ["TEC100", "Postcodes moved out of the address lines (28823, 4785-598) for the POSCOD error"],
        ["Two rows", "A second email after a ';' had pushed every later field along by one - first email kept"],
        ["Names and addresses", "Ethan's character rule. Emails and phones untouched"], []] + notes,
             path=f"{out}/YA004BPC_customers_MAPPED.xlsx", extra=[("Check new accounts", check_head, check)])

    from openpyxl import load_workbook
    for data, name, what in ((read_v8(f"{V8}/YA004BPCDL_load2_delivery_addresses.txt") + bpcdl,
                              "YA004BPCDL_delivery_addresses_MAPPED.xlsx", "clean run, all customers")):
        wb = load_workbook(f"{BASE}/tmpl_t2/YA004BPCDL.xlsx")
        ws = wb["Data with headings"]
        if ws.max_row >= 3:
            ws.delete_rows(3, ws.max_row)
        for r in data:
            ws.append([v if v != "" else None for v in r])
        ws.freeze_panes = "A3"
        nt = wb.create_sheet("Notes")
        for line in [[f"YA004BPCDL - customer delivery addresses, {what}"], [], ["Rows", len(data)],
                     ["Load after", "the customer file - every customer and address code matches it"],
                     ["Company Name", "Built from the store line and postcode, 30 characters, Ethan's character rule. "
                                      "Where two addresses would read the same, the address code is added at the end"]]:
            nt.append(line)
        nt["A1"].font = Font(bold=True, size=13)
        nt.column_dimensions["A"].width = 20
        nt.column_dimensions["B"].width = 100
        wb.save(f"{out}/{name}")
        got = [["" if v is None else str(v) for v in r][:3]
               for r in load_workbook(f"{out}/{name}", read_only=True)["Data with headings"].iter_rows(min_row=3, values_only=True)
               if any(v is not None for v in r)]
        assert got == data, name
        print(name, len(data), "rows checked")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sheets(*main(*sys.argv[1:4]))
