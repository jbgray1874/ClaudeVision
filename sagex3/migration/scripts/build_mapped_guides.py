"""One mapped guide per template, in the same shape as the earlier MAPPED workbooks.

Each file keeps the original 'Data with Headings' and 'Guide' sheets exactly as Marc and
Ethan issued them, and adds:
    Mapping   every field in template order - source, rule, status
    Notes     the numbers, the control totals and what is still open for that template
"""
import os

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

BASE = "/tmp/claude-0/-home-user-ClaudeVision/e9ffe9d9-c7dd-5e34-8a16-6cb3c65dadea/scratchpad"
SRC = f"{BASE}/uploads_tmpl5"
OUT = os.environ.get("OUT_DIR", f"{BASE}/out_mapped")

HF = Font(name="Arial", bold=True, size=10, color="FFFFFF")
BF = Font(name="Arial", size=10)
BOLD = Font(name="Arial", bold=True, size=10)
TF = Font(name="Arial", bold=True, size=13)
HFILL = PatternFill("solid", fgColor="44546A")
OPEN_ = PatternFill("solid", fgColor="FFF2CC")
HARD = PatternFill("solid", fgColor="E2EFDA")
DONE = PatternFill("solid", fgColor="DEEBF7")
THIN = Border(*[Side(style="thin", color="BFBFBF")] * 4)

UAT, GOLIVE = "20261031", "20270103"
CLEANSE = ("cleansed to the Sage code: uppercase, no spaces, no ampersands, no brackets, "
           "full stops to hyphens - done inside the view")
ACCT = f'"{UAT}" for UAT, "{GOLIVE}" for go-live. One literal, the same in all five views'
SAGECODE = ("the Sage code, via migration.XREF_SAGE_BPC / XREF_SAGE_BPS. That cross-reference is "
            "built by xref_sage_codes.sql and places 623 of 623 suppliers and 215 of 217 customers. "
            "The Access code is kept beside it as a REF_ column so any row can be traced back")

HEADERS = ["#", "Sage field", "X3 column", "Template example", "Guide note",
           "Access source", "Rule in vw_..._V2", "Status"]
WIDTHS = [5, 26, 15, 24, 36, 34, 60, 18]

