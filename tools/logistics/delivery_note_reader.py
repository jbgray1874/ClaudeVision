"""What one scanned page is: a delivery note, or something that got into the tray.

James Gray, 21 September 2026: "We get a number of these each day and we want to have a
process that runs once a day and splits each delivery note out to a new folder
K:\\Logistics\\Scans\\SplitScan with a delivery note number as the file name and client name
if we can find it."

THE SCANS HAVE NO TEXT LAYER AT ALL. Every page of the four files sent is a photograph of a
sheet of paper, so all of this rests on OCR and on being sceptical about what it returns.

── TWO APPROACHES WERE TRIED AND MEASURED BEFORE THIS ONE ──────────────────────────────────

    whole-page text      4 delivery note numbers out of 11, and client names like
                         "Daley Noah Mepene" and "Eps Hoes Esra"
    word boxes,          3 out of 11. Better where it worked and no more reliable: the label
    value-to-the-right   "Delivery Note N" OCRs as "Delivery Nots", "Delivery Note |" and
                         "Delivery Note l", so the anchor the whole method hangs on is the
                         least reliable text on the page
    THIS: fixed regions  11 out of 11 numbers, 11 out of 11 clients, 9 out of 11 page markers

Both earlier attempts failed for the same reason. The header is THREE columns —

    Invoice Address        Delivery Address        Delivery Note N    30022230
    TESCO STORES LIMITED   TESCO WALLYFORD EXPR    Delivery Date      14/09/2026

— and reading it as prose loses which label a value belongs to, while reading it by label
depends on OCR getting the label right, which is exactly what it does worst. The LAYOUT is
stable: this is SDI's own template, the same every time. So each field is read from the part
of the page it lives on, and the number is read with a digits-only charset, which is why it
goes from 4 to 11.

── WHAT THE REAL SCANS TAUGHT, AND WHY NONE OF IT WAS GUESSABLE ────────────────────────────

    "Page 1 of 1"  OCRs as  "Page Lot 1", "Pageloftl", "Page lofi", "rage ord"
        The footer is the boundary marker, and a strict `Page (\\d+) of (\\d+)` matched NONE
        of the twelve pages.

    "TES01" OCRs as "Tes01", "MAR002" as "MAROO2"
        Case and O/0 are both unreliable, in the same field, in both directions.

    One of the four files is not a delivery note at all
        A GB Lift Trucks LOLER examination report, scanned UPSIDE DOWN. Both halves matter:
        the tray gets other paperwork in it, and a page can arrive at 180 degrees. It carries
        a reference number, a date and a company address, every one of which would parse — so
        the first question is "is this one of ours", never "what is the number". The cost of
        reading a number off the wrong page is a file that is confidently and permanently
        misnamed, and nobody opens a delivery note they have already filed.

── THE REGIONS ARE FRACTIONS, NOT PIXELS ───────────────────────────────────────────────────

Scanners change DPI and somebody will re-scan at 300 instead of 200. Every box below is a
fraction of the page, so the same numbers hold at any resolution, and each is generous enough
to survive the few millimetres of drift a sheet picks up going through a feeder.
"""
from __future__ import annotations

import re
from typing import Any, Callable, Dict, Optional, Sequence, Tuple

# (left, top, right, bottom) as fractions of the page. Generous on purpose.
REGIONS: Dict[str, Tuple[float, float, float, float]] = {
    # The right-hand value column: Delivery Note N, Delivery Date, Sales Order, Account No.
    "values": (0.60, 0.04, 1.00, 0.22),
    # The left column under "Invoice Address" — the company being billed.
    "invoice": (0.00, 0.06, 0.30, 0.20),
    # The footer's "Page x of y", centred under the body.
    "footer": (0.30, 0.94, 0.75, 1.00),
    # Enough of the page to tell whether it is one of ours at all.
    "whole": (0.00, 0.00, 1.00, 1.00),
}

# What makes a page one of SDI's delivery notes. Several weak signals rather than one strong
# one: a scan loses any single line to a fold, a staple or a signature written across it, so
# requiring all of them sends good notes to _Unsorted, and requiring one lets a supplier's own
# delivery note through wearing our numbering.
_MARKERS = ("deliverynote", "wearesdi", "sdidisplays", "receivedingood", "invoiceaddre",
            "soldsubjecttoour")
_MIN_MARKERS = 2

# Letters OCR reaches for when it is looking at a digit. Applied ONLY to a run that should be
# numeric — never to a whole token, or "TES01" becomes "1E501".
_AS_DIGIT = {"O": "0", "o": "0", "l": "1", "L": "1", "I": "1", "i": "1",
             "S": "5", "B": "8", "Z": "2", "g": "9"}

