"""User guide: Live Orders and Estimate → Sage X3 in the SDI Intelligence portal (Word). Written 20 Nov 2026.

    python build_guide.py <shots folder> <out.docx>

The shots folder holds the screenshots (01_… to 09_…, taken from the portal pages). Neither the screenshots nor the
guide are kept in git (the Estimate → X3 example is a real estimate and names its customer); rebuild it. The same
guide is on each page (Live Orders → User guide tab; Estimate → X3 → "User guide - how to use this page").
"""
import sys
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Pt, RGBColor

INK, YELLOW, MUTED = RGBColor(0x1C, 0x1C, 0x1C), RGBColor(0xB8, 0x95, 0x00), RGBColor(0x62, 0x67, 0x63)
PORTAL = "http://10.0.0.5:8071"
FOLDER = r"K:\Operations\Reporting\LiveOrders"


def p(doc, text="", bold=False, size=10.5, color=INK, after=4, italic=False):
    para = doc.add_paragraph()
    r = para.add_run(text)
    r.bold, r.italic, r.font.size, r.font.color.rgb = bold, italic, Pt(size), color
    para.paragraph_format.space_after = Pt(after)
    return para


def rich(doc, parts, style=None, after=3):
    """parts: [(text, bold)] in one paragraph (a numbered / bulleted one with style)."""
    para = doc.add_paragraph(style=style)
    for text, bold in parts:
        r = para.add_run(text)
        r.bold, r.font.size = bold, Pt(10.5)
    para.paragraph_format.space_after = Pt(after)
    return para


def steps(doc, items):
    """A numbered list that starts at 1 every time (Word's List Number style runs on across lists)."""
    for n, parts in enumerate(items, 1):
        para = rich(doc, [(f"{n}.  ", True)] + parts)
        para.paragraph_format.left_indent, para.paragraph_format.first_line_indent = Cm(0.8), Cm(-0.6)


def h(doc, text, level=1):
    para = doc.add_heading(text, level=level)
    for r in para.runs:
        r.font.color.rgb = INK
    return para


def shot(doc, folder, name, caption):
    f = Path(folder) / name
    if not f.exists():
        p(doc, f"[screenshot {name} not found]", italic=True, color=MUTED)
        return
    doc.add_picture(str(f), width=Cm(16.5))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    p(doc, caption, italic=True, size=9, color=MUTED, after=10).alignment = WD_ALIGN_PARAGRAPH.CENTER


def table(doc, head, rows, widths):
    t = doc.add_table(rows=1, cols=len(head))
    t.style = "Light Grid Accent 1"
    for i, x in enumerate(head):
        t.rows[0].cells[i].text = x
    for row in rows:
        cells = t.add_row().cells
        for i, x in enumerate(row):
            cells[i].text = x
    for row in t.rows:
        for i, w in enumerate(widths):
            row.cells[i].width = Cm(w)
            for para in row.cells[i].paragraphs:
                for r in para.runs:
                    r.font.size = Pt(9.5)
    doc.add_paragraph()