SOH = [
 ("Sales Site", "SALFCY", "S01A", "Sage X3 site that entered the order", "-", '"S01A"', "Hardcoded"),
 ("Order Type", "SOHTYP", "SON", "Hardcoded", "-", '"SON"', "Hardcoded"),
 ("Order no", "SOHNUM", "", "Leave Blank", "-", "Blank - X3 numbers it", "Hardcoded"),
 ("Sold-to", "BPCORD", "GB001", "Customer Code from Sage X3", "ASC_COR_TBL.COR_CUSTOMER_CODE",
  "Emitted as " + SAGECODE, "Needs the cross-reference"),
 ("Order Date", "ORDDAT", "20251021", "Date order was entered into the system",
  "COR_ORDER_DATE", "CONVERT style 112, YYYYMMDD", "Done"),
 ("Req Delivery Date", "DEMDLVDAT", "20251021", "Date the customer requires the order",
  "COR_CUSTOMER_DUE", "Falls back to COR_EXPECTED_DATE then COR_ORDER_DATE where the date is "
  "empty or 1900", "Done"),
 ("Customer Order Reference", "CUSORDREF", "PO123456", "PO reference from the customer",
  "COR_CUSTOMER_ORDER", "As held, trimmed", "Done"),
 ("Shipping Site", "STOFCY", "S01A", "The Sage X3 site that is shipping the order", "-", '"S01A"', "Hardcoded"),
 ("Ship Date", "SHIDAT", "20251021", "The date the order needs to be shipped",
  "COR_EXPECTED_DATE", "Falls back to COR_CUSTOMER_DUE then COR_ORDER_DATE", "Done"),
 ("Carrier", "BPTNUM", "", "Courier code from Sage X3", "-",
  "Blank - agreed with Marc, no X3 carrier codes yet", "Agreed"),
 ("Invoice Element 1", "INVDTAAMT(0)", "15", "(no note given)", "-",
  "Marc: this is the carriage charge. Set to 0, because Access carries carriage as order lines (CARRIAGE, TES-DELIVERY, CARRIAGEIN), and those load as lines. Moving them here instead is a choice for the clean run", "Needs confirming"),
 ("Currency", "CUR", "GBP", "Currency of the order", "COR_CURRENCY",
  'Access holds sterling as "£". Anything that is not EUR or USD becomes "GBP"', "Done"),
 ("Header text", "*71", "", "(no note given)", "-", "Blank", "Hardcoded"),
 ("Dim Code", "DIE", "D02", "Ethan, 23 Oct: new in YA004SOHPJ, hardcoded to D02", "-", '"D02". X3 column '
  'name DIE taken from Ethan\'s "DIE and CCE errors" - to confirm', "Hardcoded"),
 ("Dimension", "CCE", "P00003", "Ethan, 23 Oct: new in YA004SOHPJ, hardcoded to P00003", "-", '"P00003". X3 '
  'column name CCE taken from Ethan\'s "DIE and CCE errors" - to confirm', "Hardcoded"),
 ("Line", "SOPLIN", "1000", "Line number, increment in 1000s to allow line insertion in future",
  "COR_LINE_NO", "ROW_NUMBER within each order x 1000, so the sequence is clean whatever "
  "Access held", "Done"),
 ("Product", "ITMREF", "P001", "Product code from Sage X3", "COR_PART_ONLY", "Code " + CLEANSE, "Done"),
 ("Description", "ITMDES", "Sold Product Bought In", "Description of line", "migration.vw_ITM.ITMDES1",
  "Taken from the item view so the order and the item master agree", "Done"),
 ("Sales Unit", "SAU", "UN", "Unit of measure being sold", "COR_UOM_ENTERED",
  "The order's own unit, falling back to the item's SAU then EA", "Done"),
 ("Quantity Ordered", "QTY", "1", "Quantity ordered of sales unit",
  "COR_QTY_ORDERED, COR_QTY_DELIVERED", "Ordered less delivered. The guide says ordered, but on "
  "a migration that re-raises work already shipped. Agreed with Marc", "Agreed"),
 ("Gross Price", "GROPRI", "12", "Unit price of line (line value calculated qty x price)",
  "COR_DISC_PRICE / COR_DISC_PRICE_PER",
  "The discounted price over its price-per, falling back to the gross price over its own. "
  "The old view used COR_PRICE_PER, which is the divisor, not a price", "Done"),
 ("Line text", "*91", "", "Line text comment that will print on each line", "-", "Blank", "Needs confirming"),
 ("REF_ORDER_NUMBER", "(not in the template)", "", "", "COR_OUR_NUMBER",
  "Carried so the build can group lines into orders, then dropped", "Reference only"),
 ("REF_ORDER_STATUS", "(not in the template)", "", "", "COR_ORDER_STATUS",
  "Blank, B or H. C is completed and excluded by the view", "Reference only"),
 ("REF_NO_PRICE", "(not in the template)", "", "", "-",
  "1 where the line has no price at all. 849 of 3,649 open lines", "Reference only"),
]