# What a company is called once the company-ness is taken off. Longest first, so "UK LIMITED"
# does not leave a stray "UK". "ple" and "pic" are here because that is what OCR makes of plc.
_CORPORATE_TAIL = (
    "public limited company", "limited liability partnership", "and company",
    "stores limited", "uk limited", "group limited", "holdings limited",
    "limited", "ltd", "plc", "ple", "pic", "llp", "inc", "group", "holdings",
    "stores", "uk", "gb", "& co", "and co",
)

_NUMBER = re.compile(r"\b(\d{8})\b")


def _digits(text: Any) -> str:
    return "".join(_AS_DIGIT.get(ch, ch) for ch in str(text or ""))


def _norm(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def looks_like_a_delivery_note(whole_page_text: Any) -> bool:
    """Whether this page is one of SDI's own delivery notes.

    ASKED BEFORE ANY FIELD IS READ, for the forklift report's sake.
    """
    blob = _norm(whole_page_text)
    return sum(1 for m in _MARKERS if m in blob) >= _MIN_MARKERS


def delivery_note_number(values_text: Any) -> Optional[str]:
    """The number this note is filed under, or None.

    THE TOPMOST NUMBER IN THE VALUE COLUMN. Delivery Note N is the first row of that block,
    with Delivery Date, Sales Order, Account No and Customer Ref beneath it — so reading order
    settles which is which without depending on the labels, which are the least reliable text
    on the page. On the one sampled note where the customer ref also survives the digits-only
    pass (30022351 and 32206404), the note number is the one that comes first.

    NOT anchored on the 300 prefix every sampled number happens to carry. That is a fact about
    this month's numbering, not about the document, and a counter rolls over.
    """
    for token in _NUMBER.findall(_digits(str(values_text or ""))):
        return token
    return None


def account_code(values_text: Any) -> Optional[str]:
    """TES01 / MAR002 / BOT01, or None.

    The letters are letters and the tail is digits, so each half is normalised on its own —
    `_digits` over the whole token turns TES01 into 1E501 and BOT01 into 80101.
    """
    for raw in re.findall(r"\b([A-Za-z]{3})\s?([A-Za-z0-9]{2,4})\b", str(values_text or "")):
        tail = _digits(raw[1])
        if tail.isdigit() and len(tail) >= 2:
            return (raw[0] + tail).upper()
    return None


def page_position(footer_text: Any) -> Tuple[Optional[int], Optional[int]]:
    """(page, of) off the footer, or (None, None).

    "Page 1 of 1" arrives as "Page Lot 1", "Pageloftl", "Page lofi" and "Page 1of1" — the 1
    and the "of" fuse, the f is lost, the l and the 1 swap. So the word "of" is not matched at
    all: the digits are pulled out of whatever is there, and one number means "1 of that".

    Where the footer is unreadable this returns (None, None) and the caller groups on the
    delivery note number changing instead — which is the more reliable signal anyway, since
    the number reads on every sampled page and this does not.
    """
    # ONLY l/I -> 1 HERE, NEVER o -> 0. Everywhere else on the page an "o" in a numeric field
    # is a mis-read zero; in this footer "of" is a WORD sitting between the two numbers, so
    # mapping it turns "Page Lot 1" into 10 and 1 and the note claims to be page 10.
    blob = re.sub(r"(?i)page", " ", str(footer_text or ""))
    blob = blob.translate(str.maketrans({"l": "1", "L": "1", "I": "1", "i": "1"}))
    numbers = [int(n) for n in re.findall(r"\d{1,3}", blob)]
    numbers = [n for n in numbers if 1 <= n <= 99]
    if not numbers:
        return None, None
    if len(numbers) == 1:
        return 1, numbers[0]
    return numbers[0], numbers[1]


def client_name(invoice_text: Any) -> Optional[str]:
    """A short client name from the invoice address — "Tesco", "Boots", "Marks & Spencer".

    THE INVOICE ADDRESS, NOT THE DELIVERY ADDRESS. The delivery address is the store or the
    carrier — "TESCO WALLYFORD EXPRESS", "Diebold Nixdorf (M&S)", "ECC COLLECTION" — and it
    changes every drop, so filing on it scatters one customer across a hundred names.

    The company is the first line UNDER the heading, and the heading itself is dropped by
    name. Derived rather than looked up in a table of the three customers this sample happens
    to contain, because the fourth would file under nothing at all.
    """
    for line in str(invoice_text or "").splitlines():
        cleaned = re.sub(r"(?i)invoice\s*addre\w*", " ", line)
        cleaned = re.sub(r"[^A-Za-z0-9&'\- ]+", " ", cleaned)
        cleaned = " ".join(cleaned.split())
        if len(cleaned) < 3 or not re.search(r"[A-Za-z]{3}", cleaned):
            continue
        name = _shorten(cleaned)
        if name:
            return name
    return None


def _shorten(name: str) -> Optional[str]:
    """"TESCO STORES LIMITED" -> "Tesco". "Marks & Spencer plc" -> "Marks & Spencer"."""
    out = " ".join(str(name or "").split())
    if len(out) < 3:
        return None
    # A SINGLE TRAILING LETTER IS SCANNER NOISE, NOT PART OF THE NAME. The invoice-address
    # crop clips the edge of the column beside it, so "Marks & Spencer plc" arrives as
    # "Marks & Spencer plc E" — and the corporate tail only strips from the END, so the stray
    # letter shields "plc" and the file is filed under "Marks & Spencer Plc E".
    # Guarded: it never eats into a name that would be left too short, so "M&S" survives.
    while True:
        parts = out.split()
        if len(parts) >= 2 and len(parts[-1]) == 1 and parts[-1].isalpha() \
                and len(" ".join(parts[:-1])) >= 3:
            out = " ".join(parts[:-1])
            continue
        break
    lowered = out.lower()
    changed = True
    while changed:
        changed = False
        for tail in _CORPORATE_TAIL:
            if lowered.endswith(" " + tail) or lowered == tail:
                out = out[: len(out) - len(tail)].rstrip(" ,-")
                lowered = out.lower()
                changed = True
                break
    out = out.strip(" ,-")
    if len(out) < 2 or not re.search(r"[A-Za-z]{2}", out):
        return None
    words = []
    for word in out.split():
        # An ampersand or a short all-caps token (M&S) keeps its shape; everything else is
        # title-cased so a filename reads like a name rather than a shout.
        if "&" in word or (word.isupper() and len(word) <= 3):
            words.append(word)
        else:
            words.append(word.capitalize())
    return " ".join(words) or None


def read_page(ocr: Callable[[str], str]) -> Dict[str, Any]:
    """Everything one page says about which note it belongs to.

    `ocr(region_name)` returns the text of that region — injected so this is testable without
    Tesseract, an image, or a machine that has either.

    is_note        whether this is one of SDI's delivery notes at all
    number         the delivery note number, or None
    client         a short client name, or None
    account        the account code, or None
    page, of       the footer's position, or (None, None)
    """
    if not looks_like_a_delivery_note(ocr("whole")):
        return {"is_note": False, "number": None, "client": None, "account": None,
                "page": None, "of": None}
    values = ocr("values")
    page, total = page_position(ocr("footer"))
    return {
        "is_note": True,
        "number": delivery_note_number(values),
        "client": client_name(ocr("invoice")),
        "account": account_code(values),
        "page": page,
        "of": total,
    }


# ── grouping pages into notes ───────────────────────────────────────────────────────

def group_into_notes(pages: Sequence[Dict[str, Any]]):
    """Turn a run of read pages into notes: [{number, client, account, pages:[i,...]}, ...].

    TWO SIGNALS, AND THE WEAKER ONE IS THE ONE EVERYBODY REACHES FOR FIRST. The footer says
    "page 1 of 2", which is the explicit answer — and it is unreadable on 2 of the 12 sampled
    pages, where the number reads on all of them. So the number changing is what starts a new
    note, and the footer is a cross-check that fills in a continuation page's identity.

    A page that is not one of ours never joins a note; it is returned in `unsorted` so it can
    be filed somewhere a person will look, rather than silently attached to whichever note
    happened to come before it in the tray.
    """
    notes, unsorted, current = [], [], None
    for index, page in enumerate(pages or []):
        if not page.get("is_note"):
            unsorted.append(index)
            current = None
            continue
        number = page.get("number")
        starts_new = (
            number is not None and (current is None or number != current["number"])
            # An explicit "page 1 of n" starts a note even when the number did not read.
            or (number is None and page.get("page") == 1 and current is None)
        )
        if starts_new:
            current = {"number": number, "client": page.get("client"),
                       "account": page.get("account"), "pages": [index],
                       "expected": page.get("of")}
            notes.append(current)
            continue
        if current is None:
            # A continuation with nothing before it — the first page of the batch is missing,
            # or the note above it was unreadable. Not guessed at.
            unsorted.append(index)
            continue
        current["pages"].append(index)
        # A continuation page often carries the fields more cleanly than page 1 did.
        for field in ("client", "account"):
            if not current.get(field) and page.get(field):
                current[field] = page[field]
    return notes, unsorted
