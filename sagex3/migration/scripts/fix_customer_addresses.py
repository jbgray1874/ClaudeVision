"""YA004BPC: the customer address fixes from Run 2 (Ethan's notes, XPOSCOD and XSAT), applied by rule.

X3 rejected TEC100, TEC105, UNI103 (postcode format) and DRE100, MAR101, PER101 (State/Region),
and with them 1,425 delivery addresses. Each rule below is applied to every customer address,
not only those six, and every change is listed on the 'Address fixes' tab:
  1. a postcode left in the address lines (postcode blank) moves to the postcode field
  2. a GB postcode with the letter O and the digit 0 confused ("SE1 OHX", "S021 3SP") is put
     right, only where exactly one correction gives a valid GB postcode
  3. a postcode holding country text ("77990,FRAN") keeps just the postcode
  4. a Dublin Eircode marked GB becomes IE; a GB address that names another country in its
     text, with no valid GB postcode, takes that country (the 27 Oct rule for the new accounts)
  5. brackets come out of phone numbers ("0046 (0) 470705100" -> "0046 0 470705100", as James
     did by hand for Run 2)
  6. State/Region (the County / region column), with the standard (ISO 3166-2) codes: CA
     from the postcode's first letter, AU and US from the postcode range, a US / AU state code
     that was typed into the postcode, AE from the emirate named in the address. X3's own
     codes to confirm with Ethan
  7. AE has no postcodes: a number in its postcode is a PO box, moved into the address
  Also: a country name typed in the postcode field sets the country; "DUBLIN 15" is IE, routing
  key D15; a Polish postcode is written NN-NNN; I / 1 confused like O / 0
Anything a rule can't settle goes on 'Address check'. A complete file (rule 1b), with its
load file (rule 1c).

Usage:
    python fix_customer_addresses.py        (IN_FILE / OUT_DIR to override)
"""
import os
import re
import shutil
import sys
from collections import Counter

from openpyxl import load_workbook

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "rebuild"))
sys.path.insert(0, HERE)
from common import add_sheet, write_load  # noqa: E402
from run3_fix_lists import NO_POSTCODE, POSTCODE  # noqa: E402  one copy of the formats

BASE = "/tmp/claude-0/-home-user-ClaudeVision/e9ffe9d9-c7dd-5e34-8a16-6cb3c65dadea/scratchpad"
IN_FILE = os.environ.get("IN_FILE", f"{BASE}/Current_mapped_set_2026-11-04/YA004BPC_customers_MAPPED.xlsx")
OUT = os.environ.get("OUT_DIR", f"{BASE}/out_run3")
LINES, POSCOD, STATE, CRY, PHONES = (19, 20, 21), 22, 23, 24, (25, 26)   # 0-based columns
FAILED = {"TEC100", "TEC105", "UNI103", "DRE100", "MAR101", "PER101"}

COUNTRY_WORDS = {"CYPRUS": "CY", "IRELAND": "IE", "DUBLIN": "IE", "FRANCE": "FR", "PARIS": "FR", "SPAIN": "ES",
                 "NETHERLANDS": "NL", "HOLLAND": "NL", "BELGIUM": "BE", "GERMANY": "DE", "DEUTSCHLAND": "DE",
                 "CHINA": "CN", "SHANGHAI": "CN", "BEIJING": "CN", "HONG KONG": "HK", "SINGAPORE": "SG",
                 "DUBAI": "AE", "U.A.E": "AE", "UAE": "AE", "PORTUGAL": "PT", "ITALY": "IT", "DENMARK": "DK",
                 "SWEDEN": "SE", "NORWAY": "NO", "FINLAND": "FI", "POLAND": "PL", "AUSTRIA": "AT",
                 "CZECH": "CZ", "CANADA": "CA", "AUSTRALIA": "AU", "U.S.A": "US", "USA": "US", "INDIA": "IN",
                 "JAPAN": "JP", "GREECE": "GR", "TURKEY": "TR", "SWITZERLAND": "CH", "QATAR": "QA",
                 "SAUDI": "SA", "KUWAIT": "KW", "BAHRAIN": "BH", "MALTA": "MT", "GIBRALTAR": "GI",
                 "JINGAN": "CN", "NANJING": "CN", "GUANGZHOU": "CN", "SHENZHEN": "CN", "ROMANIA": "RO",
                 "MALAYSIA": "MY", "MEXICO": "MX", "BRAZIL": "BR", "ARGENTINA": "AR", "MONACO": "MC",
                 "BERMUDA": "BM", "SOUTH AFRICA": "ZA", "NEW ZEALAND": "NZ", "ISRAEL": "IL", "EGYPT": "EG"}
