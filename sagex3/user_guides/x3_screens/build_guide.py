"""Build the designed Word guides 'Your Access reports in Sage X3' from the marked-up screenshots.

    python annotate.py                          (once, after new screenshots: shots/ -> shots_marked/)
    python build_guide.py debbie <out.docx>     Customer Services (Debbie Freeth)
    python build_guide.py claire <out.docx>     Finance year end (Claire Newall)
    python build_guide.py simon <out.docx>      Simon Foister, Sam, Ewa (report list of 13 Oct)

Each report gets: an Access -> Sage X3 panel, numbered steps whose numbers match the red callouts on the
screenshot, a tip, and a 'What to check' table for the user to fill in. The tracker is screens.json.
"""
import os
import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

HERE = Path(__file__).parent
MARKED = HERE / "shots_marked"
PRIVATE = Path(os.environ["X3_PRIVATE_SHOTS"]) / "marked" if os.environ.get("X3_PRIVATE_SHOTS") else None


def image_path(name):
    """Marked screenshot: the committed set, or the private set (screens showing customer / supplier names)."""
    for d in (MARKED, PRIVATE):
        if d and (d / name).exists():
            return d / name
    return None
INK = RGBColor(0x1F, 0x2A, 0x30)
GREEN = RGBColor(0x00, 0x6B, 0x45)
GREY = RGBColor(0x6B, 0x72, 0x78)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
G_HEX, LIGHT_HEX, TIP_HEX, WARN_HEX = "006B45", "E8F3EE", "FFF6DB", "FDECEE"
DATE = "16 November 2026"

# ---------------------------------------------------------------- content
# A screen block: (heading, where, image or None, [(callout no. or None, step text)], tip or None)
DELIVERY_LINE_LIST = (
    "Delivery line list", "Sales → Enquiries → Shipments → Delivery line list",
    "01_CONSCSF_delivery_line_list_selection.png",
    [(None, "Type Delivery line list in the menu search at the top of Sage X3 and open it. Company C01 and Ship Site S01A are already filled in."),
     (1, "Set the Start date and End date. They must be filled in, and default to about three months – move the Start date back to catch older deliveries."),
     (2, "Under Invoicing, untick Invoiced. Leave Not Invoiced ticked."),
     (3, "Untick Subcontract and Not invoiceable – these are never invoiced to a customer. Leave Normal ticked."),
     (4, "Press Search. The deliveries not yet invoiced are listed, one line per item delivered."),
     (5, "To work on it in Excel, choose Excel export on the right-hand panel.")],
    "Put a Customer or a Product in to see just one account or part.",
    [("14_CONSCSF_delivery_lines_not_invoiced_results.png",
      "with Invoiced unticked (1), the deliveries not yet invoiced are listed underneath, with the number of results (2): "
      "shipment number, customer, delivery date, product and description, one line per item.")])
SHIPMENTS_BY_PERIOD = (
    "Shipments by period – totals by week or month", "Sales → Enquiries → Shipments → Shipments by period",
    "02_FUNGRHSDH1_shipments_by_period_selection.png",
    [(1, "Untick Invoiced and leave Not Invoiced ticked."),
     (2, "Choose which deliveries count: normally Normal (and Loan). Leave Subcontract, Inter-site and Not invoicable unticked."),
     (None, "Set the Frequency at the bottom of the screen (weekly or monthly) and run it."),
     (3, "Press Memo to save these settings under a name. Next time press Recall and they are filled in for you.")],
    "Memo / Recall means you set your filters once and reuse them every day.")
