# SDI Displays – Access SupplyChain to Sage X3: migration runbook

Last updated 27 October 2026. Go-live 4 January 2027.

This is the record of how the migration files are built and every rule behind them, so each
rerun between now and go-live starts from fresh Access data and the agreed rules, never from
an old file. Read section 1 before every run.

- Source: Access SupplyChain, SQL Server database `SDILive` (working schema `migration`)
- Target: Sage X3, UAT at `sdi-displays-trn.uk.sagex3.com`
- Partner: Acuity24. Marc Davies (X3 consultant) and Ethan Davies (templates, import logs)
- SDI: James Gray (AI and Systems Controller) builds and loads the files

---

## 1. Golden rules – how not to reintroduce old data

1. **Extract everything fresh, on the same day, at a fixed as-at time.** Stock moved £21k in an
   hour while we worked. Products are selected by last activity against today's date (see 6.1),
   so an old product extract misses new products that are on live orders. Every file in a run
   comes from the same extract.
2. **The product file is the master.** Build it first. Routes, BOMs, costs, product-suppliers,
   works orders, stock and orders all take their product codes from it, never from their own
   source.
3. **One code rule, applied identically everywhere** (section 4). Never clean a code in one
   file and not another.
4. **Customer and supplier codes come from the cross-reference** (`migration.XREF_SAGE_BPC` /
   `XREF_SAGE_BPS`), never from the old `XREF_BPC` / `XREF_BPS` tables. Those hold a numbering
   that was never used (CUS1001, SUP1001).
5. **Never load a customer file with CUS101-style codes.** `YA004BPC_load4_customers-V9`
   went back to the old numbering. The codes in X3 are like TES101 and HAF500.
6. **Load from the mapped spreadsheets.** Each has a "Data with Headings" tab. The X3 file is
   the data rows only, semicolon separated, in the DOS code page (cp850), CRLF line ends.
7. **Hold back rather than drop.** Anything that would reject goes on a "Held back" tab with
   its reason, so nothing disappears silently.
8. **Check before handing over:** every code resolves (section 9), field counts match the
   template, no disallowed characters, keys unique.

---

## 2. Load order

| # | Template | What it is | Track |
|---|---|---|---|
| 1 | YA004BPS | Suppliers | 2 |
| 2 | YA004BPC | Customers | 2 |
| 3 | YA004BPCDL | Customer delivery addresses (after customers, never before) | 2 |
| 4 | ZSDIITM | Products | 2 |
| 5 | ZSDIITMSUP | Product-suppliers | 2 |
| 6 | YA00408BOM | Bills of materials | 2 |
| 7 | ZSDIROU2 | Routes | 2 |
| 8 | YITC | Product standard costs | 2 |
| 9 | YA004SMR | Opening stock | 1 |
| 10 | YA004POH | Open purchase orders | 1 |
| 11 | YA004SOHPJ | Open sales orders | 1 |
| 12 | YA004MFG | Open works orders (after BOMs and routes) | 1 |
| 13 | YA004BICX | Customer open items (sales ledger) | 1 |
| 14 | YA004BISX | Supplier open items (purchase ledger) | 1 |

Track 1 = opening transactions. Track 2 = master data. A failure in Track 1 is usually a
follow-through from Track 2: a missing product, customer or supplier.

---

## 3. Templates – exact layouts

All templates have a "Data with Headings" tab: X3 field codes in row 1, headings in row 2,
data from row 3, unless stated. Marc's macro skips the first two rows of "Data with Headings"
and its sheet names are hard-coded.

### Track 1

**YA004SMR – opening stock (19 columns)**
`VCRTYP, VCRNUM, STOFCY, IPTDAT, VCRDES, TRSCOD, VCRLIN, ITMREF, PCU, QTYPCU, STU, QTYSTU, PRI, PCU, QTYPCU, BPSLOT, LOT, LOC, STA`
- VCRTYP 19. STOFCY S01A. STA A.
- LOC = X3 location from Marc's list (section 7). LOT blank; the Access supplier lot goes in BPSLOT.
- Value at full lot cost, material plus labour, from the lot records, not the stock master.

**YA004SOHPJ – open sales orders (22 columns).** Replaced YA004SOH on 23 Oct.
`SALFCY, SOHTYP, SOHNUM, BPCORD, ORDDAT, DEMDLVDAT, CUSORDREF, STOFCY, SHIDAT, BPTNUM, INVDTAAMT(0), CUR, *71, DIE, CCE, SOPLIN, ITMREF, ITMDES, SAU, QTY, GROPRI, *91`
- SOHTYP SON. SOHNUM blank: X3 numbers the orders. BPTNUM (carrier) blank.
- INVDTAAMT(0) is the carriage charge, set to 0, because Access carries carriage as order
  lines (CARRIAGE, TES-DELIVERY, CARRIAGEIN).
- DIE = D02 and CCE = P00003 on every line. The two columns go between Header text (M) and
  Line (N). Ethan gave only the headings, "Dim Code" and "Dimension"; DIE and CCE are taken
  from his "DIE and CCE errors". To confirm.
- QTY = ordered less delivered. GROPRI = discounted price. Free-of-charge lines allowed.
- SOPLIN restarts at 1000 per order and steps by 1000.
- Header dates are the earliest on the order. Orders are arranged so no two with identical
  headers sit next to each other.