POH = [
 ("Purchasing Site", "POHFCY", "S01A", "Sage X3 site raising the order", "-", '"S01A"', "Hardcoded"),
 ("Order no", "POHNUM", "", "Leave Blank", "-", "Blank - X3 numbers it", "Hardcoded"),
 ("Order Date", "ORDDAT", "20251021", "Date order was entered into the system - YYYYMMDD",
  "POR_ORDER_DATE", "CONVERT style 112", "Done"),
 ("Supplier", "BPSNUM", "S001", "Supplier Code as per X3 data", "POR_SUP_CODE",
  "Mapped to " + SAGECODE, "Done"),
 ("Currency", "CUR", "GBP", "Currency of the order e.g GBP,USD", "POR_CURR_CODE",
  'Anything that is not EUR or USD becomes "GBP"', "Done"),
 ("Header text", "*71", "", "Text at header level that will print on the purchase order", "-",
  "Blank", "Hardcoded"),
 ("Line", "POPLIN", "1000", "Line number increment in 1000's to allow for line insertions",
  "POR_LINE_NO", "ROW_NUMBER within each order x 1000", "Done"),
 ("Product", "ITMREF", "P001", "Product Code as per X3 data", "POR_PART_ONLY", "Code " + CLEANSE, "Done"),
 ("Description", "ITMDES", "Sold Product Bought In", "Description of the product", "migration.vw_ITM.ITMDES1",
  "From the item view", "Done"),
 ("Receiving Site", "PRHFCY", "S01A", "Sage X3 site receiving the order", "-",
  '"S01A". The old view called this column PRFCY', "Hardcoded"),
 ("Order Unit", "UOM", "UN", "Purchase Unit of measure of the product", "POR_UOM",
  "The order's own unit, falling back to the item's PUU then EA", "Done"),
 ("Quantity Ordered", "QTYUOM", "1", "Quantity still outstanding on the order",
  "POR_QTY_ORDERED, POR_QTY_DELIVERED, POR_QTY_REJECTED",
  "Ordered less delivered less rejected. The old view left rejected quantity in", "Done"),
 ("Expected Receipt Date", "EXTRCPDAT", "20251023", "Date the order line is expected to be received",
  "POR_LATEST_DUE_DATE", "Falls back to POR_DUE_DATE then POR_ORDER_DATE", "Done"),
 ("Gross Price", "GROPRI", "5", "Price of the line in the Currency defined earlier",
  "POR_UOP_PRICE / POR_UOP_PRICE_PER, POR_FORN_PRICE",
  "The unit price over its price-per for sterling, the foreign price for EUR and USD so the "
  "price is in the order's own currency. The old view used POR_VAL, a line value", "Done"),
 ("Line text", "*91", "Please supply in agreed packaging", "Any added text for extra instruction",
  "-", "Blank", "Needs confirming"),
 ("REF_ORDER_NUMBER", "(not in the template)", "", "", "POR_NUMBER", "Grouping, then dropped", "Reference only"),
 ("REF_SUPPLIER_REF", "(not in the template)", "", "", "POR_SUP_REF", "The supplier's own reference", "Reference only"),
 ("REF_NO_PRICE", "(not in the template)", "", "", "-", "1 where no price. 23 of 802 open lines", "Reference only"),
]

SMR = [
 ("Document Type", "VCRTYP", "19", "Hardcoded", "-", '"19"', "Hardcoded"),
 ("Document", "VCRNUM", "", "Hardcoded", "-", "Blank", "Hardcoded"),
 ("Site", "STOFCY", "S01A", "(no note given)", "-",
  '"S01A". Which of the 11 Access warehouses map to sites and which to locations is still '
  "Marc's decision - REF_WAREHOUSE carries it. Marc: S01A is now the only site", "Agreed"),
 ("Posted Date", "IPTDAT", "20251021", "Hardcoded", "-",
  "The date the stock is loaded - today's date on the day of the load (28 Oct), set by STOCK_DATE "
  "in populate_guides.py on every run. Not the accounting date: the view's 20261031 is replaced", "Done"),
 ("Description", "VCRDES", "IMP1", "(no note given)", "-",
  "The product code (ITMREF) - the product key on each line (28 Oct). Was \"OPENING STOCK\"", "Done"),
 ("Movement code", "TRSCOD", "", "Hardcoded", "-", "Blank", "Hardcoded"),
 ("Document Line", "VCRLIN", "1", "(no note given)", "-",
  "ROW_NUMBER over part, warehouse and lot", "Done"),
 ("Product", "ITMREF", "P001", "(no note given)", "ASC_LOT_TBL.LOT_PART_ONLY", "Code " + CLEANSE, "Done"),
 ("Unit", "PCU", "UN", "(no note given)", "ASC_PMA_TBL.PMA_UOM", "Falls back to the item's STU then EA", "Done"),
 ("Quantity", "QTYPCU", "2", "(no note given)", "LOT_PHYSICAL", "As held", "Done"),
 ("Stock unit", "STU", "UN", "(no note given)", "ASC_PMA_TBL.PMA_UOM", "Same unit - Access holds one per part", "Done"),
 ("Quantity STK", "QTYSTU", "2", "(no note given)", "LOT_PHYSICAL",
  "Same figure. The old view called this column QTYSTS", "Done"),
 ("Unit Price", "PRI", "5.24", "(no note given)",
  "LOT_COST_EACH + LOT_LAB_COST_EACH + LOT_OHD_COST_EA + LOT_OTHER_COST_EA",
  "All four cost elements. Material alone is £3,997,506.56; with labour £4,011,655.63. "
  "The old view used standard cost, which would not tie", "Done"),
 ("Unit", "PCU (2)", "UN", "(no note given)", "ASC_PMA_TBL.PMA_UOM", "Repeat", "Done"),
 ("Quantity", "QTYPCU (2)", "2", "(no note given)", "LOT_PHYSICAL", "Repeat", "Done"),
 ("Supplier Lot", "BPSLOT", "AB2345", "(no note given)", "LOT_SUPP_REF",
  "5,137 of the 8,463 lots carry one. The old view left this blank", "Done"),
 ("Lot", "LOT", "", "Hardcoded", "-", "Blank", "Hardcoded"),
 ("Location", "LOC", "AA001", "(no note given)", "LOT_BIN_ONLY",
  "The real bin. 1,920 distinct values and they are free text - BDFL, YIREE, abg01, HARDX7. "
  "Either X3 gets those locations or stock lands in one location per site. Marc is sending the X3 location list for us to map to", "Waiting on Marc"),
 ("Status", "STA", "A", "(no note given)", "-",
  'LOT_STATUS is blank on every one of the 8,463 lots, so "A" is hardcoded', "Hardcoded"),
 ("REF_WAREHOUSE", "(not in the template)", "", "", "LOT_WH", "The 11 Access warehouses, exposed "
  "so the exclusion decision is taken in the open", "Reference only"),
 ("REF_LOT_VALUE", "(not in the template)", "", "", "-", "Quantity x full cost, for the control total", "Reference only"),
 ("REF_NO_BIN", "(not in the template)", "", "", "-", "1 where the lot has no bin. 2,325 of 8,463", "Reference only"),
]