ORDER_LINES = (
    "Order lines", "Sales → Enquiries → Orders → Order lines",
    "11_CONSCSP_order_lines_selection.png",
    [(None, "Click All (top left) → Sales → Enquiries → Orders → Order lines. The screen is called Consultation order line. Company C01 and Sales Site S01A are filled in."),
     (1, "Set the Start date and End date. Move the Start date back far enough to include old orders (e.g. 01/01/20)."),
     (2, "Under Order State, untick Closed. Leave Not Closed ticked, so only open lines show."),
     (3, "Press Search. Every open sales-order line is listed."),
     (4, "Excel export on the right-hand panel takes the list into Excel.")],
    "Optional filters: Customer, Product or Order Type. The same Orders menu has List of orders (one line per order) and Orders per period (totals).",
    [("13_CONSCSP_order_lines_results.png",
      "the open order lines are listed underneath: order number, customer, date, product and description. "
      "The count and page numbers are at the top of the list (1); Excel export (2) takes all of them into Excel.")])
RECEIPT_LINES = (
    "Receipt lines – every item received and not yet invoiced", "Purchasing → Enquiries → Receipts → Receipt lines",
    "15_CONSCPS_receipt_lines_selection.png",
    [(None, "Click All (top left) → Purchasing → Enquiries → Receipts → Receipt lines. The screen is called Receipt lines inquiry. Company C01 and Receiving Site S01A are filled in."),
     (1, "Set the Start date back far enough – it defaults to about three months."),
     (2, "Under Status, untick Invoiced and leave Not Invoiced ticked."),
     (3, "Press Search. The receipt lines are listed underneath: receipt number, supplier, receipt date, product and description."),
     (4, "Excel export on the right-hand panel takes the list into Excel.")],
    "Optional: a Starting and Ending Supplier, or a Product. List of receipts (one line per receipt) and Receipts by period (monthly totals, with Memo / Recall) sit in the same menu and work the same way.")
RECEIPT_ENTRY = (
    "Checking one receipt", "Purchasing → Receipts → Receipts",
    "05_GESPTH_purchase_receipt_entry.png",
    [(1, "Find the receipt in the Purchase receipts list on the left – filter by Receipt Date, Receipt No. or Supplier – and open it."),
     (2, "On each line, Invoiced (status) and Invoiced (quantity) show how much of that line the supplier has invoiced."),
     (3, "Receipt situation and Receipt Enquiry on the right-hand panel show the whole receipt's position.")],
    "This screen is for one receipt at a time. For the full list, use Receipt lines above.")

SHORTAGE = (
    "Shortage – materials short on orders", "Stock → Enquiries → Allocations → Shortage",
    "20_CONSSMQ_shortage_selection.png",
    [(None, "Click All → Stock → Enquiries → Allocations → Shortage."),
     (1, "Site S01A is filled in."),
     (2, "Optional: a First and Last Product to look at a range of parts."),
     (3, "Document Type: leave All Types, or choose sales orders or works orders. Document: one order number."),
     (4, "Press Search. Each shortage is listed: product, shortage type, document type, order number and line, and the quantity short."),
     (5, "Excel export on the right-hand panel.")],
    "To see just your own orders today, put one order number in Document. A filter by who entered the order is with Acuity.")
PO_ENQUIRY = (
    "Order Enquiry – purchase orders", "Purchasing → Enquiries → Orders → List of orders",
    "22_CONSCPO_purchase_order_enquiry_selection.png",
    [(None, "Click All → Purchasing → Enquiries → Orders → List of orders. The screen is called Order Enquiry. Company C01 and Purchasing Site S01A are filled in."),
     (1, "Optional: a Starting and Ending Supplier."),
     (2, "Set the Start date back far enough to include older orders."),
     (3, "Press Search."),
     (4, "Excel export on the right-hand panel.")],
    "Order lines in the same menu gives one line per item ordered, with its expected receipt date – the one for “PO delivery by date”.")
PO_MENU = (
    "Line by line, with delivery dates", "Purchasing → Enquiries → Orders",
    "21_purchasing_enquiries_orders_menu.png",
    [(1, "The Orders menu holds List of orders (one line per order), Order lines (one line per item, with the expected receipt date), "
         "Subcontract lines and Orders per period (totals).")],
    None)