CA_PROVINCE = {"A": "NL", "B": "NS", "C": "PE", "E": "NB", "G": "QC", "H": "QC", "J": "QC", "K": "ON", "L": "ON",
               "M": "ON", "N": "ON", "P": "ON", "R": "MB", "S": "SK", "T": "AB", "V": "BC", "X": "NT", "Y": "YT"}
EIRCODE = r"[AC-FHKNPRTV-Y]\d[\dW] ?[0-9AC-FHKNPRTV-Y]{4}"


STATES = {"US": {"AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL", "GA", "HI", "ID", "IL", "IN", "IA", "KS",
                  "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ", "NM", "NY", "NC",
                  "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"},
          "AU": {"NSW", "VIC", "QLD", "SA", "WA", "TAS", "NT", "ACT"},
          "CA": set(CA_PROVINCE.values()) | {"NU"}}
US_ZIP = [(10, 27, "MA"), (28, 29, "RI"), (30, 38, "NH"), (39, 49, "ME"), (50, 54, "VT"), (55, 55, "MA"), (56, 59, "VT"),
          (60, 69, "CT"), (70, 89, "NJ"), (100, 149, "NY"), (150, 196, "PA"), (197, 199, "DE"), (200, 205, "DC"),
          (206, 219, "MD"), (220, 246, "VA"), (247, 268, "WV"), (270, 289, "NC"), (290, 299, "SC"), (300, 319, "GA"),
          (320, 349, "FL"), (350, 369, "AL"), (370, 385, "TN"), (386, 397, "MS"), (398, 399, "GA"), (400, 427, "KY"),
          (430, 459, "OH"), (460, 479, "IN"), (480, 499, "MI"), (500, 528, "IA"), (530, 549, "WI"), (550, 567, "MN"),
          (570, 577, "SD"), (580, 588, "ND"), (590, 599, "MT"), (600, 629, "IL"), (630, 658, "MO"), (660, 679, "KS"),
          (680, 693, "NE"), (700, 714, "LA"), (716, 729, "AR"), (730, 749, "OK"), (750, 799, "TX"), (800, 816, "CO"),
          (820, 831, "WY"), (832, 838, "ID"), (840, 847, "UT"), (850, 865, "AZ"), (870, 884, "NM"), (889, 898, "NV"),
          (900, 961, "CA"), (967, 968, "HI"), (970, 979, "OR"), (980, 994, "WA"), (995, 999, "AK")]
EMIRATES = [("ABU DHABI", "AZ"), ("SHARJAH", "SH"), ("AJMAN", "AJ"), ("RAS AL KHAIMAH", "RK"), ("FUJAIRAH", "FU"),
            ("UMM AL", "UQ"), ("RAS AL KHOR", "DU"), ("RAS AI KHOR", "DU"), ("JEBEL ALI", "DU"), ("DUBAI", "DU")]


def us_state(pc):
    n = int(pc[:3])
    return next((s for a, b, s in US_ZIP if a <= n <= b), "")


def ae_emirate(text):
    return next((s for k, s in EMIRATES if k in text), "")


def au_state(pc):
    n = int(pc)
    return ("ACT" if 2600 <= n <= 2618 or 2900 <= n <= 2920 else "NSW" if 2000 <= n <= 2999 else
            "VIC" if 3000 <= n <= 3999 else "QLD" if 4000 <= n <= 4999 else "SA" if 5000 <= n <= 5999 else
            "WA" if 6000 <= n <= 6999 else "TAS" if 7000 <= n <= 7999 else "NT" if 800 <= n <= 999 else "")


def valid(cry, pc):
    if cry == "IE" and re.fullmatch(r"D\d{2}W?|[AC-FHKNPRTV-Y]\d[\dW]", pc):
        return True                          # an Eircode routing key on its own (Dublin districts)
    return cry in POSTCODE and bool(re.fullmatch(POSTCODE[cry], pc))


