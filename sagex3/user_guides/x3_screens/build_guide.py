"""Build Debbie's Word guide 'Your Access reports in Sage X3' from screens.json + shots/.

    python build_guide.py <out.docx>

Each report section: what it replaces in Access, where it is in Sage X3, the steps, the screenshot(s),
and a 'What to check' table for Debbie to fill in. Screens still to capture are listed at the end.
"""
import json
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

HERE = Path(__file__).parent
DATA = json.loads((HERE / "screens.json").read_text())
SCR = {s["n"]: s for s in DATA["screens"]}
GREEN = RGBColor(0x00, 0x7E, 0x45)

# The report sections for Debbie: (title, Access today, screens used, intro, steps per screen)
SECTIONS = [
    ("1. Delivered not Invoiced",
     "Access: Sales → Reports → Delivered not Invoiced",
     "Shows every delivery that has gone out but has not been invoiced yet. With the hard invoicing "
     "cut-off at the end of December, this is the list that proves nothing delivered is left uninvoiced.",
     [(3, "Delivery line list – one line per delivered item",
       ["Type Delivery line list in the menu search (top of the Sage X3 page), or go to Sales → Enquiries → Shipments → Delivery line list.",
        "Company C01 and Ship Site S01A are filled in for you.",
        "Start date and End date must be filled in. They default to about three months: set the Start date further back to catch older deliveries.",
        "Under Invoicing, untick Invoiced and leave Not Invoiced ticked.",
        "Under Category and delivery type, leave Normal ticked. Untick Subcontract and Not invoicable (these are never invoiced to a customer).",
        "Optional: put a Customer or Product in to narrow it down.",
        "Press Search. To take it into Excel, use Excel export on the right-hand panel (Global export)."]),
      (5, "Shipments by period – the same, as totals by week or month",
       ["Type Shipments by period in the menu search (Sales → Enquiries → Shipments).",
        "Tick Not Invoiced only (untick Invoiced), leave Normal ticked.",
        "Choose the Frequency (e.g. weekly or monthly) at the bottom.",
        "Memo saves your selection, and Recall brings it back next time, so you set your filters once."])]),
    ("2. Outstanding Orders",
     "Access: Sales → Reports → Outstanding Orders",
     "Shows every sales-order line that is still open: not yet delivered, or not fully delivered.",
     [(1, "Order lines – one line per open sales-order line",
       ["Type Order lines in the menu search, or go to Sales → Enquiries → Orders → Order lines.",
        "Start date and End date must be filled in. Set the Start date far enough back to include old orders.",
        "Under Order State, untick Closed and leave Not Closed ticked.",
        "Leave Normal, Loan and Direct Invoicing ticked unless you only want one type.",
        "Optional: Customer, Product or Order Type to narrow it down.",
        "Press Search, then Excel export on the right-hand panel if you want it in Excel.",
        "The same menu also has List of orders (one line per order) and Orders per period (totals)."])]),
    ("3. SDI MRP (filtered to DF)",
     "Access: SDI Reports → SDI MRP, filtered to the orders you entered (DF)",
     "Shows the stock shortages on the orders you entered yourself.",
     [])
]


def shade(cell, hex_):
    tcPr = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear")
    sh.set(qn("w:color"), "auto")
    sh.set(qn("w:fill"), hex_)
    tcPr.append(sh)


def check_table(doc, rows):
    t = doc.add_table(rows=1, cols=3)
    t.style = "Table Grid"
    for c, h in zip(t.rows[0].cells, ("Check", "Yes / No", "Your comments")):
        c.text = h
        c.paragraphs[0].runs[0].bold = True
        shade(c, "E6F4EA")
    for r in rows:
        cells = t.add_row().cells
        cells[0].text = r
    for row in t.rows:
        row.cells[0].width, row.cells[1].width, row.cells[2].width = Cm(8), Cm(2.2), Cm(6.8)
    doc.add_paragraph()


def main(out):
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name, st.font.size = "Calibri", Pt(11)
    for s in doc.sections:
        s.left_margin = s.right_margin = Cm(2)

    h = doc.add_heading("Your Access reports in Sage X3", 0)
    p = doc.add_paragraph()
    p.add_run("For Debbie Freeth, Customer Services. Draft for you to try – the screens are still being "
              "confirmed by Acuity (Marc).").italic = True

    doc.add_heading("How to use this guide", 1)
    for t in [
        "Each section takes one of the reports you use every day in Access and shows the Sage X3 screen that replaces it: where it is, which boxes to set, and a picture of the screen.",
        "Try each one on the Sage X3 training site, then fill in the 'What to check' table under it. Anything missing or different from Access, write it down there.",
        "Finding a screen: type its name into 'Search the navigation menu…' at the top of the Sage X3 page.",
        "Every enquiry has Search (run it), Criteria (change the filters) and, on the right-hand panel, Global export → Excel export.",
        "These screens are enquiries: they only show information, they don't change anything. The training site is separate from Access and from the live system.",
        "You'll need a login to the training site. James will set this up and send you the link.",
    ]:
        doc.add_paragraph(t, style="List Bullet")

    for title, access, intro, screens in SECTIONS:
        doc.add_page_break()
        doc.add_heading(title, 1)
        p = doc.add_paragraph()
        p.add_run("Today: ").bold = True
        p.add_run(access)
        doc.add_paragraph(intro)
        if not screens:
            p = doc.add_paragraph()
            r = p.add_run("Still being checked. Sage X3 has a standard shortage enquiry and MRP results, but we have not yet "
                          "found a way to filter them to the orders one person entered. We are checking this with Acuity and "
                          "will add it here.")
            r.italic = True
            doc.add_heading("What to check (on our call)", 2)
            check_table(doc, ["Which filters do you set in Access?", "What do you look for in the results?",
                              "What do you do next with it?"])
            continue
        for n, sub, steps in screens:
            s = SCR[n]
            doc.add_heading(sub, 2)
            p = doc.add_paragraph()
            p.add_run("Where: ").bold = True
            p.add_run(f"{s['path']}  (screen code {s['code']})")
            for i, step in enumerate(steps, 1):
                sp = doc.add_paragraph(f"{i}.\t{step}")
                sp.paragraph_format.left_indent = Cm(0.9)
                sp.paragraph_format.first_line_indent = Cm(-0.9)
                sp.paragraph_format.tab_stops.add_tab_stop(Cm(0.9))
                sp.paragraph_format.space_after = Pt(2)
            for shot in s["shots"]:
                f = HERE / "shots" / shot
                if f.exists():
                    doc.add_picture(str(f), width=Cm(16.5))
                    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
                    cap = doc.add_paragraph(f"The selection screen: {sub.split(' – ')[0]}")
                    cap.runs[0].italic, cap.runs[0].font.size = True, Pt(9)
            if s.get("results_shot"):
                doc.add_picture(str(HERE / "shots" / s["results_shot"]), width=Cm(16.5))
            else:
                p = doc.add_paragraph()
                r = p.add_run("Results screen: picture to follow.")
                r.italic, r.font.color.rgb = True, RGBColor(0x88, 0x88, 0x88)
        doc.add_heading("What to check", 2)
        check_table(doc, ["Does it show the same orders / deliveries as your Access report?",
                          "Are any columns you use missing?",
                          "Are the filters you need there?",
                          "Does the Excel export give you what you need?",
                          "Anything else?"])

    doc.save(out)
    print("written", out)


if __name__ == "__main__":
    main(sys.argv[1])