DEBTORS = (
    "Customer aged balance", "A/P-A/R Accounting → Enquiries",
    "24_APAR_enquiries_menu.png",
    [(1, "Click All → A/P-A/R Accounting → Enquiries. Customer aged bal to date gives the aged debtors; Customer situation gives one customer's full position.")],
    "Supplier aged bal to date in the same menu is the creditors' equivalent.")
MRP_MENUS = (
    "Where MRP lives", "Purchasing → Ordering → Planning Workbench;  Manufacturing → Enquiries → Reorder Results",
    "19_purchasing_menu_ordering_orders.png",
    [(1, "Purchasing → Ordering → Planning Workbench: the buyer's view of MRP's suggestions – what to buy and when.")],
    None,
    [("17_manufacturing_menu_enquiries.png",
      "Manufacturing → Enquiries → Reorder Results (1) holds the MRP results; List of WOs (2) lists the works orders.")])
STOCK_MENU = (
    "Stock enquiries", "Stock → Enquiries → Stock",
    "25_stock_enquiries_stock_menu.png",
    [(1, "Stock → Enquiries → Stock: Stock by Site, Stock by product, Stock by Lots, Detailed Stock (by lot and location), "
         "Projected Stock, Available Stock, Obsolete Stock and more."),
     (2, "Stock → Enquiries → Transactions: every movement in and out – the usage report."),
     (None, "Stock → Enquiries → Locations: what is in each location.")],
    "Month-end stock value is usually a printout (stock valuation) – being confirmed.")
MRP_RESULTS = (
    "MRP results for one product", "Manufacturing → Enquiries → Reorder Results → MRP - MPS Results",
    "26_CONSSCBB1_mrp_mps_results.png",
    [(1, "Site S01A is filled in."),
     (2, "Enter the Product (it must be filled in – this screen is one product at a time)."),
     (3, "Press Search: stock, allocations, shortages and MRP's suggestions for that product."),
     (4, "Excel export on the right-hand panel.")],
    "For the full list of suggestions across all products, use the Planning Workbench (Purchasing → Ordering).")
BOM_MULTI = (
    "Exploded BOM – Multi-level", "Common data → BOMs (BOMs BOMP)",
    "27_GESBODP_boms_multilevel.png",
    [(None, "Click All → Common data → BOMs."),
     (2, "Pick the part from the BOM list on the left (filter by Parent)."),
     (3, "Its Parent Product shows at the top."),
     (1, "Press Multi-level: every component at every level, with quantities."),
     (4, "The SDI Drawing Number and SDI Revision Number fields are on the BOM too.")],
    "Routings and Production Slip, next to Multi-level, show the route and the shop-floor slip for the same part.")

STD_CHECKS = ["It shows the same items as my Access report", "The columns I use are there",
              "I can filter it the way I need", "The Excel export gives me what I need"]


def section(title, access_path, access_what, x3_what, blocks, checks, note=None, ready=None):
    return dict(title=title, access_path=access_path, access_what=access_what, x3_what=x3_what,
                blocks=blocks, checks=checks, note=note, ready=bool(blocks) if ready is None else ready)


