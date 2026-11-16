"""Draw numbered callouts on the screenshots (shots/ -> shots_marked/). Boxes are in screenshot pixels (1920 wide).
Each callout number matches a step in the guide."""
import os
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
RED = (214, 40, 57)
TOP = 118          # browser tabs, address bar and bookmarks bar end here: the Sage X3 screen starts at the black header
MARKS = {
    "01_CONSCSF_delivery_line_list_selection.png": [
        (1, (40, 868, 495, 932)),        # start / end date
        (2, (804, 940, 1140, 978)),      # invoiced / not invoiced
        (3, (804, 588, 1356, 628)),      # subcontract / not invoiceable
        (4, (1420, 230, 1541, 285)),     # Search
        (5, (1645, 458, 1860, 548)),     # Global export
    ],
    "02_FUNGRHSDH1_shipments_by_period_selection.png": [
        (1, (229, 853, 565, 893)),       # invoiced / not invoiced
        (2, (229, 718, 1100, 758)),      # delivery types
        (3, (1166, 222, 1410, 277)),     # Memo / Recall
    ],
    "04_CONSCSP_order_lines_selection_menu.png": [
        (1, (160, 340, 370, 380)),       # Order lines in the menu
        (2, (40, 938, 495, 1002)),       # start / end date
        (3, (804, 660, 1095, 698)),      # closed / not closed
        (4, (1420, 230, 1541, 285)),     # Search
        (5, (1645, 458, 1860, 548)),     # Global export
    ],
    "11_CONSCSP_order_lines_selection.png": [
        (1, (40, 938, 495, 1002)),       # start / end date
        (2, (804, 662, 1095, 698)),      # closed / not closed
        (3, (1420, 230, 1541, 285)),     # Search
        (4, (1645, 458, 1860, 548)),     # Global export
    ],
    "20_CONSSMQ_shortage_selection.png": [
        (1, (40, 442, 200, 482)),        # site
        (2, (220, 442, 972, 482)),       # first / last product
        (3, (40, 518, 700, 558)),        # document type / document
        (4, (1420, 230, 1541, 285)),     # Search
        (5, (1640, 442, 1860, 532)),     # Excel export
    ],
    "21_purchasing_enquiries_orders_menu.png": [
        (1, (126, 586, 272, 736)),       # List of orders / Order lines / Subcontract lines / Orders per period
    ],
    "22_CONSCPO_purchase_order_enquiry_selection.png": [
        (1, (436, 516, 1004, 558)),      # starting / ending supplier
        (2, (706, 684, 1160, 724)),      # start / end date
        (3, (1420, 230, 1541, 285)),     # Search
        (4, (1645, 458, 1860, 548)),     # Excel export
    ],
    "24_APAR_enquiries_menu.png": [
        (1, (100, 566, 300, 682)),       # customer situation / customer aged balance
    ],
    "25_stock_enquiries_stock_menu.png": [
        (1, (128, 330, 352, 892)),       # Stock enquiries: by site / product / lots / detailed ...
        (2, (82, 894, 214, 926)),        # Transactions
    ],
    "26_CONSSCBB1_mrp_mps_results.png": [
        (1, (40, 436, 218, 476)),        # site
        (2, (40, 538, 404, 578)),        # product
        (3, (1420, 230, 1541, 285)),     # Search
        (4, (1640, 640, 1860, 728)),     # Excel export
    ],
    "28_CONSSMV_stock_transactions_selection.png": [
        (1, (40, 508, 200, 548)),        # site
        (2, (400, 508, 766, 548)),       # product (required)
        (3, (1420, 230, 1541, 285)),     # Search
        (4, (1640, 442, 1860, 532)),     # Excel export
    ],
    "29_stock_enquiries_transactions_menu.png": [
        (1, (128, 586, 292, 620)),       # Transactions by Date
        (2, (128, 826, 320, 860)),       # Stock valuation by period
        (3, (128, 546, 278, 580)),       # Stock Transactions
    ],
    "30_CONSSFC_stock_by_site_selection.png": [
        (1, (220, 508, 586, 548)),       # product (required)
        (2, (992, 508, 1266, 548)),      # quantity type
        (3, (1420, 230, 1541, 285)),     # Search
        (4, (1640, 562, 1860, 652)),     # Excel export
    ],
    "31_FUNAUTFAE_invoices_to_be_issued.png": [
        (1, (466, 410, 990, 452)),       # company / all sites
        (2, (230, 512, 448, 552)),       # shipments until
        (3, (230, 768, 442, 886)),       # generation type
        (4, (1256, 222, 1344, 278)),     # OK
    ],
    "32_financials_closing_processes_menu.png": [
        (1, (104, 618, 264, 650)),       # Invoices to be issued
        (2, (104, 538, 254, 570)),       # Invoice receivables
    ],
    "05_GESPTH_purchase_receipt_entry.png": [
        (1, (6, 180, 357, 440)),         # list of receipts on the left
        (2, (412, 922, 870, 992)),       # invoiced status / quantity
        (3, (1645, 650, 1850, 720)),     # receipt situation / enquiry
    ],
}