BICX = [
 ("Invoice Type", "", "MINV", "MINV = Invoice; MCRN = Credit Note; MREC = Receipt; MJDT = Misc. Debit; MJCT = Misc. Credit",
  "SL_TRANSACTIONS.ST_TRANTYPE",
  "INV to MINV (822), PAY to MREC (16), CRN to MCRN (2), ADR to MJDT (2). The old view had no "
  "type column at all, so every credit would have loaded as an invoice", "Done"),
 ("Document", "", "OP/I000242B", "Current System Unique Reference; must be unique within file",
  "ST_HEADER_REF", "13 references repeat - BACS x10, FP x5. The second and later take a "
  "-2, -3 suffix, as Ethan's own examples do", "Done"),
 ("Customer", "", "GB001", "Sage X3 Customer Code", "ST_COPYCUST",
  "ST_COPYCUST is the customer: all 844 open items populated, all 844 join to SL_ACCOUNTS. "
  "Mapped to " + SAGECODE, "Done"),
 ("Site", "", "S01A", "Sage X3 Financial Site", "-", '"S01A"', "Hardcoded"),
 ("Accounting Date", "", "20251031", "Day prior to go-live date YYYYMMDD", "-",
  ACCT + ". The old view used the transaction's own date, so each item posted to its own period", "Done"),
 ("Currency", "", "GBP", "Transaction Currency ISO currency code", "ST_CURRENCYCODE",
  'Access holds sterling as "£" - 752 of the 844 items. Mapped to "GBP"', "Done"),
 ("GBP Amount", "", "150", "Transaction Amount - GBP", "ST_UNALLOCATED",
  "The outstanding amount, not the gross. Positive: the Invoice Type carries the sign, which "
  "is how the template's own examples read", "Done"),
 ("Transaction Amount", "", "150", "Transaction Amount - in Transaction Currency", "ST_CURR_UNAL",
  "Tested on the VALUE, not on null: Access writes zero in this column on sterling rows, so "
  "ISNULL would load 752 items at nil", "Done"),
 ("Source Date", "", "20251021", "Original Transaction Date", "ST_DATE", "Style 112", "Done"),
 ("Paying Customer", "", "GB001", "Sage X3 Customer Code", "ST_COPYCUST",
  "Same code - Access has no separate payer", "Needs confirming"),
 ("Due Date", "", "20251001", "Due Date of Transaction YYYYMMDD", "ST_DUEDATE",
  "Falls back to the transaction date where empty or 1900", "Done"),
 ("Payment Terms", "", "BAC_IMM", '"BAC_IMM"', "-", '"BAC_IMM"', "Hardcoded"),
 ("Source Document", "", "SO002356", "Supplementary Reference, e.g. Order No. of an Invoice",
  "ST_ORDER_NUMBER", "As held, e.g. 10016085", "Done"),
 ("Comments", "", "Migrated Invoice Comment", "Header Comments 30 chars", "ST_DESCRIPTION",
  'Trimmed to 30, e.g. "Sales Invoice Posting"', "Done"),
 ("Comments", "", "Header Comments 2", "Header Comments 30 chars", "-", "Blank", "Hardcoded"),
 ("Comments", "", "Header Comments 2", "Header Comments 30 chars", "-", "Blank", "Hardcoded"),
 ("Line", "", "1", '"1"', "-", '"1"', "Hardcoded"),
 ("Site", "", "S01A", "Sage X3 Financial Site", "-", '"S01A"', "Hardcoded"),
 ("Plan code", "", "18L", '"18L"', "-", '"18L"', "Hardcoded"),
 ("General accounts", "", "999100", '"999100"', "-", '"999100"', "Hardcoded"),
 ("Distribution", "", "", "<blank>", "-", "Blank", "Hardcoded"),
 ("Comment", "", "Line Comment XXXXXXXXXXXXXXXXY", "Line Comment 30 chars", "ST_DESCRIPTION",
  "Same as the header comment", "Done"),
 ("Transaction Amount", "", "150", "Transaction Amount - in Transaction Currency", "ST_CURR_UNAL",
  "Same figure as the header, so the two tie", "Done"),
 ("REF_ARCHIVED", "(not in the template)", "", "", "ST_ARCHIVE_FLAG",
  "The old view excluded archived rows, which dropped 126 open items carrying real money. "
  "Exposed instead so finance decides", "Reference only"),
 ("REF_ACCESS_TYPE", "(not in the template)", "", "", "ST_TRANTYPE", "The Access type, for checking", "Reference only"),
 ("REF_TRAN_DATE", "(not in the template)", "", "", "ST_DATE", "For ageing before the load", "Reference only"),
]