GUIDES = {
    "debbie": dict(
        title="Your Access reports in Sage X3",
        subtitle="A step-by-step guide for Customer Services",
        prepared_for="Debbie Freeth, Customer Service Manager",
        intro=("From 4 January 2027 Sage X3 replaces Access. This guide takes the three reports you use every day "
               "and shows exactly where each one lives in Sage X3, which boxes to tick, and what you get. "
               "The red numbers on each picture match the numbered steps beside it."),
        sections=[
            section("Delivered not Invoiced", "Sales → Reports → Delivered not Invoiced",
                    "Deliveries that have gone out but have not been invoiced.",
                    "Two standard screens: Delivery line list (every item) and Shipments by period (totals).",
                    [DELIVERY_LINE_LIST, SHIPMENTS_BY_PERIOD], STD_CHECKS,
                    note="Year end: Finance have a hard invoicing cut-off at the end of December. This is the list "
                         "that shows nothing delivered is left uninvoiced."),
            section("Outstanding Orders", "Sales → Reports → Outstanding Orders",
                    "Sales-order lines still open: not yet delivered, or not fully delivered.",
                    "The standard Order lines enquiry, filtered to lines that are not closed.",
                    [ORDER_LINES], STD_CHECKS),
            section("SDI MRP (your orders)", "SDI Reports → SDI MRP, filtered to DF",
                    "Stock shortages on the orders you entered yourself.",
                    "The standard Shortage enquiry (Stock → Enquiries → Allocations → Shortage). It filters by product, "
                    "document type and document – not yet by who entered the order.",
                    [SHORTAGE], ["Which filters do you set in Access?", "What do you look for in the results?",
                                 "What do you do next with it?"],
                    note="The screen is found. Filtering it to the orders you entered (your “DF”) is not a standard filter – "
                         "we're checking with Acuity, and we'll go through it together on our call.", ready=False),
        ]),
    "simon": dict(
        title="Your reports in Sage X3",
        subtitle="Purchasing, stock, sales and finance reports – for Simon, Sam and Ewa",
        prepared_for="Simon Foister (with Sam and Ewa)",
        intro=("On 13 October you sent us the 17 Access reports you, Sam and Ewa use. This guide shows where the standard "
               "ones live in Sage X3 and how to run them, and lists the ones we need you to define. The red numbers on "
               "each picture match the numbered steps beside it."),
        sections=[
            section("Purchase orders: delivery dates and outstanding POs (REP-01, REP-04)",
                    "PO delivery by date; Outstanding purchase orders, to Excel",
                    "Open purchase orders and when the goods are due in (for Sam).",
                    "Order Enquiry (List of orders) and Order lines, each with Excel export.",
                    [PO_ENQUIRY, PO_MENU], STD_CHECKS),
            section("Receiving goods (REP-02)", "Receive goods on site",
                    "Goods booked in from suppliers (for Sam).",
                    "Receipt lines, List of receipts and Receipts by period.",
                    [RECEIPT_LINES], STD_CHECKS),
            section("Outstanding sales orders (REP-07)", "Outstanding sales orders",
                    "Sales-order lines still open.",
                    "The standard Order lines enquiry, filtered to lines that are not closed.",
                    [ORDER_LINES], STD_CHECKS),
            section("Debtors (REP-06)", "Debtors reports (for Ewa)",
                    "Aged debtors and customer balances.",
                    "Customer aged bal to date and Customer situation (A/P-A/R Accounting → Enquiries).",
                    [DEBTORS], STD_CHECKS),
            section("MRP suggestions (REP-08)", "MRP suggestions",
                    "What to make and buy, and when.",
                    "Planning Workbench (Purchasing) and Reorder Results (Manufacturing).",
                    [MRP_MENUS, MRP_RESULTS], ["Which suggestions do you act on today?", "Do you filter by buyer, product group or date?"],
                    note="MRP - MPS Results is one product at a time; the list across all products is the Planning Workbench – being confirmed with Acuity.",
                    ready=False),
            section("Stock: month end, usage, locations and movements (REP-09, REP-10, REP-13)",
                    "End-of-month stock; Stock usage; Stock tracking, booking-in, locations and movements",
                    "Stock value at month end, what has been used, and where stock is.",
                    "Stock → Enquiries: Stock, Transactions and Locations.",
                    [STOCK_MENU], ["Which totals do you need at month end (quantity, value, by location)?",
                                   "Over what period do you look at usage?"],
                    note="The Stock enquiries are found; Transactions and Locations screens and the month-end valuation will be added once confirmed.", ready=False),
            section("Exploded BOMs, incl. carton call-offs (REP-03)", "Exploded BOMs",
                    "Every component at every level, with quantities (for Sam).",
                    "Common data → BOMs, then the Multi-level button.",
                    [BOM_MULTI], ["It shows every level, like Access", "The call-off cartons show", "The quantities are right"]),
            section("Reports we need you to define (REP-05, 11, 12, 14, 15, 16, 17)",
                    "Your list, 13 October",
                    "These aren't standard in Sage X3 the way they work at SDI, so we need to know how they work today before we build them.",
                    "Built as Sage X3 printouts or enquiries once defined.",
                    [], ["REP-14 Production vs Proto Live (most important): how do we tell a prototype order from a production one?",
                         "REP-11 Internal revenue: how is it calculated today? An example with figures would be ideal.",
                         "REP-12 Total revenue: what's included and excluded, and by invoice or order date?",
                         "REP-15 Project tracker: could you send the current layout?",
                         "REP-16 Manufactured sales: what counts as manufactured?",
                         "REP-17 Department on-time delivery: measured how, and by which department?",
                         "REP-05 Export invoices (Ewa): one or two recent examples, and what the report must show"],
                    note="Please answer in the table below, or by email.", ready=False),
        ]),
    "claire": dict(
        title="Year-end checks in Sage X3",
        subtitle="Where Finance's year-end lists live in Sage X3",
        prepared_for="Claire Newall, Financial Controller",
        intro=("For year end and go-live, these are the Sage X3 screens that show what is delivered but not invoiced, "
               "received but not invoiced, and what is still out with subcontractors. Each page shows where the screen "
               "is and which boxes to set; the red numbers on the pictures match the steps."),
        sections=[
            section("Delivered not invoiced", "Sales → Reports → Delivered not Invoiced",
                    "Deliveries gone out and not yet invoiced – the year-end invoicing cut-off.",
                    "Delivery line list (every item) and Shipments by period (totals).",
                    [DELIVERY_LINE_LIST, SHIPMENTS_BY_PERIOD], STD_CHECKS),
            section("Received not invoiced", "Purchase receipts with no supplier invoice yet",
                    "Goods booked in from suppliers and not yet invoiced – the year-end accrual.",
                    "Receipt lines, List of receipts and Receipts by period, each with a Not Invoiced filter.",
                    [RECEIPT_LINES, RECEIPT_ENTRY], STD_CHECKS),
            section("Invoices to be issued (month-end accrual)", "The month-end accrual for delivered-not-invoiced",
                    "An accrual posted at month end for deliveries not yet invoiced, reversed next month.",
                    "Sage X3's Invoices to be issued closing process (Financials → Closing processes).",
                    [], ["How is the accrual done in Access today?", "Which nominal codes does it use?"],
                    note="Being confirmed with Acuity."),
            section("Subcontract orders not booked in", "Subcontract orders waiting to be booked in (with Sam)",
                    "Work sent out to subcontractors and not yet received back.",
                    "Purchasing → Enquiries → Subcontract: Allocations, Allocation Shortages and Subcontract consumption.",
                    [("Where the subcontract enquiries are", "Purchasing → Enquiries → Subcontract",
                      "16_purchasing_subcontract_menu.png",
                      [(1, "Click All → Purchasing → Enquiries, then open Subcontract. It holds Allocations, Allocation Shortages and Subcontract consumption.")],
                      "Which of these shows orders still out with the subcontractor is being confirmed with Acuity.")],
                    ["Which orders do you and Sam check today?"],
                    note="The menu is found; the exact screen for “not yet received back” is being confirmed with Acuity.",
                    ready=False),
        ]),
}


