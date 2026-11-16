"""Draw numbered callouts on the screenshots (shots/ -> shots_marked/). Boxes are in screenshot pixels (1920 wide).
Each callout number matches a step in the guide."""
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
    "05_GESPTH_purchase_receipt_entry.png": [
        (1, (6, 180, 357, 440)),         # list of receipts on the left
        (2, (412, 922, 870, 992)),       # invoiced status / quantity
        (3, (1645, 650, 1850, 720)),     # receipt situation / enquiry
    ],
}


def font(size):
    for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"):
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def main():
    out = HERE / "shots_marked"
    out.mkdir(exist_ok=True)
    f = font(30)
    for name, marks in MARKS.items():
        im = Image.open(HERE / "shots" / name).convert("RGB")
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