BISX = [
 ("Invoice Type", "", "MINV", "MINV = Invoice; MCRN = Credit Note; MPAY = Payment; MJDT; MJCT",
  "PL_TRANSACTIONS.PT_TRANTYPE", "INV to MINV (2,220), PAY to MPAY (40), CRN to MCRN (3), "
  "ADR to MJDT (1)", "Done"),
 ("Document", "", "PIN001B", "Current System Unique Reference; must be unique within file",
  "PT_HEADER_REF", "22 references repeat - DD x16, FP x3 and others. Suffixed -2, -3", "Done"),
 ("Supplier", "", "S001", "Sage X3 Supplier Code", "PT_COPYSUPP",
  "PT_COPYSUPP is the supplier: all 2,266 open items populated, all join to PL_ACCOUNTS, "
  "266 suppliers owed money. Mapped to " + SAGECODE, "Done"),
 ("Site", "", "S01A", "Sage X3 Financial Site", "-", '"S01A"', "Hardcoded"),
 ("Accounting Date", "", "20251031", "Day prior to go-live date YYYYMMDD", "-", ACCT, "Done"),
 ("Currency", "", "GBP", "Transaction Currency ISO currency code", "PT_CURRENCYCODE",
  "2,197 sterling, 53 USD, 14 EUR", "Done"),
 ("CURLED", "CURLED", "GBP", "(no note given - the guide skips this column)", "-",
  '"GBP" - confirmed by Marc as the ledger currency', "Agreed"),
 ("GBP Amount", "", "1", "Transaction Amount - GBP", "PT_UNALLOCATED",
  "The outstanding amount. £6,901,039.43 across 2,266 items", "Done"),
 ("Transaction Amount", "", "1", "Transaction Amount - in Transaction Currency", "PT_CURR_UNAL",
  "THE fix: the old view used ISNULL, which never fires because Access writes zero rather than "
  "null on sterling rows. 2,197 items - 97% of the file - would have loaded at 0.00", "Done"),
 ("Source Date", "", "20250901", "Original Transaction Date", "PT_DATE", "Style 112", "Done"),
 ("Paying Supplier", "", "S001", "Sage X3 Supplier Code", "PT_COPYSUPP", "Same code", "Done"),
 ("Due Date", "", "20250930", "Due Date of Transaction YYYYMMDD", "PT_DUEDATE",
  "Falls back to the transaction date", "Done"),
 ("Payment Terms", "", "BAC_IMM", '"BAC_IMM" for domestic; "TFR_IMM" for non domestic',
  "PL_ACCOUNTS.SU_COUNTRY_CODE",
  "By the supplier's country, as the guide says, with currency only as the fallback where the "
  "country is blank. The old view decided on currency alone, so a UK supplier invoicing in "
  "euros got the wrong terms", "Done"),
 ("Source Document", "", "IN97967078", "Supplementary Reference, e.g. Supplier Invoice Number",
  "PT_HEADER_REF2, PT_ORDER_NUMBER", "The supplier's own reference, falling back to the order "
  "number then the document", "Done"),
 ("Comments", "", "Migrated Invoice XXXXXXXXXXXXY", "Header Comments 30 chars", "PT_DESCRIPTION",
  "The column is 30 characters anyway", "Done"),
 ("Comments", "", "Header Comments 2", "Header Comments 30 chars", "-", "Blank", "Hardcoded"),
 ("Comments", "", "Header Comments 3", "Header Comments 30 chars", "-", "Blank", "Hardcoded"),
 ("Line", "", "1", '"1"', "-", '"1"', "Hardcoded"),
 ("Site", "", "S01A", "Sage X3 Financial Site", "-", '"S01A"', "Hardcoded"),
 ("Plan code", "", "18L", '"18L"', "-", '"18L"', "Hardcoded"),
 ("General accounts", "", "999200", '"999200"', "-", '"999200"', "Hardcoded"),
 ("Distribution", "", "", "<blank>", "-", "Blank", "Hardcoded"),
 ("Comment", "", "Line Comment XXXXXXXXXXXXXXXXY", "Line Comment 30 chars", "PT_DESCRIPTION",
  "Same as the header comment", "Done"),
 ("Transaction Amount", "", "898.75", "Transaction Amount - in Transaction Currency", "PT_CURR_UNAL",
  "Same figure as the header", "Done"),
 ("REF_ARCHIVED", "(not in the template)", "", "", "PT_ARCHIVE_FLAG", "Exposed, not filtered out", "Reference only"),
 ("REF_ACCESS_TYPE", "(not in the template)", "", "", "PT_TRANTYPE", "The Access type, for checking", "Reference only"),
 ("REF_TRAN_DATE", "(not in the template)", "", "", "PT_DATE", "For ageing before the load", "Reference only"),
]