# ---------------------------------------------------------------- helpers
def shade(cell, hex_):
    tcPr = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear"); sh.set(qn("w:color"), "auto"); sh.set(qn("w:fill"), hex_)
    tcPr.append(sh)


def set_borders(table, val="single", color="D5DADD", size=4):
    tblPr = table._tbl.tblPr
    b = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{edge}")
        e.set(qn("w:val"), val)
        if val != "nil":
            e.set(qn("w:sz"), str(size)); e.set(qn("w:color"), color)
        b.append(e)
    tblPr.append(b)


def cell_margins(cell, cm=0.25):
    tcPr = cell._tc.get_or_add_tcPr()
    m = OxmlElement("w:tcMar")
    for side in ("top", "left", "bottom", "right"):
        e = OxmlElement(f"w:{side}"); e.set(qn("w:w"), str(int(cm * 567))); e.set(qn("w:type"), "dxa"); m.append(e)
    tcPr.append(m)


def run(p, text, bold=False, size=None, color=None, italic=False):
    r = p.add_run(text)
    r.bold, r.italic = bold, italic
    if size: r.font.size = Pt(size)
    if color is not None: r.font.color.rgb = color
    return r


def para(container, text="", size=10.5, color=INK, bold=False, after=4, align=None):
    p = container.add_paragraph()
    if text: run(p, text, bold=bold, size=size, color=color)
    p.paragraph_format.space_after = Pt(after)
    if align is not None: p.alignment = align
    return p