# Screenshots that show customer or supplier names are kept OUT of git: they live in the folder named by
# X3_PRIVATE_SHOTS (raw) and are marked into <that folder>/marked. The guides read them from there.
PRIVATE_MARKS = {
    "13_CONSCSP_order_lines_results.png": [
        (1, (1050, 428, 1550, 462)),     # result count and pages
        (2, (1645, 458, 1860, 548)),     # Excel export
    ],
    "14_CONSCSF_delivery_lines_not_invoiced_results.png": [
        (1, (804, 612, 1140, 642)),      # Invoiced unticked
        (2, (1185, 692, 1390, 722)),     # result count
    ],
    "15_CONSCPS_receipt_lines_selection.png": [
        (1, (1040, 540, 1496, 584)),     # start / end date
        (2, (40, 786, 372, 816)),        # invoiced / not invoiced
        (3, (1420, 230, 1541, 285)),     # Search
        (4, (1645, 458, 1860, 548)),     # Excel export
    ],
    "17_manufacturing_menu_enquiries.png": [
        (1, (100, 572, 236, 606)),       # Reorder Results
        (2, (100, 656, 214, 690)),       # List of WOs
    ],
    "18_stock_menu_enquiries.png": [
        (1, (100, 666, 300, 958)),       # Stock enquiries
    ],
    "19_purchasing_menu_ordering_orders.png": [
        (1, (100, 362, 268, 394)),       # Planning Workbench
    ],
    "27_GESBODP_boms_multilevel.png": [
        (1, (1436, 229, 1592, 287)),     # Multi-level
        (2, (8, 182, 632, 950)),         # list of BOMs
        (3, (694, 503, 1060, 542)),      # parent product
        (4, (694, 666, 1164, 708)),      # SDI drawing / revision number
    ],
    "16_purchasing_subcontract_menu.png": [
        (1, (206, 258, 458, 418)),       # Subcontract submenu
    ],
}


def font(size):
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def main():
    jobs = [(HERE / "shots", HERE / "shots_marked", MARKS)]
    priv = os.environ.get("X3_PRIVATE_SHOTS")
    if priv:
        jobs.append((Path(priv), Path(priv) / "marked", PRIVATE_MARKS))
    for src, out, marks_map in jobs:
        out.mkdir(exist_ok=True)
        mark_all(src, out, marks_map)


def mark_all(src, out, marks_map):
    f = font(30)
    for name, marks in marks_map.items():
        if not (src / name).exists():
            continue
        im = Image.open(src / name).convert("RGB")
        d = ImageDraw.Draw(im)
        for n, (x1, y1, x2, y2) in marks:
            d.rounded_rectangle((x1, y1, x2, y2), radius=8, outline=RED, width=5)
            r = 24
            cy = (y1 + y2) // 2
            cx = x1 - r - 8
            if cx - r < 0:                      # no room on the left: put it on the right
                cx = x2 + r + 8
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=RED, outline="white", width=3)
            d.text((cx, cy), str(n), font=f, fill="white", anchor="mm")
        im = im.crop((5, TOP, im.width - 5, im.height - 4))
        im.save(out / name, optimize=True)
        print("marked", name)


if __name__ == "__main__":
    main()