**YA004POH – open purchase orders (15 columns)**
`POHFCY, POHNUM, ORDDAT, BPSNUM, CUR, *71, POPLIN, ITMREF, ITMDES, PRHFCY, UOM, QTYUOM, EXTRCPDAT, GROPRI, *91`
- POHNUM blank. Lines restart at 1000 per order. Units EA.

**YA004BICX – customer open items (23 columns, one heading row only)**
Invoice Type, Document, Customer, Site, Accounting Date, Currency, GBP Amount, Transaction
Amount, Source Date, Paying Customer, Due Date, Payment Terms, Source Document, three
comments, Line, Site, Plan code, General accounts, Distribution, Comment, Transaction Amount.
- MINV / MCRN / MREC / MJDT / MJCT. General account 999100. Plan code 18L.
- Amounts are the outstanding balance, positive; the document type carries the sign.

**YA004BISX – supplier open items (24 columns, one heading row only)**
As BICX with **CURLED** in column 7, GBP. General account 999200.
- CURLED is in Ethan's template and Marc confirmed it as the ledger currency. James removed it
  once before because X3 did not recognise it. Keep it unless the load breaks; a 23-column
  version without it can be produced.
- **Load BICX and BISX from the file, not the macro.** They have one heading row and the
  macro skips two, so it would drop the first item.

### Track 2

**YA004BPS – suppliers (33 columns).** Only the first 14 codes of the template were recorded:
`BSGCOD, BPSNUM, BPSNAM, CRY, CUR, CRN, EECNUM, VACBPR, PTE, ACCCOD, BPAADD, BPADES, BPAADDLIG(0), BPAADDLIG(1)`
- Then, from the data: address line 3, county, (blank), postal code (R), country, telephone,
  telephone 2, website, email, nine blanks.
- Column AG = BPAADDFLG = 2 for every supplier (one address each).

**YA004BPC – customers (34 columns).** First 14 codes recorded:
`BCGCOD, BPCNUM, BPRNAM, BPRNAM(1), BPRSHO, BPAINV, BPAPYR, BPAADD, BPDADD, CUR, CRN, NAF, EECNUM, BPCINV`
- Then: VACBPR (O), PTE, ACCCOD, **R = address code**, BPADES, three address lines, postal
  code, county, country, two phones, two emails, three blanks, **AG = BPAADDFLG**, town.
- AG = 2 where column R is 001, otherwise 1 (Ethan).
- *Keep a copy of the original BPC and BPS template workbooks with this file. They were lost
  once.*