def build(shots, out):
    doc = Document()
    for s in doc.sections:
        s.left_margin = s.right_margin = Cm(2)
        s.top_margin = s.bottom_margin = Cm(1.8)
    doc.styles["Normal"].font.name = "Calibri"
    p(doc, "we.are.sdi · SDI Intelligence", bold=True, size=11, color=YELLOW, after=2)
    p(doc, "Live Orders and Estimate → Sage X3", bold=True, size=24, after=2)
    p(doc, "User guide · 20 November 2026 · for Production, Purchasing, Estimating and Customer Services", size=11,
      color=MUTED, after=12)
    rich(doc, [("Where: ", True), (f"the SDI Intelligence portal, {PORTAL} - menu ", False), ("Live Orders", True),
               (" and ", False), ("Estimate → X3", True), (" (under Overview). Any SDI PC on the network.", False)])
    rich(doc, [("Sage X3: ", True), ("both screens ", False), ("read", True), (" Sage X3; neither changes anything in "
               "it. Estimate → X3 prepares the import files; they are loaded in X3 by hand for now.", False)])
    rich(doc, [("On the pages: ", True), ("the same guide is on each screen, behind the ", False), ("📖 User guide", True),
               (" button at the top of the page.", False)], after=12)

    # ---------------------------------------------------------------- Live Orders
    h(doc, "1. Live Orders")
    p(doc, "Production's Live Orders sheet, built from Sage X3: every open works order with its material status, the "
           "hours still to do in each work centre, the works orders to raise (WO Suggestions) and the exploded BOM of "
           "each order. It follows the same rules as the Access SupplyChain sheet (the How it works tab lists them).")
    p(doc, "The screenshots use example data: the training company has no works orders loaded yet.", italic=True,
      color=MUTED, size=9.5)
    shot(doc, shots, "01_live_orders_overview.png", "Overview: headline numbers, material status, works orders by due "
                                                    "week, hours by week and shop")
    h(doc, "Get today's Live Orders", 2)
    steps(doc, ([("Press ", False), ("↻ Regenerate", True), (" (top right). It reads Sage X3 now; the progress shows "
                   "next to the button. A few minutes (the first run of a day can take longer).", False)],
                  [("When it's done, the line by the button names the new workbook, e.g. ", False),
                   ("SDI_Live_Orders_2026-11-20_0815.xlsx", True), (", with ", False), ("Preview", True),
                   (" and ", False), ("Download", True), (". The views refresh by themselves.", False)],
                  [("It is saved in ", False), (FOLDER, True), (". Every run is a new file with the date and time in its "
                   "name - nothing is overwritten, so anyone can run it at any time.", False)]))
    shot(doc, shots, "06_live_orders_regenerate_done.png", "After a run: the workbook just saved, with Preview and Download")
    h(doc, "The views", 2)
    table(doc, ["Tab", "What it shows", "For"], [
        ["Overview", "Headline numbers, red / amber / green, works orders by due week, hours by week and shop, busiest "
                     "work centres, biggest shortages, what's due in the next 14 days.", "Everyone"],
        ["Live Orders", "One line per works order, as Production's sheet. Filter by status, shop, week or level; search "
                        "by part, WO, SO or account. Click a line for its exploded BOM. Export CSV.", "Production"],
        ["Work-centre load", "Hours still to do per work centre, by the week each order is due. Darker = busier.",
         "Production"],
        ["Shortages", "Every bought-in component the open works orders need, against stock, on order and on works "
                      "orders: what's short and which orders it holds up.", "Purchasing"],
        ["WO Suggestions", "Sales-order lines for made parts that no works order or stock covers. Red = no BOM or no "
                           "route.", "Production, Customer Services"],
        ["Customers", "Works orders, red count, overdue and hours by account.", "Customer Services"],
        ["Trends", "Red / amber / green and hours across every saved run.", "Managers"],
        ["Workbooks", "Every spreadsheet in the Live Orders folder (also the 📂 Workbooks button).", "Everyone"],
        ["User guide / How it works", "This guide; the rules, each against Access and Sage X3.", "Everyone"]],
        [3.4, 10.6, 3.2])
    rich(doc, [("Material status: ", True), ("GREEN", True), (" all material in stock · ", False), ("AMBER", True),
               (" covered by a PO or works order due in time · ", False), ("RED", True),
               (" short with nothing due in time, or no BOM.", False)], after=8)
    shot(doc, shots, "02_live_orders_grid_and_bom.png", "Live Orders: click a works order for its exploded BOM - stock, "
                                                        "on PO and the next PO date, on WO")
    h(doc, "Add Production's notes (Comments, Prog, Tube req)", 2)
    steps(doc, ([("Press ", False), ("📂 Workbooks", True), (", find the newest workbook (marked ", False),
                   ("latest", True), (") and press ", False), ("Copy path", True), (".", False)],
                  [("In Excel: File → Open, paste the path, Open (or paste it into File Explorer).", False)],
                  [("Type in the ", False), ("yellow ✎ columns", True), (" on the Live Orders tab, and save.", False)],
                  [("The next Regenerate carries the notes to the new workbook by works-order number - nobody copies "
                    "them over on Monday.", False)]))
    rich(doc, [("Don't ", True), ("type notes in a downloaded copy (it doesn't go back to the folder), and don't rename "
               "the generated files: the notes are taken from the newest generated workbook in the folder.", False)],
         after=8)
    h(doc, "Look back: 📂 Workbooks", 2)
    p(doc, "Every spreadsheet in the folder - the generated ones and any saved there by hand. Sort newest or oldest "
           "first or by name; search; Preview any of them in the portal, tab by tab, without opening Excel; View in "
           "the dashboard to see an older run in all the views (press 'back to latest' to return); Download; Copy path.")
    shot(doc, shots, "03_live_orders_workbooks.png", "📂 Workbooks: the folder's spreadsheets, sorted by date, with a "
                                                     "preview of one")

    # ---------------------------------------------------------------- Estimate -> X3
    doc.add_page_break()
    h(doc, "2. Estimate → Sage X3")
    p(doc, "Turns a saved estimate into the three Sage X3 import files - the product (ZSDIITM), its bill of materials "
           "(YA00408BOM) and its route (ZSDIROU2) - and a write-up workbook showing every line of the estimate, where it "
           "lands in X3 and how each quantity and run time is worked out. Every line is checked against Sage X3's own "
           "product list and work centres first.")
    shot(doc, shots, "07_estimate_user_guide_and_upload.png", "Estimate → X3: the guide, the upload box and the earlier "
                                                              "runs")
    h(doc, "Steps", 2)
    steps(doc, ([("Drop the estimate", True), (" in the box (or click to choose it) - the .xls or .xlsx exactly as the "
                   "estimator saved it. The estimators' template and Dave's IMPORT layout are both read.", False)],
                  [("Options", True), (" - leave them unless you know otherwise: category FGML for a new part; sheet "
                   "steel CR4 unless the estimate says ZINTEC or Galvanised; part code only to override the estimate's "
                   "own (e.g. a test part).", False)],
                  [("Press ", False), ("Generate the X3 files", True), (" - a few seconds.", False)],
                  [("READY TO LOAD", True), (" (green): every line checked. ", False), ("NOT READY", True),
                   (" (red): the Checks tab lists each STOP with the estimate cell to fix - fix it in the estimate, "
                    "save, run it again.", False)],
                  [("Where the files go", True), (": a READY run is saved in ", False),
                   (r"K:\Operations\Reporting\SageEstimates", True), (", in its own folder named by part, date and time "
                   "(e.g. XX-0000001_2026-11-20_2015): the three .txt load files and the write-up. The page shows the "
                   "folder with Copy path; you can also download them there. A NOT READY run isn't saved.", False)],
                  [("Load in Sage X3", True), (": Usage → Imports, TEST (SDI Mig) first, in the order shown - product, "
                   "BOM, route. If the part already exists, its product line is rejected - expected; the BOM and route "
                   "load onto it. Then compare the part's BOM and route in X3 with the write-up.", False)]))
    shot(doc, shots, "08_estimate_ready.png", "READY TO LOAD: the files, the load order, and every estimate line "
                                              "against where it lands in X3")
    h(doc, "Common STOPs", 2)
    table(doc, ["The check says", "What to do"], [
        ["… not a product in X3", "Use the right code, or have the product created in X3 first."],
        ["work centre … is not an X3 work centre", "The estimate's department has no X3 work centre (e.g. OVEN): it needs "
                                                   "mapping before that operation can load."],
        ["no link quantity / no part code", "A quantity or code is missing on that estimate line."],
        ["Sheet … no X3 sheet", "No X3 sheet of that size, gauge and material: check the size, the gauge or the "
                                "material option."]], [6.5, 10.7])
    shot(doc, shots, "09_estimate_not_ready.png", "NOT READY: each STOP with the estimate cell to fix; the load files "
                                                  "are held back")
    p(doc, "Not carried into X3 (shown in the write-up): scrap %, and the estimate's costs - the standard-cost load is "
           "still to come. Every run is kept under Earlier runs.", italic=True, color=MUTED, size=9.5)

    h(doc, "Questions", 2)
    p(doc, "James Gray. The rules behind Live Orders are on its How it works tab.")
    doc.save(out)
    return out


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    print(build(sys.argv[1], sys.argv[2]))