NOTES = {
 "YA004SOH": (
   "Open sales orders", "migration.vw_SOH_V2", "dbo.ASC_COR_TBL",
   [("Open order lines", "3,649"), ("Orders", "1,122"), ("Customers", "111"), ("Products", "1,361"),
    ("Lines with no price at all", "849 of 3,649")],
   [("Marc", "Order status. 2,297 lines are blank status, 1,347 are B and 8 are H. C is completed "
     "(25,975 lines, 31 outstanding) and the view excludes it. Is B live? Access also keeps "
     "OUTSTANDING_SALES_ORDER_TABLE with 2,402 rows, which is close to the blank-status count."),
    ("Marc", "Quantity. The guide says ordered; the view loads ordered less delivered, because the "
     "ordered figure would re-raise work already shipped."),
    ("Marc", "Gross price. The view loads the discounted price so the order value ties. The template "
     "has no discount column, so loading gross would overstate every discounted order."),
    ("Marc", "Delivery addresses. The template has no ship-to column, which is why the 50 Tesco store "
     "addresses did not reach order 10015257. The 1,399 addresses are in the customer file. A "
     "multi-drop order cannot be represented in this template as issued."),
    ("Ethan", "Invoice Element 1 (INVDTAAMT(0)) - carriage, or a discount? Set to 0 meanwhile."),
    ("Ethan", "With Order no blank, how does the import decide where one order ends and the next "
     "begins? The view carries REF_ORDER_NUMBER so the file can be ordered correctly, but two "
     "orders from one customer on one date with the same PO reference could merge.")]),
 "YA004POH": (
   "Open purchase orders", "migration.vw_POH_V2", "dbo.ASC_POR_TBL",
   [("Open order lines", "810"), ("Orders", "259"), ("Suppliers", "97"),
    ("Units outstanding", "237,714.50"), ("Lines with no price", "23 of 802")],
   [("-", "The cleanest of the five. Every open line has a blank status and blank line type, so "
     "there is no filter argument."),
    ("Ethan", "Line text - leave blank?")]),
 "YA004SMR": (
   "Opening stock", "migration.vw_SMR_V2", "dbo.ASC_LOT_TBL",
   [("Lots holding stock", "8,463"), ("Products", "4,876"), ("Warehouses", "11"),
    ("Material cost", "£3,997,506.56"), ("Labour", "£14,149.07"),
    ("Overhead and other", "£0.00"), ("Total stock value", "£4,011,655.63"),
    ("Lots with a bin", "6,138"), ("Distinct bins", "1,920"), ("Lots with a supplier lot", "5,137")],
   [("Marc", "The 11 warehouses. Which become X3 sites, which become locations within S01A, which "
     "are excluded. 88 holds £425,090.69 across 41 products and reads as a logical warehouse; "
     "99, PK and FX are tiny or nil."),
    ("Marc", "1,920 distinct bins, and they are free text - BDFL, YIREE, COP-WO, abg01, HARDX7. "
     "Either X3 gets those locations created or stock lands in one location per site."),
    ("Finance", "TEL-PARIS carries £200,000 in warehouse 01 and another £200,000 in OS - £400,000 "
     "on two lots of one unit each. That reads like a project or work in progress, not stock."),
    ("Finance", "Confirm £4,011,655.63 is the opening stock value to bring across.")]),
 "YA004BICX": (
   "Customer open items", "migration.vw_BICX_V2", "dbo.SL_TRANSACTIONS",
   [("Open items", "844"), ("Outstanding", "£9,733,641.86"), ("Invoices", "822"),
    ("Unallocated receipts", "16"), ("Credit notes", "2"), ("Adjustments", "2"),
    ("Sterling / euro", "752 / 90"), ("Duplicate references", "13"),
    ("Archived but still outstanding", "126"),
    ("Ageing", "466 under 30 days, 219 at 30-60, 71 at 60-90, 86 under a year, none over")],
   [("Marc", "255 of the 844 open items - £4,483,707.28, 46% of the ledger - belong to customers "
     "that are not in the customer load at all. Four accounts are 86% of it: Marks & Spencer plc "
     "£1,817,847.49, Boots UK £1,011,428.77 and the two Techtronic ELC accounts £1,044,697.25. "
     "The view inner-joins to the cross-reference, so those rows are not in the file - the check "
     "queries count them."),
    ("Finance", "126 open items are flagged archived. The old view dropped them silently. An archived "
     "transaction that still has money outstanding is still money outstanding - should they come?"),
    ("Ethan", "Paying Customer - Access has no separate payer, so the customer code is repeated. "
     "Head-office payers would need setting up in X3 by hand.")]),
 "YA004BISX": (
   "Supplier open items", "migration.vw_BISX_V2", "dbo.PL_TRANSACTIONS",
   [("Open items", "2,266"), ("Outstanding", "£6,901,039.43"), ("Invoices", "2,220"),
    ("Unallocated payments", "40"), ("Credit notes", "3"), ("Adjustments", "1"),
    ("Sterling / USD / EUR", "2,197 / 53 / 14"), ("Suppliers owed", "266"),
    ("Duplicate references", "22"),
    ("Ageing", "812 under 30 days, 762 at 30-60, 446 at 60-90, 243 under a year, 1 over")],
   [("Marc", "241 of the 2,266 open items - £811,218.05 - belong to suppliers that are not in the "
     "supplier load. Xiamen Yiree alone is £346,918.58, then Capital OnTap £107,160.23 and LKW "
     "Walter £105,456.96. The view inner-joins to the cross-reference, so those rows are not in "
     "the file; the check queries count them."),
    ("Ethan", "CURLED has no row in the guide. Set to GBP - is that the ledger currency?")]),
}