def fix_gb(pc):
    """The one O / 0 swap that makes a valid GB postcode, or None."""
    s = pc.replace(" ", "")
    if len(s) < 5 or len(re.findall(r"[A-HJ-NP-Z]", s)) < 2:
        return None                          # a foreign number ("10310") isn't a mistyped GB postcode
    hits = {}
    swap = {"O": "0", "0": "O", "I": "1", "1": "I"}
    spots = [i for i, ch in enumerate(s) if ch in swap]
    for mask in range(1, 2 ** len(spots)):
        t = list(s)
        for k, i in enumerate(spots):
            if mask >> k & 1:
                t[i] = swap[t[i]]
        t = "".join(t)
        cand = f"{t[:-3]} {t[-3:]}"
        if valid("GB", cand):
            hits.setdefault(bin(mask).count("1"), set()).add(cand)
    if not hits:
        return None
    fewest = hits[min(hits)]                 # the fewest characters changed, and only one way
    return fewest.pop() if len(fewest) == 1 else None


def postcode_in_text(cry, lines):
    """(line index, postcode, line without it) for a postcode at the end of an address line."""
    if cry not in POSTCODE:
        return None
    for i in reversed(range(len(lines))):
        text = (lines[i] or "").strip()
        for m in re.finditer(r"(?=(\b(?:" + POSTCODE[cry] + r")))\b", text.upper()):
            pc = m.group(1)
            rest = (text[:m.start(1)] + text[m.start(1) + len(pc):]).strip(" ,-")
            if text.upper().rstrip(" ,.").endswith(pc):
                return i, pc, rest
    return None


