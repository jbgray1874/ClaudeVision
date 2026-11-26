"""How Live Orders works it out - the logic reverse-engineered from Access SupplyChain and Production's sheet, and
reconciled to Access on 16 Nov 2026 (reconcile_dave.py), now applied to live Sage X3 data. Written 20 Nov 2026.

One list, shown in two places so they can never disagree: the "How it works" tab of every workbook
(live_orders_xlsx.py) and the "How it works" view in the portal (the data file's "logic", live_orders_dashboard.html).
build_live_orders.py is the code that does it; x3_source.py turns X3's data into the same shape as the Access extract,
so the X3 board runs exactly the reconciled logic.

Each row: (what, the rule, how Access / Production's sheet did it, where it comes from in Sage X3, 16 Nov reconciliation)
"""

LIVE = ("Live, not a history report: every Regenerate reads Sage X3 at that moment - open works orders, stock, open "
        "sales and purchase order lines - and works the board out from scratch. Products, BOMs and routings are "
        "refreshed overnight. Each generation is saved as its own workbook (never overwritten) so you can look back; "
        "the portal always opens the newest.")

LOGIC = [
    ("Which works orders",
     "Every open, firm works order with something left to make - the same coverage as Access (open status, every "
     "order type). Closed works orders are left out even if short-closed, and so are planned / suggested ones (Access "
     "had none). Sub-assemblies (WO numbers with /) are their own rows, under their parent.",
     "Open works orders in Access; Production's sheet listed them by hand.",
     "Work order product lines (x3Manufacturing.workOrderProductLine): closed, planned and suggested left out.",
     "Part 102 / 102, quantity 102 / 102."),
    ("Balance",
     "Ordered (or amended) quantity minus the good quantity made.",
     "QTY - Booked in = Balance on Production's sheet.",
     "expectedQuantity - totalCompletedQuantity.",
     "98 / 102 (the 4 had been made since the sheet was saved). Works orders migrated from Access start at their "
     "remaining quantity, so their 'made' restarts at 0."),
    ("Due date and week",
     "The works order's scheduled end date. Rows are in due-date order with a break line each week; overdue is red.",
     "The WO scheduled date; the weekly break lines were typed.",
     "endDate on the work order line.",
     "76 / 102 (25 of the 26 differences were reschedules after the sheet was saved)."),
    ("Material status",
     "1) Each works order needs BOM quantity x balance of every component. 2) Stock is shared out to works orders in "
     "due-date order, earliest first. 3) A shortage is covered by open PO lines (earliest first), then by works orders "
     "for made components. GREEN = all in stock. AMBER = covered by a PO / WO due on or before the works order's due "
     "date, or a call-off material (sheet metal, powder, packing, pallets, wire, carriage). RED = short with nothing due "
     "in time, or no BOM.",
     "Typed by Production after checking stock and POs (Access holds no allocations).",
     "BOM lines (manufacturingBomLine), stock (status A), PO lines with quantity still to receive (not closed - as "
     "Access), expected receipt date, works orders.",
     "Listed beside Production's typed status for every works order (By works order tab); the rule and the call-off "
     "list are to agree with Production (LO-01). The reason (which material, short or to call off) is shown when you "
     "click the line, and on the Exploded BOMs tab - not as a column (25 Nov, Simon)."),
    ("Metal / Joinery / Acrylics",
     "From the work centres on the part's routing, shown as the letters M = Metal, J = Joinery, A = Acrylics.",
     "Y typed per shop.",
     "routingOperation.mainWorkCenter.",
     "63 / 102 - the sheet's Y's were Production's own judgement, the board uses the route."),
    ("Hours still to do",
     "Per work centre: run minutes per unit x balance / 60, plus the set-up if nothing has been made yet. Shown under "
     "Production's department names.",
     "Department hours per works order on Production's sheet.",
     "routingOperation setupTime / runTime (minutes, as loaded from the route file), per main work centre.",
     "297 of 334 work-centre lines agree where both have hours."),
    ("Work-centre load",
     "Those hours by the week each works order is due; overdue work counts in the current week.",
     "Totals per department under each weekly break line.",
     "As above.",
     "Follows the hours."),
    ("WO Suggestions",
     "Open sales-order lines for made parts (has a BOM or route) not covered by stock or works orders. Suggested start = "
     "due date - 14 days. Red = no BOM or no route. Lines due more than 60 days ago go to Checks for Customer Services.",
     "MRP report for WO suggestions (red = no BOM or route) - tab 2 of Production's sheet.",
     "Sales order lines with quantity still to deliver (salesOrderLine; closed lines left out - as Access), "
     "against works orders and stock.",
     "Same layout as Production's tab 2."),
    ("PO Suggestions",
     "Bought-in parts the open works orders are short of (every BOM level, as Shortages): to order = needed - stock - "
     "on open POs - on works orders. Needed by = the due date of the first works order that can't be covered (works "
     "orders in due order). Order by = needed by - the part's usual lead time (median days from order date to expected "
     "receipt on its X3 PO lines; 14 days if it has none). Last supplier / price: its most recent X3 PO line. "
     "Read-only: Purchasing raise the orders in X3.",
     "Purchasing checked Access and the sheet by hand.",
     "BOM lines, stock, PO lines open and closed (purchaseOrderLine: supplier, order date, expected receipt, gross "
     "price, currency, purchase unit), works orders.",
     "New (26 Nov) - to agree with Purchasing."),
    ("Late POs",
     "Open PO lines (quantity still to receive) past their expected receipt date, and those due in the next 7 days; "
     "the works orders waiting = the open works orders whose BOM (any level) uses the part.",
     "Purchasing checked by hand.",
     "PO lines (expectedReceiptDate, remaining quantity), BOM lines, works orders.",
     "New (26 Nov)."),
    ("Order lookup",
     "Every open sales-order line (quantity still to deliver), with the works orders made for it - same order and part, "
     "else the same order - their status and due date; flagged when a works order is due after the customer's date.",
     "Customer Services asked Production.",
     "Sales order lines (requestedDeliveryDate, customerOrderReference), works orders' salesOrder.",
     "New (26 Nov)."),
    ("Exploded BOM",
     "Every works order's BOM at every level (up to 8) x balance, against stock, on PO (and the next PO date), on WO, "
     "make / buy. Short bought-in parts in red. Click a part code to jump to it.",
     "BOM report - tab 3 of Production's sheet (one part at a time).",
     "BOM lines, stock, PO lines, works orders.",
     "-"),
    ("REV",
     "The product's version.",
     "Typed by Production (blank on 757 of 769 Access works orders).",
     "majorProductVersion on the work order line.",
     "Check against the GA drawing still to add (which drawing folder - open point)."),
    ("Production's notes",
     "Comments, Prog, Tube req, Material (Production's own material notes) and Notes are typed on the portal's Live "
     "Orders page - shared by everyone, with who and when - or in the newest workbook's yellow columns. Each "
     "generation carries them forward by works order (if a cell was changed in both, the later change wins), so "
     "nothing is copied over on Monday.",
     "Rachael copied the sheet into a new week by hand every Monday.",
     "Not in X3 - kept by the portal (per environment) and in each workbook in K:\\Operations\\Reporting\\LiveOrders.",
     "-"),
]