def spacer(doc, pt=2):
    doc.add_paragraph().paragraph_format.space_after = Pt(pt)


def callout(p, n):
    r = p.add_run(f" {n} ")
    r.bold, r.font.size, r.font.color.rgb = True, Pt(9.5), WHITE
    rPr = r._r.get_or_add_rPr()
    sh = OxmlElement("w:shd"); sh.set(qn("w:val"), "clear"); sh.set(qn("w:color"), "auto"); sh.set(qn("w:fill"), "D62839")
    rPr.append(sh)
    p.add_run("  ")


def box(doc, text, fill, label=None, label_color=INK):
    t = doc.add_table(rows=1, cols=1); set_borders(t, "nil")
    c = t.rows[0].cells[0]; shade(c, fill); cell_margins(c, 0.3)
    p = c.paragraphs[0]
    if label: run(p, label + "   ", bold=True, color=label_color, size=10)
    run(p, text, size=10, color=INK)
    spacer(doc)


def heading(doc, text, level):
    h = doc.add_heading(text, level)
    for r in h.runs:
        r.font.color.rgb = GREEN
    return h


def footer(section, text):
    f = section.footer.paragraphs[0]
    run(f, text + "     Page ", size=8, color=GREY)
    for kind, txt in (("begin", None), (None, "PAGE"), ("end", None)):
        r = f.add_run(); r.font.size = Pt(8); r.font.color.rgb = GREY
        if kind:
            fc = OxmlElement("w:fldChar"); fc.set(qn("w:fldCharType"), kind); r._r.append(fc)
        else:
            it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve"); it.text = txt; r._r.append(it)