def main():
    os.makedirs(OUT, exist_ok=True)
    path = f"{OUT}/YA004BPC_customers_MAPPED.xlsx"
    shutil.copy(IN_FILE, path)
    wb = load_workbook(path)
    ws = wb["Data with Headings"]
    fixes, check, rule = [], [], Counter()

    def change(r, col, new, why):
        old = ws.cell(r, col + 1).value
        if (old or "") != (new or ""):
            ws.cell(r, col + 1, new or None)
            fixes.append([ws.cell(r, 2).value, ws.cell(r, 18).value, ws.cell(1, col + 1).value or
                          ws.cell(2, col + 1).value, old, new, why])
            rule[why.split(":")[0]] += 1

    for r in range(3, ws.max_row + 1):
        cust = ws.cell(r, 2).value
        if not cust:
            continue
        get = lambda c: str(ws.cell(r, c + 1).value or "").strip()
        cry, pc = get(CRY), get(POSCOD).upper()
        text = " ".join(get(c) for c in LINES).upper()

        # 4. country first, so the postcode rules use the right format
        if pc in COUNTRY_WORDS and not valid(cry, pc):           # "IRELAND" typed as the postcode
            change(r, CRY, COUNTRY_WORDS[pc], "4 country: the country name was in the postcode field")
            change(r, POSCOD, "", "4 country: the country name was in the postcode field")
            cry, pc = COUNTRY_WORDS[pc], ""
        m = re.fullmatch(r"DUBLIN\s*(\d{1,2}W?)", pc)
        if m:                                                    # "DUBLIN 15" = routing key D15
            change(r, CRY, "IE", "4 country: Dublin district marked GB")
            change(r, POSCOD, f"D{int(m.group(1).rstrip('W')):02d}" + ("W" if m.group(1).endswith("W") else ""),
                   "4 country: Dublin district as its Eircode routing key")
            cry, pc = "IE", get(POSCOD)
        if cry == "GB" and not valid("GB", pc):
            if re.fullmatch(EIRCODE, pc) or (not pc and re.search(EIRCODE, text)):
                change(r, CRY, "IE", "4 country: Dublin Eircode marked GB")
                cry = "IE"
            else:
                named = {v for k, v in COUNTRY_WORDS.items() if re.search(rf"\b{re.escape(k)}\b", text)}
                if len(named) == 1:
                    change(r, CRY, named.pop(), "4 country: the address names another country")
                    cry = get(CRY)
        # GB postcode with a stray inner space ("DN2 4 PE")
        if cry == "GB" and pc and not valid("GB", pc):
            t = pc.replace(" ", "")
            # only a misplaced space inside the inward code ("DN2 4 PE", "TW 2 5LH"): the district
            # as typed must stay the same ("G13 SQ" is not "G1 3SQ" - a digit is missing)
            if valid("GB", f"{t[:-3]} {t[-3:]}") and t[:-3].startswith(pc.split()[0]):
                change(r, POSCOD, f"{t[:-3]} {t[-3:]}", "2 postcode: spacing")
                pc = f"{t[:-3]} {t[-3:]}"
        # 2. GB O / 0
        if cry == "GB" and pc and not valid("GB", pc):
            g = fix_gb(pc)
            if g:
                change(r, POSCOD, g, "2 postcode: letter O / zero or I / one confused")
                pc = g
        if cry == "PL" and re.fullmatch(r"\d{2} ?\d{3}|\d{3} ?\d{2}", pc):
            d = pc.replace(" ", "")
            change(r, POSCOD, f"{d[:2]}-{d[2:]}", "2 postcode: PL written as NN-NNN")
            pc = get(POSCOD)
        # 3. country or state text inside the postcode; a state code moves to State/Region
        if pc and cry in POSTCODE and not valid(cry, pc):
            m = re.search(POSTCODE[cry], pc)
            if m and len(m.group(0)) >= 4:
                rest = (pc[:m.start()] + pc[m.end():]).strip(" ,.-").upper()
                change(r, POSCOD, m.group(0), "3 postcode: text removed")
                pc = m.group(0)
                if rest in STATES.get(cry, ()) and not get(STATE):
                    change(r, STATE, rest, f"6 State/Region: {cry} code that was in the postcode")
        if cry in NO_POSTCODE and pc:
            # no postcodes in this country: the number is a PO box - keep it in the address
            empty = next((c for c in LINES if not get(c)), None)
            if empty is not None:
                change(r, empty, f"PO BOX {pc}", f"7 postcode: {cry} has no postcodes, PO box moved to the address")
            else:
                change(r, LINES[-1], f"{get(LINES[-1])} PO BOX {pc}"[:50],
                       f"7 postcode: {cry} has no postcodes, PO box moved to the address")
            change(r, POSCOD, "", f"7 postcode: {cry} has no postcodes, PO box moved to the address")
            pc = ""
        # 1. postcode left in the address lines
        if not pc:
            found = postcode_in_text(cry, [get(c) for c in LINES])
            if found:
                i, p, rest = found
                change(r, LINES[i], rest, "1 postcode: moved out of the address line")
                change(r, POSCOD, p, "1 postcode: moved out of the address line")
                pc = p
        # 5. phone brackets
        for c in PHONES:
            ph = get(c)
            if "(" in ph or ")" in ph:
                change(r, c, " ".join(ph.replace("(", " ").replace(")", " ").split()), "5 phone: brackets removed")
        # 6. State / Region
        if not get(STATE):
            st = (CA_PROVINCE.get(pc[:1]) if cry == "CA" and pc else
                  au_state(pc) if cry == "AU" and re.fullmatch(r"\d{4}", pc) else
                  us_state(pc) if cry == "US" and re.match(r"\d{5}", pc) else
                  ae_emirate(text) if cry == "AE" else None)
            if not st and cry in STATES:
                named = {w for w in re.findall(r"[A-Z]{2,3}", text) if w in STATES[cry]}
                st = named.pop() if len(named) == 1 else None
            if st:
                change(r, STATE, st, f"6 State/Region: {cry} from the postcode")
            elif cry in ("CA", "AU", "AE", "US"):
                check.append([cust, get(17), cry, pc, "", f"{cry} needs a State/Region - X3 code to confirm (Ethan)"])
        # what's still not right, for the six X3 rejected
        if cust in FAILED and cry in POSTCODE and pc and not valid(cry, pc):
            check.append([cust, get(17), cry, pc, get(STATE), f"postcode '{pc}' still isn't a {cry} format - check"])
        if cust in FAILED and cry == "GB" and pc and not valid("GB", pc):
            pass

    add_sheet(wb, "Address fixes", ["Customer", "Address", "Field", "Was", "Now", "Rule"], fixes,
              [10, 8, 14, 30, 30, 50])
    add_sheet(wb, "Address check", ["Customer", "Address", "Country", "Postcode", "State/Region", "To check"], check,
              [10, 8, 8, 12, 12, 80])
    n = wb["Notes"]
    n.append([])
    n.append(["Address fixes (4 Nov)", f"{len(fixes):,} values corrected by rule for Run 2's XPOSCOD / XSAT rejections: "
                                       + ", ".join(f"{k} {v:,}" for k, v in sorted(rule.items()))
                                       + f". {len(check):,} left on 'Address check'. Nothing else changed"])
    wb.save(path)
    txt, lines, _ = write_load(path, "Data with Headings", 3)
    per = Counter(f[0] for f in fixes if f[0] in FAILED)
    print(path, f"\n  {len(fixes):,} fixes:", dict(sorted(rule.items())), f"\n  on the six X3 rejected: {dict(per)}",
          f"\n  left to check: {len(check):,}", Counter(c[0] for c in check), f"\n  {lines:,} rows | {txt}")


if __name__ == "__main__":
    main()