# Ethan, 23 Oct: YA004SOH becomes YA004SOHPJ - the same template with Dim Code and
# Dimension added between Header text (M) and Line (N).
OUTCODE = {"YA004SOH": "YA004SOHPJ"}
NEW_SOH_COLS = [("DIE", "Dim Code", "D02"), ("CCE", "Dimension", "P00003")]


def add_soh_columns(wb):
    ws = wb["Data with Headings"]
    ws.insert_cols(14, 2)
    for k, (code, head, val) in enumerate(NEW_SOH_COLS):
        ws.cell(1, 14 + k, code)
        ws.cell(2, 14 + k, head)
        for r in range(3, ws.max_row + 1):
            ws.cell(r, 14 + k, val)
    g = wb["Guide"]
    at = next(r for r in range(1, g.max_row + 1) if g.cell(r, 1).value == "Header text") + 1
    g.insert_rows(at, 2)
    for k, (code, head, val) in enumerate(NEW_SOH_COLS):
        for c, v in enumerate([head, val, val, val, f"Hardcoded to {val} (YA004SOHPJ)", "Hardcoded"], start=1):
            g.cell(at + k, c, v)


TABLES = {"YA004SOH": SOH, "YA004POH": POH, "YA004SMR": SMR, "YA004BICX": BICX, "YA004BISX": BISX}