# ---------------------------------------------------------------- build
def build(name, out):
    g = GUIDES[name]
    doc = Document()
    st = doc.styles["Normal"]; st.font.name = "Calibri"; st.font.size = Pt(10.5); st.font.color.rgb = INK
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    for lvl, size in ((1, 18), (2, 13.5)):
        hs = doc.styles[f"Heading {lvl}"]; hs.font.name = "Calibri"; hs.font.size = Pt(size); hs.font.bold = True
    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    sec.left_margin = sec.right_margin = Cm(1.8); sec.top_margin = Cm(1.6); sec.bottom_margin = Cm(1.6)
    sec.different_first_page_header_footer = True
    footer(sec, f"SDI · {g['title']} · Draft {DATE}")

    # ---- cover
    band = doc.add_table(rows=1, cols=1); set_borders(band, "nil")
    c = band.rows[0].cells[0]; shade(c, G_HEX); cell_margins(c, 0.9)
    run(c.paragraphs[0], "SAGE X3  ·  USER GUIDE", bold=True, size=10, color=RGBColor(0xCF, 0xEB, 0xDD))
    p = c.add_paragraph(); p.paragraph_format.space_before = Pt(30); run(p, g["title"], bold=True, size=30, color=WHITE)
    p = c.add_paragraph(); run(p, g["subtitle"], size=15, color=RGBColor(0xE6, 0xF4, 0xEC))
    p = c.add_paragraph(); p.paragraph_format.space_after = Pt(30)
    for _ in range(2): spacer(doc, 10)
    meta = doc.add_table(rows=4, cols=2); set_borders(meta, "nil")
    for i, (k, v) in enumerate((("Prepared for", g["prepared_for"]), ("Prepared by", "James Gray, AI and Systems Controller"),
                                ("Date", DATE), ("Status", "Draft – screens being confirmed with Acuity"))):
        a, b = meta.rows[i].cells
        a.width, b.width = Cm(4), Cm(13.4)
        run(a.paragraphs[0], k, bold=True, size=11, color=GREY)
        run(b.paragraphs[0], v, size=11)
    for _ in range(2): spacer(doc, 10)
    p = para(doc, after=8)
    run(p, g["intro"], size=12)
    p.add_run().add_break(WD_BREAK.PAGE)

    # ---- at a glance
    heading(doc, "At a glance", 1)
    t = doc.add_table(rows=1, cols=3); set_borders(t); t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for c, txt in zip(t.rows[0].cells, ("Your report in Access", "In Sage X3", "Ready to try?")):
        shade(c, G_HEX); run(c.paragraphs[0], txt, bold=True, color=WHITE)
    for i, s in enumerate(g["sections"], 1):
        r = t.add_row().cells
        run(r[0].paragraphs[0], f"{i}. {s['title']}", bold=True)
        para(r[0], s["access_path"], size=9, color=GREY, after=0)
        run(r[1].paragraphs[0], s["x3_what"], size=10)
        ready = s["ready"]
        shade(r[2], LIGHT_HEX if ready else TIP_HEX)
        run(r[2].paragraphs[0], "Yes – try it" if ready else "Being confirmed", bold=True,
            color=GREEN if ready else RGBColor(0x8A, 0x60, 0x00))
    for row in t.rows:
        for c, w in zip(row.cells, (Cm(5.6), Cm(8.2), Cm(3.6))):
            c.width = w; cell_margins(c, 0.2)

    if len(g["sections"]) > 4:
        doc.add_page_break()
    else:
        spacer(doc, 8)
    heading(doc, "Before you start", 2)
    t = doc.add_table(rows=0, cols=2); set_borders(t)
    for k, v in (("Finding a screen", "Type its name into “Search the navigation menu…” at the top of Sage X3."),
                 ("Search / Criteria", "Search runs the enquiry. Criteria takes you back to change the filters."),
                 ("Start and End date", "Must be filled in on most enquiries. They default to about three months – widen them for older items."),
                 ("Excel export", "On the right-hand panel of every enquiry: Global export → Excel export."),
                 ("Memo / Recall", "On the “by period” screens: save your filters once, reuse them every time."),
                 ("Safe to explore", "Enquiries only show information – they don't change anything.")):
        a, b = t.add_row().cells
        shade(a, LIGHT_HEX); run(a.paragraphs[0], k, bold=True, size=10); run(b.paragraphs[0], v, size=10)
        a.width, b.width = Cm(4.2), Cm(13.2); cell_margins(a, 0.2); cell_margins(b, 0.2)

    # ---- one chapter per report
    for i, s in enumerate(g["sections"], 1):
        doc.add_page_break()
        band = doc.add_table(rows=1, cols=1); set_borders(band, "nil")
        c = band.rows[0].cells[0]; shade(c, G_HEX); cell_margins(c, 0.35)
        run(c.paragraphs[0], f"{i}    ", bold=True, size=20, color=RGBColor(0xCF, 0xEB, 0xDD))
        run(c.paragraphs[0], s["title"], bold=True, size=20, color=WHITE)
        spacer(doc, 0)

        cmp_ = doc.add_table(rows=2, cols=2); set_borders(cmp_)
        for c, txt in zip(cmp_.rows[0].cells, ("TODAY IN ACCESS", "IN SAGE X3")):
            shade(c, "F1F3F4"); run(c.paragraphs[0], txt, bold=True, size=9, color=GREY)
        a, b = cmp_.rows[1].cells
        run(a.paragraphs[0], s["access_path"], bold=True)
        para(a, s["access_what"], size=10, after=0)
        run(b.paragraphs[0], s["x3_what"], size=10.5)
        for row in cmp_.rows:
            for c in row.cells:
                c.width = Cm(8.7); cell_margins(c, 0.25)
        spacer(doc, 0)
        if s.get("note"):
            box(doc, s["note"], TIP_HEX if s["blocks"] else WARN_HEX, "Note")

        for blk in s["blocks"]:
            hd, where, img, steps, tip = blk[:5]
            results = blk[5] if len(blk) > 5 else []
            heading(doc, hd, 2).paragraph_format.keep_with_next = True
            p = para(doc, after=6); p.paragraph_format.keep_with_next = True; run(p, "Where:   ", bold=True, color=GREY, size=10); run(p, where, size=10)
            for n, text in steps:
                p = doc.add_paragraph(); p.paragraph_format.space_after = Pt(3); p.paragraph_format.keep_with_next = bool(img)
                p.paragraph_format.left_indent = Cm(1.0); p.paragraph_format.first_line_indent = Cm(-1.0)
                if n: callout(p, n)
                else: run(p, "  •    ", bold=True, color=GREEN)
                run(p, text, size=10.5)
            if img and image_path(img):
                doc.add_picture(str(image_path(img)), width=Cm(15.8))
                pic = doc.paragraphs[-1]; pic.alignment = WD_ALIGN_PARAGRAPH.CENTER; pic.paragraph_format.space_after = Pt(2)
                para(doc, f"{hd.split(' – ')[0]} on the Sage X3 training site. The red numbers match the steps above.",
                     size=8.5, color=GREY, after=6, align=WD_ALIGN_PARAGRAPH.CENTER)
            for rimg, rcap in results:
                if image_path(rimg):
                    rp = para(doc, after=4); rp.paragraph_format.keep_with_next = True
                    run(rp, "What you get:  ", bold=True, color=GREEN, size=10.5); run(rp, rcap, size=10.5)
                    doc.add_picture(str(image_path(rimg)), width=Cm(15.8))
                    pic = doc.paragraphs[-1]; pic.alignment = WD_ALIGN_PARAGRAPH.CENTER; pic.paragraph_format.space_after = Pt(6)
            if tip:
                box(doc, tip, LIGHT_HEX, "Tip", GREEN)

        answers = not s["blocks"]                     # questions for the user: an answer column, not Yes / No
        heading(doc, "Your answers" if answers else "What to check", 2).paragraph_format.keep_with_next = True
        cols = ("Question", "Your answer") if answers else ("Check", "Yes / No", "Your comments")
        widths = (Cm(8.4), Cm(9)) if answers else (Cm(7.2), Cm(3.2), Cm(7))
        t = doc.add_table(rows=1, cols=len(cols)); set_borders(t)
        for c, txt in zip(t.rows[0].cells, cols):
            shade(c, G_HEX); run(c.paragraphs[0], txt, bold=True, size=10, color=WHITE)
        for chk in s["checks"] + ["Anything else?"]:
            cells = t.add_row().cells
            run(cells[0].paragraphs[0], chk, size=10)
            if not answers:
                run(cells[1].paragraphs[0], "☐ Yes    ☐ No", size=10)
        for row in t.rows:
            for c, w in zip(row.cells, widths):
                c.width = w; cell_margins(c, 0.2)
            row.height = Cm(1.1 if answers else 0.8)
        for row in t.rows[:-1]:                       # keep the table on one page, with its heading
            for c in row.cells:
                for pp in c.paragraphs:
                    pp.paragraph_format.keep_with_next = True

    spacer(doc, 8)
    box(doc, "Anything missing or different from what you need? Note it in the tables and send the guide back to "
             "James Gray – or we'll go through it together.", LIGHT_HEX, "Next", GREEN)
    doc.save(out)
    print("written", out)


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