**YA004BPCDL – delivery addresses (3 columns, tab "Data with headings")**
`BPCNUM, BPAADD, BPDNAM`
- One row per customer address. BPDNAM = recognisable name, 30 characters.
- Access names every address after the company (all 1,399 Tesco addresses are "TESCO STORES
  LIMITED"). So for customers with several addresses the name is built as company word +
  address line 1 + postcode, e.g. `TESCO PITTODRIE EXPRE AB24 3DF`.

**ZSDIITM – products (three heading rows: table, code, heading; data from row 4)**
`TCLCOD, ITMREF, ITMDES1, ITMDES2, ITMDES3, STU, PUU, PUUSTUCOE, SAU, SAUSTUCOE, WEU, ITMWEI, BASPRI` (13 named, 18 fields in the file)
- Categories: FGML = sold, manufactured. FGSL = sold, bought in. PHANT = sub-assembly. RAWML =
  raw material, bought in.
- Units EA everywhere, conversions 1, weight unit KG. ZSDIITM is still the product template;
  YA004ITM is a different layout (statistical groups, expiry, serial, tax level GSR) and
  hasn't been confirmed as a replacement.

**ZSDIITMSUP – product-suppliers (3 columns, tab "Template")**
`ITMREF, BPSNUM, ITMREFBPS` – ITMREFBPS = the product code again.
- No priority column, so only each product's main supplier is loaded (section 6.4).

**YA00408BOM – bills of materials (11 columns)**
`ITMREF, BOMALT, USESTA, BOHSTRDAT, BOHENDDAT, BASQTY, QTYCOD, BOMSEQ, CPNITMREF, CPNTYP, LIKQTY`
(Parent Product, BOM Code, Use Status, Valid from, Valid to, Base Quantity, Management Unit,
Sequence, Component, Component Type, Link Quantity)
- BOMALT 10. BOMs only on FGML and PHANT. Parent, alternative and sequence must be unique.

**ZSDIROU2 – routes (tab "ZSDROU2", three heading rows, data from row 4)**
`ITMREF, ROUALT, FCY, USESTA, TIMUOMCOD, WORTYP, OPENUM, WST, ROODES, SETTIM, OPETIM`
- ROUALT 10. FCY S01A. USESTA 1 (the guide's note says "Hardcode to 10" but the example and
  every load use 1; asked Ethan). TIMUOMCOD 2 (minutes). WORTYP 4.
- OPENUM 5, 10, 15... per product. WST = an X3 work centre (section 8).
- SETTIM and OPETIM in minutes; run time per unit.
- The guide says ROODES should include the sub-assembly code where applicable. Access has no
  operation-to-sub-assembly link (asked Ethan).
- Routes only on FGML and PHANT.

**YITC – product standard costs (tab "YITC", 12 columns)**
`Line Indicator, STOFCY, ITMREF, CSTTYP, ITCSEQ, ITCDAT, ITCSTRDAT, ITCENDDAT, FIYNUM, MATCST, CLCQTY, MATLEVCST`
- Values: `I; S01A; product; 1; 1; 20260101; 20260101; 20261231; 3; cost; 100; cost`.
- **CSTTYP is 1 and the whole cost is in MATCST**, which is Ethan's "all costing under
  material". The 3 is FIYNUM, the fiscal year, not a cost type. One cost per product.

**YA004MFG – works orders (11 columns, tab "Data With Headings" with a capital W)**
`MFGFCY, BOMALT, ITMREF, STRDAT, ENDDAT, EXTQTY, MFGNUM, *1, *2, *3, *4`
- S01A; 10; product; start; end; quantity still to make; blank; product (routing); 10; C; 1.
- Ethan's example rows are format examples only. They don't match live Access orders.

---

## 4. Code rules

### 4.1 Product codes (V7 rule, used in every file)
1. Trim, then upper case.
2. Remove spaces, `&`, `(`, `)` and CHAR(160) (non-breaking space). Full stop becomes `-`.
   That was the original rule.
3. `/` and `_` become `-`. Every other symbol is removed: `% ? ° + ' @ : "` and anything else.
   Ethan's notes found `%` and `?` causing missing products.
   - If `/` to `-` would make a code the same as an existing one, drop the slash instead.
     (`ELEC/1M/90CM` and `ELEC-1M/90CM` exist side by side.)
   - Don't strip trailing hyphens: `CRL02-THESAINT-` and `CRL02-THESAINT` are both real codes.
4. Result: letters, digits and hyphens only.

In V7, 451 codes changed: 160 had a symbol and 291 were only mixed case. The full list of old
and new codes is in `V7_fix_report.xlsx`.

**Known problem: 33 codes belong to two different products.** The original clean-up merged
distinct Access codes, e.g. `BOT-AIRFREIGHT`, `SUBMETAL0011`, `JRL01-WALLBAY`. X3 keeps one
product per code, so one row loads (the manufactured version where the code has a BOM) and the
other is held back. **SDI to decide which product keeps each code.**

### 4.2 Customer and supplier codes
- Built by `xref_sage_codes.sql` (v3): Access account to Sage code by name.
  1. Exact name.
  2. Then both sides cut to 35 characters, with `& ( ) ' . ,` and spaces removed. The load
     files cut the names to 35 first, then removed those characters.
  3. Then manual pairs: KVT01 to KOV500 (Kovotvar), HCL02 to HOT100 (the load file misspells
     Hotel Chocolat).
- Result: 623 of 623 suppliers and 217 of 217 customers.
- The supplier and customer names aren't kept in git. `scripts/make_xref_inserts.py` rebuilds
  the full SQL from the **loaded** V4 supplier and V7 customer files. Don't use the V8 files:
  V8 rewrote `&` as AND, which breaks the name match.

---

## 5. Ethan's character rule (Import Notes, 23 Oct)

X3 allows letters, numbers, `-`, `_`, `.` (and spaces in text). Applied to every text field:
codes, descriptions, names, addresses, operation descriptions, comments.

| Character | Becomes |
|---|---|
| `&` | `AND` (with spaces) |
| `/` | `-` |
| `£` stuck to a word and followed by s (`Dowel£s`) | removed: an apostrophe Access lost (`Dowels`) |
| `£` otherwise | `GBP` |
| `°` | ` deg` |
| `Ø` | `DIA` |
| `½` / `¼` | `1-2` / `1-4` |
| accented letters | the plain letter (`José` → `Jose`) |
| en or em dash | `-` |
| ` ? ` between words | ` - ` (a dash Access lost) |
| anything else | removed |

- Nothing may grow past its field length; cut at the field's length.
- **References** (BICX/BISX document numbers, source documents) also lose their spaces.
  **Supplier lots** (SMR BPSLOT, LOT) get hyphens for spaces: `5019032 04.12` →
  `5019032-04.12`. The **customer PO** (CUSORDREF) keeps its spaces.
- **Emails, phone numbers and websites are left alone.** They need `@ + ( ) /`.
- Made-unique rule: if cleaning makes two document references the same, the second gets
  `-2`, `-3`... (first 18 characters + suffix).

---

## 6. Data rules by area

### 6.1 Products
- Selected by `migration.vw_DQ_ITM`: GOOD, INCOMPLETE, REVIEW, OLD or EXCLUDE, by last
  activity against GETDATE(). A product created after the extract, or with no activity yet, is
  graded OLD and dropped. **Extract on load day.**
- 137 in-use products (GOOD or INCOMPLETE, on orders or in stock) were missing from the first
  load and have been added since V6 (`items_to_append.sql`).
- Descriptions: Access STKNAME is often blank or repeats the code; the real text is in
  ITMDES3 / PMA_DESC_3. A blank first description takes description 3, then 2, then the code.

### 6.2 BOMs
- 33,596 BOM lines are held back because a parent or component is not a product in the load:
  14,304 products, mostly old. **SDI decision:** bring them into the product file, or drop
  the lines.
- 92 BOMs load with one or more components missing (215 lines). They're listed on the BOM
  spreadsheet's "Missing components" tab.
- BOMs on bought-in FGSL products are held back. X3 builds manufactured products only.

### 6.3 Routes
- Routes on RAWML or FGSL products are held back (71 lines, 36 products).
- Work centres: section 8.

### 6.4 Product-suppliers
- Access holds no supplier against the part: STK_STOCK_2.STK_SUPPLIER1–10 are empty.
- From purchase order history in ASC_POR_TBL, which starts on 1 September 2022. Each
  product's suppliers are ranked by most recent order. Priority 1 loads; the 3,150
  alternatives are held until Ethan adds a priority column (PIO).
- 2,377 bought-in products haven't been bought since September 2022, so they have no
  supplier.
- 110 Access suppliers (1,770 products) have no Sage supplier code. MPR01 alone is 940
  products.

### 6.5 Suppliers and customers
- **Tax rules (VACBPR).** X3's table: DOM, FRDOM, FRVAT, FRZER, PLDKR, PLOEU, PLOKR, ROWC,
  ROWS, XVRS. **There is no EU rule.** For UAT, EU customers are ROW / ROWC (as UNI100, which
  loaded) and EU suppliers are ROWS. **Finance to confirm before go-live.**
- **VAT numbers (EECNUM).** Format: GB + 9 digits (or 12 for branch traders), no spaces. An
  EU number has its 2-letter country prefix.
  - The 180 suppliers rejected in UAT had dummy numbers: two real Polish numbers copied
    across 117 suppliers, TEMPJAF placeholders, and GB numbers on overseas companies.
  - Dummies are blanked, because UK suppliers load with a blank.
  - Access holds real VAT numbers for only 78 of 1,259 suppliers (PL_ACCOUNTS.SU_VAT_REG_NO).
  - About 427 supplier GB numbers are fabricated: they run in sequence and only 28 of 441
    pass the HMRC check digit. They load, but **finance must replace them**.
  - ROL100 had an 8-digit number, now blanked.
- Customer TEC100: postcodes moved out of the address lines (POSCOD error).
- A semicolon between two emails split two customer rows. The first email was kept.

### 6.6 Sales orders
- Ship (SHIDAT) and requested delivery (DEMDLVDAT) dates before 2025 move to the accounting
  date. 2024 dates were rejected.
- A ship date before its order date is an Access typo (e.g. ordered 19 Aug 2026, ship 20 Jun
  2025). It takes the requested delivery date.
- Order dates are never changed.
- Credits sitting on orders (negative prices, £93,241.98 in the 22 Oct extract, largest an
  M&S monthly credit of £75,023.49) are held back. They need raising as credit notes.
- Multi-drop orders: Access has no delivery address on the order or the line, and the store
  allocation isn't recorded on the order. Still to find.

### 6.7 Works orders (ASC_WOR_TBL)
- Open = WOR_STATUS blank (744 of 55,657). C = complete.
- WOR_ORDER_TYPE: WS = standard. WP = prototype (placeholder products such as PROTOS and
  M&S-PROTOTYPE, held back). WR = one row.
- Quantity = WOR_ORIG_QTY − WOR_GOOD_QTY. WOR_AMD_QTY has never been used (27,356 completed
  orders checked).
- Start = WOR_CREATED_DATE (WOR_FIRST_DATE is never set). End = WOR_DATE_SCHED, never before
  the start.
- 453 of 638 are child orders (e.g. 70021093/01 under 70021093). Asked Ethan whether X3
  creates them from the parent's BOM.
- Open questions to Ethan: order number, quantity meaning, work in progress (47 part-made,
  £292,085.66 booked), past dates, prototypes.

### 6.8 Ledgers
- Customer items: SL_TRANSACTIONS, customer = ST_COPYCUST. Supplier items: PL_TRANSACTIONS,
  supplier = PT_COPYSUPP.
- Outstanding balance, not original value. Sterling is held as "£" in Access and becomes GBP.
- Repeated references get a suffix. Archived-but-outstanding items are a finance question.
- Missing accounts: Marks & Spencer plc, Boots UK and two Techtronic ELC accounts hold £3.87m.
  M&S plc to MAR100 for UAT is asked.

### 6.9 Dates and site
- Accounting date for UAT: 20261031.
- Go-live: the last day of the previous financial period (31 Dec 2026 if periods are calendar
  months; to confirm with Marc).
- S01A is the only site, for every site field.

---

## 7. Stock locations (Marc's X3 list, 22 Oct)

2,470 locations, each code unique across types:

| Type | Locations | Codes |
|---|---|---|
| BARD | 2,310 | AA01–LF33 |
| GDSIN | 144 | A01L–A36L, A01U–A36U, B001–B036, C001–C036 |
| DESP | 8 | T001–T008 |
| EXT | 7 | HARD, TPSM, SYST, ALDE, LOGX, PNCL, PION |
| WH01 | 1 | A001 |

Access bin to X3 location (`scripts/map_bins.py`):

| How | Rule | Bins |
|---|---|---|
| exact | The bin is already an X3 code | 437 |
| rule | Racking padded (AA2 → AA02); goods-in level (A10-UP → A10U); bays padded (B5 → B005) | 253 |
| suggested, for Marc to confirm | HARD*/HAR<n> → HARD; SYST; ALDER/ABG → ALDE; PION; LOG → LOGX; TPSM; TRAIL<n> → T00<n> | 27 |
| default | People's names, work areas, single-letter racking F1–O90 → A001 | 1,213 |

- Don't map NW H1–H90 to HARD: those are racking.
- **Go-live issue:** 3,986 of 6,303 lots (£2.47m of £3.44m) land in A001. Marc to create
  locations, or stock to be moved or counted before cut-over.

---

## 8. Work centres (X3 list, from James's screenshot)

| Code | Title | Code | Title |
|---|---|---|---|
| ALAB001 | Acrylics Assemble Pack | MLAB001 | Metal Assembly Packing |
| ALAB002 | Acrylics Drill | MLAB002 | Metal Dressing |
| ALAB003 | Acrylics Glue | MLAB003 | Metal Guillotine |
| ALAB004 | Acrylics Line Bend | MLAB004 | Metal Manual Labour |
| ALAB005 | Acrylics Manual Labour | MLAB005 | Metal Roll |
| ALAB006 | Acrylics Pin Router | MLAB006 | Metal Tube |
| AMAC001 | Acrylics CNC | MLAB007 | Metal Weld |
| AMAC002 | Acrylics Diamond Polish | MMAC001 | Metal Fold |
| AMAC003 | Acrylics Laser | MMAC002 | Metal Laser |
| JLAB001 | Joinery Benchwork | MMAC003 | Metal Powder Coat |
| JLAB002 | Joinery Assembly Pack | MMAC004 | Metal Punch |
| JLAB003 | Joinery Wetspray | MMAC005 | Metal Robomac |
| JMAC001 | Joinery CNC | MMAC006 | Metal Spot Weld |
| JMAC002 | Joinery Edge Banding | MMAC007 | Metal Tube Bend |
| JMAC003 | Joinery Machines General | STD | Standard Work Centre Labour |
| JMAC004 | Joinery Saw | LAB001, MAC001 | "To be removed" – never use |

- Group: A = Acrylics, J = Joinery, M = Metal. LAB = labour, MAC = machine. Site S01A.
- The mapping from the old Access work centres to these codes is in the routes file
  `ZSDIROU2_load1_routes-V4-cleansed` (for example Access LASM → MMAC002 Metal Laser, ROBO →
  MMAC005 Metal Robomac). **Keep that file. It is the only record of the mapping.**
- Check on every run: every WST is on this list, and the operation descriptions fit the title
  (laser on the laser centres, fold on Metal Fold, P-COAT on Metal Powder Coat).

---

## 9. Checks before handing files over

- [ ] Every file: field count equals the template's; headings equal the template.
- [ ] No disallowed characters in code and text fields (emails, phones and websites excepted).
- [ ] Product codes unique in the product file.
- [ ] Every ITMREF / CPNITMREF in BOMs, routes, costs, product-suppliers, works orders,
      stock, purchase orders and sales orders is in the product file, spelled exactly the same.
- [ ] BOM parents, routes and works orders only on FGML or PHANT.
- [ ] BOM parent + alternative + sequence unique. Route product + operation unique. One cost
      per product.
- [ ] Every customer and supplier on orders, open items, product-suppliers and delivery
      addresses is in the customer or supplier file.
- [ ] Tax rules only from X3's table. VAT numbers in a valid format or blank.
- [ ] All stock locations on Marc's list.
- [ ] Ledger totals reconcile to Access to the penny.

---

## 10. Access SupplyChain – where things are

There is no data dictionary for Access; everything below was found by querying the database.

| Data | Table, columns |
|---|---|
| Products | STK_STOCK (STKCODE, STKNAME, STK_DO_NOT_USE, STK_ARCHIVE); STK_STOCK_2 (STKCODE2, STK_SUPPLIER1–10, all empty); ASC_PMA_TBL (PMA_PART_ONLY, PMA_DESC_1/3, PMA_UOM, PMA_COST_MAT); migration.LOAD_ITM (ITMREF, ITMDES1–3) |
| Sales orders | ASC_COR_TBL (COR_OUR_NUMBER, COR_LINE_NUM, COR_PART_ONLY, COR_CUSTOMER_CODE, COR_ORDER_DATE, COR_CUSTOMER_DUE, COR_EXPECTED_DATE, COR_QTY_ORDERED / DELIVERED, COR_DISC_PRICE, COR_DISC_PRICE_PER, COR_ORIG_PRICE) |
| Purchase orders | ASC_POR_TBL (POR_NUMBER, POR_PART_ONLY, POR_SUP_CODE, POR_ORDER_DATE, POR_DUE_DATE, POR_QTY_ORDERED / DELIVERED, POR_FORN_PRICE, POR_UOP_PRICE, POR_UOP_PRICE_PER, POR_CURR_CODE, POR_UOM). History from 1 Sep 2022 |
| Stock lots | ASC_LOT_TBL (LOT_PART_ONLY, LOT_WH, LOT_NUM, LOT_SUB, bins). 11 warehouses |
| Works orders | ASC_WOR_TBL (WOR_ORDER, WOR_PARENT_ORDER, WOR_ITEM_ONLY, WOR_SALORD, WOR_ORIG_QTY, WOR_AMD_QTY, WOR_GOOD_QTY, WOR_CREATED_DATE, WOR_FIRST_DATE, WOR_DATE_SCHED, WOR_STATUS, WOR_ORDER_TYPE, WOR_BOOKED_MAT / LAB / SC_COST) |
| Customer ledger | SL_TRANSACTIONS (ST_COPYCUST = customer, ST_HEADER_REF); SL_ACCOUNTS (CUCODE, CUNAME, CU_COUNTRY_CODE, CU_TAX_CODE); SL_ADDRESSES (AD_ACC_CODE, AD_CODE ...) |
| Supplier ledger | PL_TRANSACTIONS (PT_COPYSUPP = supplier, PT_HEADER_REF); PL_ACCOUNTS (SUCODE, SUNAME, SU_VAT_REG_NO, SU_COUNTRY_CODE) |

---

## 11. Traps we hit – don't hit them again

- **Collation:** dbo tables are Latin1_General_BIN, the migration schema is CI_AS. Use
  `COLLATE DATABASE_DEFAULT` on every join, UNION and comparison across them.
- **Encoding:** Access exports are DOS cp850. 0x9C is £, 0xF8 is °, 0x9D is Ø. Read and write
  cp850, or 209 characters get mangled.
- **Excel damage:** codes read as dates (a midnight time stamped on), leading zeros lost.
  `standardise_v3.py` repairs them, but only onto a code that exists.
- **Semicolons inside values** (two emails) split a row and shift every later field.
- **Hidden characters:** CHAR(160) in codes; `?` where Access lost a character; `£s` where
  it lost an apostrophe.
- **The old migration views were wrong in ways that load silently:** the price-per divisor
  used as the price, a filter that dropped most live orders, the wrong site and date format,
  stock at standard cost from the stock master, and a currency rule that loaded 97% of
  supplier items at zero. Use views_v2.sql.
- **Names had been changed in the load files** (cut to 35 characters, & and brackets
  removed). The cross-reference must reproduce that.
- **Snapshot timing:** products graded by last activity against today's date.
- **Macro:** skips two heading rows. BICX and BISX have one.
- **Supplier rejections cascade:** a rejected supplier takes its product-supplier rows, open
  items and purchase orders with it. Load suppliers first and read the log.

---

## 12. How to rerun

1. **Fresh extract** (all on one day): views_v2.sql export grids; bins_and_delivery.sql grid
   1; product_suppliers_v3.sql grid 2; works_orders_extract.sql grid 2; plus the cleansed
   product, BOM, route and cost source files.
2. **Cross-reference:** rebuild `xref_sage_codes.sql` with `scripts/make_xref_inserts.py`
   (V4 suppliers, V7 customers) and run it, then `views_v2.sql`.
3. **Product side:** `standardise_v3.py` aligns routes, costs and BOMs to the product file
   and splits BOMs into loadable and held back. Then `build_v7_fixes.py` applies the code
   rule, supplier VAT, customer fixes, product-suppliers and delivery addresses.
4. **Master data:** `build_v8_track2.py` applies the character rule, duplicates, tax rules,
   bought-in BOM and route holds, and runs every check as an assertion.
5. **Opening transactions:** `map_bins.py`, then `build_mapped_guides.py` and
   `populate_guides.py` (the five guides, SOHPJ columns, dates, characters). Then
   `recode_ledgers_v7.py` for the clean-run product codes, and `build_mfg.py` for works orders.
6. **Spreadsheets:** `build_sheets.py` and `build_bp_sheets.py`. Each fills the template and
   reads every cell back against the load data.
7. Run the checklist in section 9.

The scripts use a working folder path at the top (`BASE`). Set it to wherever the extracts
are. They need Python 3 with openpyxl.

---

## 13. State at 27 October 2026

**Files for the clean run (mapped spreadsheets):**

| Spreadsheet | Rows |
|---|---|
| YA004BPS_suppliers_MAPPED | 623 |
| YA004BPC_customers_MAPPED | 2,268 (217 customers) |
| YA004BPCDL_delivery_addresses_MAPPED | 2,268 |
| ZSDIITM_products_MAPPED | 16,499 |
| ZSDIITMSUP_product_suppliers_MAPPED | 7,679 |
| YA00408BOM_boms_MAPPED | 30,131 |
| ZSDIROU2_routes_MAPPED | 31,255 |
| YITC_product_costs_MAPPED | 9,597 |
| YA004MFG_works_orders_MAPPED_clean_run | 638 |
| YA004SMR_guide_MAPPED_clean_run | 6,303 lots, £3,437,532.29 |
| YA004POH_guide_MAPPED_clean_run | 479 lines, 168 orders |
| YA004SOHPJ_guide_MAPPED_clean_run | 2,012 lines, 558 orders |
| YA004BICX_guide_MAPPED | 587 items, £5,249,157.38 |
| YA004BISX_guide_MAPPED | 2,027 items, £6,113,728.04 |

**Waiting on Marc:** whether October is open in UAT; the go-live date; carriage as lines or
invoice element; the ship-to field on SOHPJ; static data (999100, 999200, 18L, payment terms,
EUR/USD); M&S plc to MAR100; the 27 suggested bins, A001 and the racking; whether YA004ITM
replaces ZSDIITM.

**Waiting on Ethan:** DIE/CCE field names; CURLED in the X3 BISX definition; the X3 lot
export; the tax rules for UAT; BOMs and routes on bought-in products; route use status 1 or
10; the sub-assembly code in operation descriptions; a PIO column on ZSDIITMSUP; S500; the
works order questions; clean-run error logs.

**SDI decisions:** which product keeps each of the 33 shared codes; the 14,304 products BOMs
use but the load leaves out; real VAT numbers and EU tax rules (finance); credits on sales
orders; the multi-drop store allocation; the 2,377 bought-in products with no supplier; the
110 suppliers with no Sage code.

**Confidentiality:** when emailing suppliers, email yourself and put the recipients in BCC,
never CC (Claire Newall). Supplier and customer lists are not kept in git.

---

## 14. Fixes applied – both tracks, file by file

Counts are from the 21–27 October build. They will move with each fresh extract, but the
fixes themselves are what every rerun must repeat.

### Track 1 – opening transactions

| File | Fixes applied |
|---|---|
| **YA004SMR** opening stock | Mapped column for column to the template. Full lot cost (material + labour) from the lot records. Product codes as loaded. **Locations:** every Access bin mapped to Marc's list (437 exact, 253 by rule, 27 suggested, 1,213 to A001); 2,317 lots on a real location, 3,986 in A001. **Supplier lots:** 232 cleaned, spaces to hyphens. Held back 2,176 lots (£603,150.76) whose product is not in the product load. Clean run: 131 product codes changed to the V7 codes. |
| **YA004SOH → YA004SOHPJ** open sales orders | New template: Dim Code (DIE) = D02 and Dimension (CCE) = P00003 added between Header text and Line (22 columns). **Dates:** 293 lines with a ship or delivery date before 2025 moved to 20261031; 64 lines shipping before their order date given the requested delivery date; order dates unchanged; header dates the same on every line of an order (253 lines). **Text:** 145 cells cleaned to Ethan's rule; 878 blank descriptions filled from the product file. Lines renumbered from 1000 per order (271); 30 orders rearranged so identical headers are never adjacent. Units to EA, £ to GBP, outstanding quantity, discounted price. Held back 200 lines, including the credits on orders (£93,241.98). Clean run: 47 product codes changed. |
| **YA004POH** open purchase orders | Mapped to the template. **Text:** 36 descriptions cleaned (M&S-TOOLING → M AND S-TOOLING). 272 blank descriptions filled. Lines renumbered (33), 26 orders rearranged. Held back 193 lines. Clean run: 5 product codes changed. |
| **YA004BICX** customer open items | Mapped to the template. Outstanding balances, positive values, £ to GBP, Sage customer codes via the cross-reference, repeated references suffixed. Reconciles to Access to the penny. The character rule found nothing to change. |
| **YA004BISX** supplier open items | As BICX, plus CURLED = GBP. **References:** 84 document references with spaces or / cleaned (2026158/77 → 2026158-77), still unique. 3,134 text cells tidied (dashes, double spaces). A 23-column version without CURLED exists in case X3 rejects it. |
| **YA004MFG** works orders (new) | 638 of the 744 open Access works orders, one line each. Quantity = ordered less made. Start = created date. End = scheduled date (13 that ended before they started now end on the start date). Held back 106: 36 with nothing left to make, 42 with no BOM, 25 not a product (all 16 prototypes), 3 with no route. Clean run: 42 codes changed. |

### Track 2 – master data

| File | Fixes applied |
|---|---|
| **YA004BPS** suppliers | **VAT:** 186 dummy numbers blanked. These were two Polish numbers copied across 117 suppliers, TEMPJAF placeholders, and GB numbers on overseas companies; they were the cause of the 180 rejections in UAT. **Tax rule:** 28 suppliers on EU set to ROWS. **Text:** 211 name and address cells cleaned. Address flag 2 on all (already right). A reload file of the 179 rejected suppliers was made for UAT. |
| **YA004BPC** customers | **Tax rule:** the 10 EU customers (56 address rows) set to ROW / ROWC, as UNI100. **VAT:** ROL100's 8-digit number blanked. **TEC100:** postcodes moved out of the address lines (POSCOD error). **Two rows** split by a semicolon between emails put back to 34 fields. **Text:** 367 cells cleaned. Address flag (AG) checked: 001 = 2, others = 1. |
| **YA004BPCDL** delivery addresses (new) | 2,268 rows, one per customer address. For customers with several addresses the name is built from company + store line + postcode, within 30 characters. Built from the cleaned customer file. |
| **ZSDIITM** products | **Codes (V7):** 451 changed, 160 because of a symbol, 291 only to upper case, with no new duplicates. **Descriptions (V8):** 4,426 cells cleaned (Dowel£s → Dowels, £ per 1000 → GBP per 1000, 50° → 50 deg, & → AND). 68 blank descriptions filled. 137 missing in-use products added (V6). Held back 33 rows: a code on two products. |
| **ZSDIITMSUP** product-suppliers (new) | 7,679 products with their main supplier, from purchase history since Sept 2022. 3,150 alternatives held for a priority column. The cause of the blank suppliers in planning: 2,143 rows belonged to the 179 suppliers rejected on VAT. |
| **YA00408BOM** BOMs | **V6:** every code rewritten to the product file's spelling, Excel damage repaired, lines split into loadable and held back. 33,596 held: parent or component not in the product load (14,304 products). **V7:** 10 recovered by the code rule. **V8:** 11 lines on bought-in FGSL products held, 1 exact duplicate dropped, 1 clashing sequence moved on. 92 BOMs load with a component missing (listed). |
| **ZSDIROU2** routes | Work centres checked against X3's list: all 31 used are X3 codes, and each operation is on the right type of centre. 4,607 operation descriptions cleaned (P/C → P-C). 71 lines on 36 bought-in products held. Use status 1 kept (guide example; asked Ethan). |
| **YITC** product costs | Codes aligned to the product file and Excel damage repaired (V6). Confirmed all under material (cost type 1). 28 second costs held, for codes that were on two products. |

### Mapping and cross-reference work behind both tracks
- **Customer and supplier codes:** the cross-reference was rebuilt by name against the loaded
  files: 623/623 suppliers, 217/217 customers. The old CUS1001/SUP1001 numbering was dropped.
- **Product codes:** one rule everywhere (section 4.1). V6 aligned all product-side files to
  the product master; V7 removed every symbol; V8 cleaned descriptions.
- **Stock locations:** Access bins to Marc's 2,470 X3 locations (section 7).
- **Work centres:** checked against X3's 33 (section 8).
- **The old migration views** were rewritten (views_v2.sql): price-per divisor, order filter,
  site, date format, stock cost source, currency rule.

---

## 15. Templates and files received from Acuity

| Received | From, when | What it is | What we did with it |
|---|---|---|---|
| Five Track 1 guides: YA004SMR, SOH, POH, BICX, BISX | Ethan, 20 Oct zip | The opening transaction templates. Confirmed latest: BICX 10/06/2026, BISX 29/01/2026, others 23/10/2025 | Mapped column for column; field counts 19 / 20 (now 22) / 15 / 23 / 24 |
| Answers on the five files | Marc, 22 Oct | S01A only site; X3 bin codes to map; accounting date = last day of the previous period; positive values with currency in its own field; Invoice Element 1 = carriage; CURLED yes; carrier blank OK; X3 numbers orders; outstanding qty and discounted price correct; X3 calculates status; FOC lines OK; ship-to column can be added | Built into the files |
| **Location_List.xlsx** | Marc, 22 Oct | 2,470 X3 locations in 5 types (section 7) | Every Access bin mapped; stock file rebuilt |
| **Import_Error_Troubleshooting_Guide.xlsx** | Ethan, 20 Oct (sent again 27 Oct, identical) | The UAT errors: 180 supplier codes (VAT), 11 customer errors (10 VACBPR, 1 POSCOD) | Root causes found and fixed (dummy VAT numbers, no EU tax rule, TEC100 postcodes). S500 queried |
| **Import errors email** | Ethan, 20 Oct | Product, BOM, route and cost errors are missing products from stray symbols, mainly % and ?; clean every symbol | Done (V7). Also found most BOM errors are products missing from the load, and 33 shared codes |
| **YA004ITM_guide.xlsx** + macro email | Marc, 23 Oct (sent again, identical) | Macro version of an import template: a cover sheet with defaults and a button that writes the .txt from "Data with Headings", skipping 2 rows; sheet names hard-coded. Product layout of 19 columns (statistical groups, expiry, shelf life, serial, tax level GSR, back-to-back) | The macro didn't survive email (plain .xlsx, empty cover sheet). We use spreadsheets with the same sheet naming. Whether YA004ITM replaces ZSDIITM is asked |
| **SDI_Data_Migration_-_Import_Notes.docx** | Ethan, 23 Oct | Per-template fixes: allowed characters; BP tax rule table (no EU); AG address flag rule; GB and EU VAT formats; products and descriptions more thoroughly; BOMs need loaded products; work centre mapping; costs under material; SOH dates (2024) and DIE/CCE; SMR lots must be X3 lots; BICX/BISX "worked", missing accounts; IME column on BISX to come | Every point applied or asked (sections 5, 6, 14). The X3 lot export is still needed |
| **YA004SOHPJ** (instructions) | Ethan, 23 Oct | SOH + Dim Code (D02) and Dimension (P00003) between columns M and N | Built as YA004SOHPJ (22 columns), DIE/CCE to confirm |
| **YA004BPCDL_guide.xlsx** | Ethan, 23 Oct (sent twice) | Customer delivery addresses: BPCNUM, BPAADD, BPDNAM. Load after customers | Built, 2,268 rows |
| **ZSDIITMSUP_Guide_V2.xlsx** | Ethan, 23 Oct (sent twice) | Product-suppliers: ITMREF, BPSNUM, ITMREFBPS (= product code) | Built, 7,679 rows; PIO asked |
| **YA004MFG_Guide.xlsx** | Ethan, 27 Oct | Works orders: 11 columns, BOM code and routing code 10, update code C, status 1. Example rows are illustrative, not live orders. Standard spreadsheet tools can't read its styles; it was read from the XML | Built, 638 orders; 6 questions asked |
| **X3 work centre list** (screenshot) | James, 27 Oct | 33 X3 work centres with group, type and title (section 8) | Routes checked against it: all match |

**Still to receive:** the X3 lot export (SMR); the X3 import definition for YA004BISX
(CURLED); the field names for SOHPJ's two new columns; the IME column for BISX; clean-run
error logs; the original BPC and BPS template workbooks, to keep with this runbook.