os.makedirs(OUT, exist_ok=True)
for code, rows in TABLES.items():
    wb = load_workbook(f"{SRC}/{code}_guide.xlsx")
    title, view, src_table, counts, questions = NOTES[code]
    if code == "YA004SOH":
        add_soh_columns(wb)
    name = OUTCODE.get(code, code)

    ws = wb.create_sheet("Mapping", 0)
    ws.append([f"{name}  -  {title}"])
    ws["A1"].font = TF
    ws.append([f"Built by {view}, from {src_table}. Run xref_sage_codes.sql first, then "
               f"views_v2.sql. Customer, supplier and product codes are all Sage codes. "
               f"The REF_ columns are not part of the template - the file build uses them, "
               f"then drops them."])
    ws["A2"].font = BF
    ws["A2"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.append([])
    ws.append(HEADERS)
    for c in ws[4]:
        c.font, c.fill, c.border = HF, HFILL, THIN
        c.alignment = Alignment(wrap_text=True, vertical="top")
    for i, r in enumerate(rows, start=1):
        ws.append([i] + list(r))
    for row in ws.iter_rows(min_row=5):
        for c in row:
            c.font, c.border = BF, THIN
            c.alignment = Alignment(wrap_text=True, vertical="top")
        st = row[7].value
        if st in ("Done", "Agreed"):
            row[7].fill = DONE
        elif st == "Hardcoded":
            row[7].fill = HARD
        elif st in ("Needs confirming", "Needs the cross-reference", "Waiting on Marc"):
            row[7].fill = OPEN_
    for i, w in enumerate(WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A5"

    ws = wb.create_sheet("Notes", 1)
    ws.append([f"{name}  -  what the data says, and what is still open"])
    ws["A1"].font = TF
    ws.append([])
    ws.append(["The numbers"])
    ws[f"A{ws.max_row}"].font = BOLD
    for k, v in counts:
        ws.append([k, v])
    ws.append([])
    ws.append(["Still open"])
    ws[f"A{ws.max_row}"].font = BOLD
    ws.append(["For", "Question"])
    for c in ws[ws.max_row]:
        c.font, c.fill, c.border = HF, HFILL, THIN
    for who, q in questions:
        ws.append([who, q])
    for row in ws.iter_rows(min_row=2):
        for c in row:
            if c.font.size != 13 and not c.font.b:
                c.font = BF
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.column_dimensions["A"].width = 36
    ws.column_dimensions["B"].width = 96

    path = f"{OUT}/{name}_guide_MAPPED.xlsx"
    wb.save(path)
    done = sum(1 for r in rows if r[6] in ("Done", "Hardcoded", "Agreed"))
    open_ = sum(1 for r in rows if r[6] in ("Needs confirming", "Needs the cross-reference", "Waiting on Marc"))
    ref = sum(1 for r in rows if r[6] == "Reference only")
    print(f"{path}   {len(rows)} rows: {done} settled, {open_} open, {ref} reference")
