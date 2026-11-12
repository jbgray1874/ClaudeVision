# SDI Displays – Access SupplyChain to Sage X3: migration runbook

Last updated 11 November 2026 (Run 4 results, SDI actions due Fri 13 Nov; integrations register; section 20 lists everything beyond the migration). Go-live run 31 Dec 2026; go-live 4 January 2027.
**Start with section 19:** the current files, what was found on 4 Nov, and the open decisions.

This is the record of how the migration files are built and every rule behind them, so each
rerun between now and go-live starts from fresh Access data and the agreed rules, never from
an old file. Read section 1 before every run.

- Source: Access SupplyChain, SQL Server database `SDILive` (working schema `migration`)
- Target: Sage X3, UAT at `sdi-displays-trn.uk.sagex3.com`
- Partner: Acuity24. Marc Davies (X3 consultant) and Ethan Davies (templates, import logs)
- SDI: James Gray (AI and Systems Controller) builds and loads the files

---

## 1. Golden rules – how not to reintroduce old data

0. **SDILive is production. Access's own data must never change (James, 27 Oct).** The only
   objects a script may create or change are our own, in the `migration` schema: the XREF tables,
   ITM_LOOKUP and the views. Anything that touches `dbo` is SELECT only. Every write script must
   say at the top which migration objects it changes. Check before sending it: no INSERT, UPDATE,
   DELETE or ALTER may name anything outside `migration.`.
1. **Every extract is live, taken on the day of the run, at a fixed as-at time (James, 4 Nov).**
   Never build or hand over a file from an earlier extract as if it were current. Stock moved
   £21k in an hour while we worked. Products are selected by last activity against today's date
   (see 6.1), so an old product extract misses new products that are on live orders. Every file in
   a run comes from the same extract, and each file states the extract it came from.
   - **What went wrong on 3–4 Nov:** BICY and BISY were rebuilt for Company C01 and the column
     swap, and the transaction set was presented as current. All of it was still the 21 Oct
     extract (plus the 27 Oct new accounts). The fixes were right; the data was 2 weeks old. A
     rebuild that changes the rules must run on a fresh extract, or say plainly that it doesn't.
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
   the data rows only, semicolon separated, in the DOS code page (cp850), CRLF line ends. Every
   run writes it beside the spreadsheet (rule 1c).
7. **Hold back rather than drop.** Anything that would reject goes on a "Held back" tab with
   its reason, so nothing disappears silently.
8. **Check before handing over:** every code resolves (section 9), field counts match the
   template, no disallowed characters, keys unique.

---

### 1a. No exclusions by assumption (James, 30 Oct)

**Nothing is left out because of a guess about what Access holds or what X3 will need.** Every
record that's live in Access goes across. Where a value is missing, it gets the best value Access
does have, plus a flag; the record isn't dropped. A record is only left out on an explicit rule
that someone named has agreed, and it's listed with its reason. The exclusions found so far, and
what happens to each:

| # | Exclusion | Effect | Decision |
|---|---|---|---|
| 1 | **Costs:** only products with a non-zero Access standard cost got a cost | 6,902 of 16,499 products have no cost. 860 of them hold stock, and the stock load stops on them (FIXING49 etc., 30 Oct) | **Switched off, 30 Oct (`scripts/build_yitc.py`).** One complete cost file of 15,562: 9,597 Access standard costs, plus 778 stock lot cost, 2,049 last purchase price (393 of them EUR / USD converted at Access's own ledger rate, EUR 0.8643, USD 0.7484) and 3,138 BOM material roll-up for made products. Each cost's source is on the Cost source tab. Still on the Check tab: 73 products that hold stock at zero cost in Access (SDI to give a cost), and 864 with nothing in Access (no stock, purchases or costed BOM) |
| 2 | **Products:** OLD grade ignores stock, purchases and open orders | 1,681 live products, £603k stock, about 620 order lines held | **Switch off.** Any product with stock, open orders or recent purchases goes in |
| 3 | **Customers / suppliers:** GOOD grade only | 98 customers and 161 suppliers missed (fixed 27 Oct) | **Switched off.** Every live account goes in |
| 4 | **Order and invoice views** inner-joined to the cross-reference | 1,428 / 124 / 255 / 241 rows dropped silently | **Switch off.** LEFT JOIN: a missing account shows on Held back. STOP check in section 9 |
| 5 | **BOM lines** held when parent or component isn't in the product file | 33,596 lines | Follows 2: re-run once the products are in |
| 6 | **Product-suppliers:** main supplier only | 3,150 alternatives not loaded | Every pair now loads in the template's three columns, main supplier first. The PIO column was tried on 4 Nov and rejected by the import on 5 Nov; the priority is kept on a tab, not loaded |
| 7 | **Product-supplier links** for products not in the product file | 575 products | Follows 2 |
| 8 | **Stock lots** on products not in the product file | 2,176 lots, £603k | Follows 2 |
| 9 | **Order lines** with a product not in the product file | 418 SO and 204 PO lines | Follows 2 |
| 10 | **Works orders** held (no BOM or route, nothing left to make, prototypes) | 106 | Review the 42 with no BOM once 2 and 5 are done |
| 11 | **PHANT** set from "parent and component anywhere in Access" | 545 products mis-categorised | **5 Nov, Ethan: PHANT stays PHANT.** Run 3 rejected every PHANT → FGML change, so the usage test is off (`--phant access` is the default) and a product already in X3 keeps X3's category. Marc is working out another way. The test is kept as information on the "PHANT test" tab. **4 Nov: switched to the usage test.** Of 3,759 vw_ITM PHANT products: D 3,214 true phantoms stay PHANT (none holds stock or is on an open order of any kind); B 437 made or stocked sub-assemblies → FGML (360 have their own works orders; 102 hold £21.4k); A 97 sold → FGML; C 11 bought in, stay PHANT, to check. **X3's meaning:** the template guide calls PHANT a "Subassembly product", but an X3 phantom is never stocked or made on its own works order; its components are pulled into the parent's works order. **Open with Marc:** group B are real sub-assemblies. If SDI wants them shown as such, a "made, stocked sub-assembly" category (for example SUBML) can be created in X3 and the 437 switched over in one place (`products.py`). Group C is probably RAWML. `--phant access` restores vw_ITM's categories |
| 12 | **Routes on bought-in products** | 71 lines | Keep: X3 routes made products only (Ethan) |
| 13 | **Bank details for BACS suppliers only** | 44 suppliers on transfer terms | Keep: Ethan's template note |
| 14 | **Accounts left out:** intercompany, ledger accounts, employee expenses | 6 customers, 78 suppliers | Finance to decide. Until then they're listed, not silently dropped |
| 15 | **Dormant accounts:** no trade for 2 years and nothing open | not migrated | To confirm with SDI |
| 16 | **Products with no cost** left out of YITC (on Check instead) | 937 products had no cost line, 73 of them stocked | **Switched off, 2 Nov.** Loaded at 0, listed on Check for SDI to supply a cost. YITC now has a line for all 16,499 products |
| 17 | **vw_ITM drops products marked do-not-use or archived** in STK_STOCK (discovery, 31 Oct) | live ones never reached the product file | **Switched off** in `rebuild/`: they come through the master grid; live ones go in and are on Check |
| 18 | **vw_BOMP drops a hard-coded list of 51 components** and lines with no quantity | BOM lines missing, components never pulled into the product file | **Switched off** for products (`rebuild/` reads ASC_BOM_TBL). The 51 to review in the BOM part |
| 20 | **County / region never filled** on customer addresses: the template column has no X3 field code | X3 needs a State/Region for CA, AU, AE, US: DRE100, MAR101, PER101 rejected (XSAT), with their delivery addresses | **To fix for Run 3:** fill it for those countries (Run3_master_data_fixes.xlsx). Map the column properly in the customer part of the kit |
| 21 | **FGSL is not stock-managed in X3** | 451 FGSL products hold stock (1,222 lots, £1.72m); SMR rejected them (1,500+ errors) | **Decision for Marc / Ethan:** make FGSL stock-managed. These are bought-in goods SDI really stocks; otherwise the stock can't load |
| 22 | **vw_DQ_ITM grades against today's date** | 395 products loaded in October had aged from GOOD to REVIEW / OLD by 4 Nov and dropped out of the rebuild | **Fixed 4 Nov:** a product already loaded in X3 always stays (`--loaded`, default the previous set's ZSDIITM). A loaded product not found in Access is put on Check, never dropped |
| 23 | **Shared codes hide live products** (two Access products clean to one X3 code) | 129 held back on 4 Nov; **22 are live**, e.g. "M&S-PROTOTYPE *" (36 open SO lines, 15 works orders), "TIE-MILW 150MM S" (20,200 units), the "TUBE 11673-01(n)" series. Their stock and orders land on the kept product | **SDI decision.** Suggested: each live one takes its own code (`<code>-2`), applied in every file at once. Listed on the ZSDIITM Check tab |
| 19 | **Description 1 is only the code** (STKNAME on sub-assemblies / parts: "10074-02-SA01") | 1,753 loaded products show the code, not a name | **Fixed in `rebuild/`, 2 Nov:** takes description 3, then PMA_DESC (the part master's own description, which vw_ITM never read), then description 2. 1,653 fixed from data held; the other 100 from PMA_DESC on the next extract |

### 1b. Complete files only, never a top-up (James, 30 Oct)

**Every file is the whole file, rebuilt from scratch from one extract.** No top-up, add-on or
"new rows only" files. When something was missed, the fix is a new complete file with it in.
That way the file always matches Access as a whole, and the change report (`rebuild/changes.py`)
shows exactly what moved since the last load. The new-accounts-only files of 27 Oct and the cost
top-up of 30 Oct were withdrawn under this rule.

### 1c. Every run produces both the spreadsheets and the X3 load files (James, 31 Oct)

Each mapped spreadsheet comes with its `;` load file, built from the saved spreadsheet so the
two can't disagree (`rebuild/common.py`, `write_load`). The format is the one James loads (V1.3
"cleansed" files):
- data rows only, no headings;
- one field for every template column;
- `;` between fields, no quotes;
- CRLF after every line;
- DOS code page 850.

The writer stops if a value holds a `;` or a line break. Tested 2 Nov: the ZSDIITM and YITC files
match the loaded V1.3 files byte for byte on every unchanged row.

### 1e. Every file, every run - master data too (James, 4 Nov)

**A run rebuilds every file from the day's extract, the master data included.** BOMs and routes
were left as the 27 Oct build on 4 Nov, and it showed: 95 works orders held for no BOM. If a
file can't be rebuilt (its live source isn't extracted yet), the handover names it: which file,
why, and what's needed (rule 1d).

### 1d. Missing or unusable data: ask James for it, by name (James, 4 Nov)

**When an extract is missing, out of date, from the wrong moment or fails a check, say so and ask
James for exactly what's needed.** Don't build round it, don't fall back to an older extract, and
don't leave it implied. Every request names:
- the script (path in the repo);
- when to run it, and after what (e.g. after `add_new_accounts_to_xref.sql` has committed);
- what its check grid should show, so a bad run is caught at once;
- why it's needed and which file waits on it.

The 4 Nov lesson: `extract_transactions.sql` was run at 17:06, before the cross-reference commit
landed. Its CHECK grid showed 0 / 0 new accounts and 1,458 SOH lines dropped, against 56 after the
commit. The evening upload didn't include a rerun, and that had to be asked for plainly.



| # | Template | What it is | Track |
|---|---|---|---|
| 1 | YA004BPS | Suppliers | 2 |
| 1a | YA004BPSC | Supplier bank details (after suppliers; new 28 Oct) | 2 |
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
| 13 | YA004BICY (was BICX) | Customer open items (sales ledger) | 1 |
| 14 | YA004BISY (was BISX) | Supplier open items (purchase ledger) | 1 |

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
  **Column D, Posted Date (IPTDAT), is the day the stock is loaded (`STOCK_DATE`), section 6.9.**
  **Column E, Description (VCRDES), is the product key: it carries the product code (ITMREF) on
  every line, the same as column H (James, 28 Oct).** It was "OPENING STOCK" on every line.
  The guide's examples (IMP1, IMP2) show it changes per line. `populate_guides.py` sets it,
  `recode_ledgers_v7.py` keeps it equal to the clean-run code, and `build_sheets.py` writes it.
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

**YA004BICY – customer open items (24 columns, one heading row only). Was YA004BICX (renamed 28 Oct).**
Invoice Type, Document, Customer, **Company**, Site, Accounting Date, Currency, GBP Amount, Transaction
Amount, Source Date, Paying Customer, Due Date, Payment Terms, Source Document, three
comments, Line, Site, Plan code, General accounts, Distribution, Comment, Transaction Amount.
- MINV / MCRN / MREC / MJDT / MJCT. General account 999100. Plan code 18L.
- Amounts are the outstanding balance, positive; the document type carries the sign.
- **Company (column D, new 28 Oct): C01 on every row (3 Nov).** S01A is the site, already in
  Site. C01 is the company Acuity put in for Run 2, and BICY then loaded with 0 errors. It's the
  default in `scripts/build_bicy_bisy.py` (`COMPANY=` overrides it).
- **Document (NUM, column B) and Source Document (BPRVCR, column N) are swapped (Run 2, Acuity).**
  NUM now holds the order number (ST_ORDER_NUMBER) and BPRVCR the Access invoice number
  (ST_HEADER_REF). Every NUM is kept unique, so no two items can merge into one X3 document:
  - a value used more than once takes -2, -3 (160 BICY items share 68 order numbers);
  - a blank or 0 takes the invoice number. These are the 18 receipts and journals that Acuity
    filled with 0 by hand.
  `SWAP=0` keeps B and N as built. **Ask Ethan whether X3 needs NUM unique**; if it doesn't, the
  suffixes can go.

**YA004BISY – supplier open items (24 columns, one heading row only). Was YA004BISX (renamed 28 Oct).**
As BICY, with Supplier and Paying Supplier, and general account 999200. Columns: Invoice Type,
Document, Supplier, **Company**, Site, Accounting Date, Currency, GBP Amount, ... the same as BICY.
- **CURLED is removed (James, 28 Oct).** It was column 7 of BISX; X3 didn't recognise it.
- **Source Document** is the supplier's reference (PT_HEADER_REF2), else the order number, else the
  document (PT_HEADER_REF). On 28 Oct, 317 items (£1.6m) came out blank: Access holds a missing
  order number as '' not NULL, so the view's COALESCE stopped there. `views_v2.sql` now NULLIFs it,
  and `populate_guides.py` fills any blank with the document reference. The BICY Source Document
  (ST_ORDER_NUMBER) had no blanks.
- Company in column D, as BICY (C01). Document and Source Document swapped as BICY: 454 repeated
  values take -2, -3. The blanks Acuity filled with BLANK are already filled from the document
  reference (the 317 above), so none reach X3 blank.
- **Lines, not suffixes (Ethan / Jim, 11 Nov, Run 4). ON HOLD 12 Nov, `LINES=1` only: see 19.12. The 5xxxxxx number is the PO number.**
  Document (B) is the Access document number (5 and six digits), never one we made up. Rows that
  share an Access number (same supplier, currency, terms, type) are lines 1, 2, 3 of that one
  document (Line, column R), written next to each other; header GBP Amount and Transaction Amount
  carry the document total; each line keeps its own line amount (column X). 4 Nov data: 193
  documents became multi-line (415 rows now lines 2+, up to 18 lines); 1,641 documents; line total
  unchanged. A "Lines" tab lists every one. `LINES=0` rebuilds the old layout (proved identical to
  the file sent). **BICY is not changed:** its Document is the customer order number, and repeats
  there are different invoices, not lines.
  - **The catch, put to Ethan:** the "lines" of one Access number are separate supplier invoices
    (5028370: six supplier refs, 6 Aug–21 Sep, due 30 Oct and 29 Nov). X3 keeps the header of
    line 1 only: one supplier ref, one source date, one due date. 134 documents differ in source
    date, 56 in due date.
- **No Access document number (259 items, £1,332,793.58, 4 Nov):** Document = the supplier ref
  (B = N). With SDI Finance (Claire) to explain: `deliver/Finance_BISY_blank_Access_document_numbers.xlsx`.
  Many look like deposits / prepayments against POs ("PO5029719DEP"), direct-debit and card
  items, keyed straight into the purchase ledger. Confirm in Access with
  `rebuild/sql/check_bisy_document_numbers.sql`. They stay as they are until Finance answers.
- **Built by `scripts/build_bicy_bisy.py`** from the BICX / BISX files that `populate_guides.py`
  makes. It deletes CURLED, inserts Company at D, swaps B and N, updates the Mapping, Guide and
  Notes tabs, reads every row back, and writes the `;` load file (rule 1c). Rows and values are
  otherwise identical.
- **Load BICY and BISY from the file, not the macro.** They have one heading row and the
  macro skips two, so it would drop the first item.

### Track 2

**YA004BPSC – supplier bank details (9 columns, two heading rows; new from Ethan, 28 Oct)**
`BPSNUM, BPAADD, CRY, BIDNUM, PAB1, BICCOD, PAB2, CUR, BIDNUMFLG`

| X3 field | Heading | Mapped from | Rule |
|---|---|---|---|
| BPSNUM | Supplier | Sage supplier code: `migration.XREF_SAGE_BPS`, plus the 83 new pairs written into the query | |
| BPAADD | Address | `001` | the supplier's only address in YA004BPS |
| CRY | Country | the final supplier file (column 19), so the corrected country | |
| BIDNUM | Bank acct. number | `PL_ACCOUNTS.SU_BANK_SORT` + `SU_BANK_AC_NO` | `XXXX` + 6-digit sort code + 8-digit account number, digits only. 7-digit accounts padded with a leading 0. Access holds no bank identifier (BIC), so XXXX stays, as Ethan's note says |
| PAB1 / BICCOD / PAB2 | Domicile / BIC / Paying bank 2 | | blank |
| CUR | Currency | the final supplier file (column 5) | |
| BIDNUMFLG | By Default | `2` | Yes |

- **Only suppliers paid by BACS** (payment terms BAC_..., 662 of the 706). That's the template's
  note: "Bank details only needed for suppliers paid by BACs at this stage".
- Not loaded, and listed on the Check tab: a BACS supplier with no bank details in Access, and
  anything that isn't 6 + 8 digits. Access also holds `SU_BANK_AC_NAME`, `SU_BANK_BANKNAME` and
  `SU_BANK_BACSREF`; the template has no field for them.
- **Build:** run `sql/supplier_bank_details.sql` (read-only, one grid), then
  `scripts/build_bpsc.py <grid> YA004BPSC_bank_details_MAPPED.xlsx`. The tabs are renamed from
  Sheet1 / Sheet2 to "Data with Headings" / "Guide" because the macro looks for that name.
- **Confidential:** bank account details. The spreadsheet and the query output stay out of git
  and inside SDI.
- **Built 28 Oct:** 626 BACS suppliers loaded, all GBP, BIDNUM 18 characters. On the Check tab:
  - 35 BACS suppliers have no bank details in Access;
  - ASS500's 7-digit account was padded to 8 (Finance to confirm);
  - PRC500 is held: the account number 93957497 sits in the bank-name field and "HSBC" in the
    account field, so fix it in Access.
  44 suppliers on transfer terms (TFR_) aren't loaded. Four BACS suppliers have a UK sort code
  but a non-UK address country (FR, NL, HK, AT), and are loaded as they are.

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
- **Check which version is in SDILive before every extract.** On 27 Oct the table in the database
  was still version 2 (215 of 217): WCP02 pointed at WCP100 instead of WCP101, and HCL02 / HOT100
  was missing. Run version 3 first. A quick check: `SELECT COUNT(DISTINCT SAGE_CODE) FROM
  migration.XREF_SAGE_BPC` must be 217.
- The old-to-new customer list for Customer Services (Sue Rogers) is built from this table:
  `SELECT ACCESS_CODE, ACCESS_NAME, SAGE_CODE, SAGE_NAME FROM SDILive.migration.XREF_SAGE_BPC`.
- **Creating new customer and supplier accounts is done by the import, not by Acuity.** An
  account missing from X3 (Techtronic ELC GmbH TIE02E/TIE02POL, M&S plc MAR002, Boots UK BOT01 ...)
  is added as rows in the YA004BPC / YA004BPS file, with a new code in the same pattern:
  3 letters of the name + 100 for customers or 500 for suppliers, the next number within a
  group (TEC100-102 exist, so Techtronic ELC would be TEC103).
- **Why live customers were missing (27 Oct):** the customer import took only accounts graded
  GOOD in `migration.vw_DQ_BPC`. 98 accounts not graded OLD were left out: 55 "possible
  duplicates" (same name, really per-country or per-currency accounts, 20 of them Techtronic),
  16 overseas accounts flagged because category and tax rule disagree, 12 "UK with no postcode"
  (mostly overseas), 3 with no address, 4 intercompany, and 8 GOOD ones newer than the file.
  On every rerun, select on "not OLD", not "GOOD only".
- `scripts/build_customers_to_add.py` turns that list into `Customers_to_add.xlsx` with an action
  and a proposed code per account: 86 to add, 1 to add once it has an address (IBS01), 4
  intercompany and 2 ledger accounts (ESD01 discount, FSC01 fuel scale charge) left out for
  Finance, and HCL02, which is already in X3 as HOT100. Within a 3-letter group, codes already
  given to Customer Services go first, then the most recently invoiced. **Codes promised to Sue:
  TIE02E = TEC103, TIE02POL = TEC104.** Don't let a rerun change them (they're in `PROMISED`).
- **A missing account isn't just a missing customer row.** The order and invoice views
  inner-join to the cross-reference, so an account with no Sage code silently loses its rows.
  The 27 Oct extract dropped:

  | File | Rows dropped (no Sage account) | Fix |
  |---|---|---|
  | YA004BPC customers | the 87 accounts themselves | new rows in the customer spreadsheet |
  | YA004BPCDL delivery addresses | their addresses | new rows from SL_ADDRESSES |
  | YA004BICX open sales invoices | 255 items, about GBP 4.48m (loaded: 587, GBP 5.25m) | rebuild after the xref |
  | YA004SOHPJ open sales orders | 1,428 lines | rebuild after the xref |
  | YA004BPS suppliers | to be measured: `sql/suppliers_missing_from_x3.sql` | new rows in the supplier spreadsheet |
  | YA004BISX open purchase invoices | 241 items | rebuild after the xref |
  | YA004POH open purchase orders | 124 lines | rebuild after the xref |
  | ZSDIITMSUP product-suppliers | links to the missing suppliers | rebuild after the xref |

  Products, BOMs, routes, costs, stock (SMR) and works orders carry no customer or supplier
  code and aren't affected. The "Held back" tabs in POH and SOHPJ are a separate issue:
  products not in the item load.
- `scripts/build_customer_mapping.py` builds the customer mapping table (all 304 live customers:
  217 in X3, plus 86 new, plus IBS01 once it has an address) and `sql/xref_new_customer_accounts.sql`,
  which adds the 86 new pairs to XREF_SAGE_BPC as MATCHED_BY = 'new account'. Accounts that share
  a name (Techtronic, Boots, Kurt Geiger ...) can't be matched by name, so these pairs are fixed by
  code. Load order: the customer import (which creates the accounts) before BICX and SOHPJ.
- `scripts/build_new_customers.py` turns the output of `sql/new_customer_details.sql` (vw_BPC
  plus SL_ADDRESSES) into customer rows and delivery addresses for the new accounts (27 Oct: 86
  customers, 3,901 addresses). It writes only the complete customer and delivery address files
  (rule 1b; the new-accounts-only files of 27 Oct are withdrawn), the full clean-run
  files with the new rows after the existing 2,268, which are left unchanged. Its rules:
  - the address code is the Access AD_CODE (three digits); the address Access flags as main is the default;
  - one SL_ADDRESSES field can hold several lines, padded to 30 or run together, so it's split;
    anything past three lines is folded into line 3 or 2, or listed if it doesn't fit;
  - the tax rule comes from the Access VAT code (DOM → DOM/DOM, EU → ROW/ROWC), with conflicts
    against the address country listed for Finance;
  - where Access says GB but the address names another country, the named country is used (994 addresses);
  - VAT numbers without a country prefix are blanked, with a suggested prefix on the Check tab;
  - blank addresses are left out, and duplicate delivery descriptions get the address code added.
- **Suppliers, the same.** `sql/new_supplier_details.sql` lists the live suppliers with no Sage
  code and their vw_BPS rows in one run (27 Oct: 161). `scripts/build_new_suppliers.py` decides
  and builds:
  - **Added (83):** every supplier with open invoices or PO lines (35 suppliers, about GBP 840k,
    110 PO lines), plus companies that traded in the last 24 months.
  - **Left out for Finance to confirm:** 72 employee expense accounts with nothing open (the first
    supplier load had none either), and 6 accounts that aren't suppliers (petty cash, HMRC, Lloyds
    Cardnet, "Joinery", two marked do not use).
  - **Codes:** next free from 500.
  - **Rows:** the 33-column supplier layout, with the character rule, EU → ROWS, no dummy or
    unprefixed VAT numbers (suggestions on the Check tab), the country taken from the address when
    Access says GB, and UK postcodes fixed.
  - **Cross-reference:** it also writes `sql/xref_new_supplier_accounts.sql` (codes only). Run it
    after `xref_sage_codes.sql`, as for customers.
- **Orders and invoices of the new accounts (27 Oct).** `sql/export_new_accounts_orders_invoices.sql`
  is read-only, with the new codes written in, so no cross-reference change is needed. It returns
  only those rows. `populate_guides.py` takes them as `EXTRA_EXPORT`, with `CUSTOMER_FILE` and
  `SUPPLIER_FILE` pointing at the final customer and supplier files. Then run `recode_ledgers_v7.py`
  and the Track 1 part of `build_sheets.py`. The rebuild without EXTRA reproduces the earlier load
  files byte for byte; with it, every existing row is unchanged and these rows are added:
  - SOHPJ: 1,149 lines (222 more held back for products not in the item load);
  - POH: 100 lines;
  - BICX: 230 items, GBP 3.54m;
  - BISX: 253 items, GBP 0.84m.
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
- **How vw_DQ_ITM grades.** Last activity is the latest of the product's last sales order, its
  last works order, or, for a BOM component, the last sales or works order of any product it's
  used in. OLD means no activity or more than 5 years ago. REVIEW is 2–5 years, INCOMPLETE is
  current with no description, GOOD is current. **It ignores purchase orders, goods received and
  stock on hand**, so a bought-in material that's in stock but not on a recently active BOM is OLD.
- **The same gap as the customers (27 Oct): live products graded OLD are left out.** The clean-run held-back tabs show:
  - 1,473 products holding stock, worth GBP 603,151 (2,176 SMR lots). Most are real materials:
    mild steel (MS) GBP 85k, fixings GBP 30k, powder GBP 27k, sub-assemblies, sheet metal,
    electrical, plastics, MDF.
  - 250 products on open orders (192 PO and 196 SO lines).
  - 271 of the stocked products are BOM components.

  Rule from now on: **any product with stock or an open order is migrated, whatever its grade.**
  The grade only decides what has to be fixed.
- Descriptions: Access STKNAME is often blank or repeats the code; the real text is in
  ITMDES3 / PMA_DESC_3. A blank first description takes description 3, then 2, then the code.
  **623 products still have only the code** (5 Nov): Access holds no other text for them in any field. SDI to supply.
- **Categories (Ethan, 5 Nov):** a product already in X3 keeps the category X3 holds: X3's import rejects a category change on an existing product. A new product takes vw_ITM's category, and PHANT stays PHANT. Build with `--loaded` set to the file loaded in X3 (`ZSDIITM_loaded_in_X3_Run2_V1.3.txt`, 16,499), not a later build.
- **The run date (`--today`) is the extract's date**, not the build day. The two-year activity window counts from it. On 5 Nov, a build dated the 5th dropped 16 products last bought on 4 Nov 2024.

### 6.2 BOMs
- 33,596 BOM lines are held back because a parent or component is not a product in the load:
  14,304 products, mostly old. **SDI decision:** bring them into the product file, or drop
  the lines.
- 92 BOMs load with one or more components missing (215 lines). They're listed on the BOM
  spreadsheet's "Missing components" tab.
- BOMs on bought-in FGSL products are held back. X3 builds manufactured products only.

### 6.3 Routes
- Routes on RAWML or FGSL products are held back (71 lines, 36 products). X3 routes manufactured products only (Ethan, Run 2).
- 5 Nov: 116 lines are on 15 products Access now routes, but X3 holds them as FGSL / RAWML from Run 2. **James, 5 Nov: leave them in, X3 skips them**, so the file goes as built (TES-12567-01-GA 48 lines, BOT-12631-08-00 19, TIE-12515 18, MS-0346603 16, and 11 others). If SDI makes them, they should be FGML in X3. That's a category change, so it goes with Marc's PHANT workaround.
- From live data since 5 Nov: `rebuild/routes.py`, with work centres from `rebuild/work_centres.csv`.
- Work centres: section 8.

### 6.4 Product-suppliers
- Access holds no supplier against the part: STK_STOCK_2.STK_SUPPLIER1–10 are empty.
- From purchase order history in ASC_POR_TBL, which starts on 1 September 2022. Each
  product's suppliers are ranked by most recent order. **Every pair loads** (since 4 Nov) in the
  template's three columns, main supplier first. The PIO column was rejected by the import on 5 Nov.
  The priority is on the "Supplier priority" tab, not loaded.
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

#### Customer address rules (4 Nov, from Run 2's XPOSCOD / XSAT rejections)

`scripts/fix_customer_addresses.py` applies these to **every customer address**, not only the
ones X3 rejected. Every change goes on the "Address fixes" tab; anything a rule can't settle goes
on "Address check". **They must run on every rebuild of the customer file.**

1. **Postcode left in the address text → moved into the postcode field.** This applies when the
   postcode is blank. It covers a postcode at the end of a line, and the continental order with the
   postcode before the town ("75018 PARIS", "4815 HK BREDA", "F-36330 ARTHON", "DK-2650 Hvidovre"),
   with any country prefix stripped. It's removed from the line. Access's own address fields are
   used as evidence too (next item).
2. **Mistyped GB postcodes:**
   - letter O and zero, or letter I and one, are swapped back (SE1 OHX → SE1 0HX, S021 3SP →
     SO21 3SP, IG10 ILJ → IG10 1LJ). This applies only where one reading with the fewest changes
     is a valid GB postcode, and only to a postcode that already contains letters, so a foreign
     number like "10310" is never "corrected";
   - a space misplaced inside the inward code is fixed (DN2 4 PE → DN2 4PE), but only if the
     district stays as typed. "G13 SQ" is left alone: a digit is missing, not a space;
   - a Polish postcode is written NN-NNN (055 32 → 05-532).
3. **Text in the postcode field → the postcode only** ("77990,FRAN" → 77990). A US or AU state
   code found there ("NY 10013", "NSW 2000") moves to State/Region.
4. **Wrong country:**
   - a Dublin Eircode, or a Dublin district ("DUBLIN 15"), marked GB → IE, with the routing
     key as the postcode (D15);
   - a GB address that names another country in its text, with no valid GB postcode → that
     country (the rule used for the new accounts on 27 Oct). Cyprus, Shanghai, Dublin and so on;
   - a country name typed into the postcode field ("IRELAND", "TURKEY", "MALAYSIA") → that
     country, with the postcode left blank.
5. **Phone numbers → brackets removed** ("0046 (0) 470705100" → "0046 0 470705100", as James
   did by hand for Run 2).
6. **State/Region** (the template's "County / region" column, never filled before), using the
   standard ISO 3166-2 codes:
   - CA: from the postcode's first letter (M → ON);
   - AU: from the postcode range (2000 → NSW);
   - US: from the ZIP code range (10013 → NY), or the state code typed with it;
   - AE: from the emirate named in the address (Ras Al Khor, Jebel Ali or Dubai → DU; Sharjah → SH);
   - otherwise a state code written in the address.
   **Asked of Ethan:** the X3 field code for that column (it has none in the template; SAT?) and
   whether X3's region codes are these ISO codes.
7. **AE has no postcodes:** a number in an AE postcode is a PO box, so it's moved into the address
   as "PO BOX nnnnnn" and the postcode is left blank (DRE100's 239600).
8. **Access's own address fields are evidence** (from `bp_identifiers_run3.sql`, so for the
   accounts it covers). These fields are in `SL_ADDRESSES` but **the customer build never used
   them; the customer part of the kit must:**
   - **AD_COUNTRY** holds the real country as text where AD_COUNTRY_CODE says GB ("CANADA",
     "BRAZIL", "Nederland", "BANGKOK, THAILAND"). It decides the country before the address text does;
   - **AD_ADDRESS_USER1 / 2 and AD_COUNTRY** hold towns and postcodes ("L5L 5Y5", "S9 1TQ" typed in
     AD_COUNTRY with "FAO-" in the postcode field);
   - a Dutch postcode split across fields ("3315" + "LG Dordrecht") is joined: 3315 LG;
   - a GB postcode whose inward part was split ("G13 SQ", stored by Access as "G13SQ") takes its
     only valid reading, G1 3SQ (79 Gordon Street, Glasgow).

On 4 Nov: **507 fixes (223 on the six X3 rejected); 1 address left to check** (BEA101, AU, no
postcode or state; it isn't one of the six, so it wasn't in the Access query). Every rejected
address is settled.

#### Supplier VAT rule (4 Nov, from Run 2's FR rejections)

`scripts/fix_suppliers.py`. Run 2 blanked VAT numbers as dummies; the Access values are now
**checked, not assumed**:
- A French VAT number is FR + a 2-digit key + the 9-digit SIREN, where the key is
  (12 + 3 × (SIREN mod 97)) mod 97 and the SIREN passes the Luhn check. A value passing both is
  a real FR VAT number whatever prefix Access gave it, so it's restored with FR. GAL500 →
  FR65572062594 and ICE500 → FR73539546192 (Access had "GB…").
- A value passing no check (FR, GB or SIREN) stays blank, for Finance. Nothing is made up.
- The CRN (SIRET, 14 digits) can't be derived: it's the SIREN plus a 5-digit site number Access
  doesn't hold. Ethan has been asked whether X3 accepts the 9-digit SIREN meanwhile.
- Each rejected supplier is listed on "Supplier check" with what it still needs.
- **The VAT numbers are read straight from Access** (PL_ACCOUNTS.SU_VAT_REG_NO, via
  `bp_identifiers_run3.sql`). That found a third: BUR500 → FR96790182786, a new account of 27 Oct
  whose VAT number never reached the file. It also showed GAL500 and ICE500 are stored in Access
  with no prefix: the "GB" was added by the earlier build.
- **Supplier postcodes:** the customer rule 1 is applied to every supplier address. French and
  Spanish suppliers had the postcode before the town in an address line: 11 postcodes (22 field changes), e.g.
  AMG500 "75018 PARIS", BAL500 "F-36330 ARTHON", PLS500 "03802 ALCOY".
- **Tax codes:** Access has the FR suppliers on FZ / FV and BAL500 on SV (standard VAT), which is
  why BAL500 came out DOM. Finance to decide.

#### Where Access keeps VAT numbers (`sql/vat_sources_discovery.sql`, 4 Nov)

The users said Access SupplyChain holds VAT numbers the files don't have. Every VAT or registration
column in SDILive was checked:

| Column | Values (distinct) | Used for |
|---|---|---|
| `PL_ACCOUNTS.SU_VAT_REG_NO` | 79 (79) | supplier file, already |
| `SL_ACCOUNTS.CU_VAT_REG_NO` | 90 (85) | customer file, already |
| `SL_ADDRESSES.AD_VAT_REG_NO` | 631 (89) | **customer file: fills gaps (below)** |
| `SL_ADDRESSES_COPYA.AD_VAT_REG_NO` | 122 (70) | customer file: fills gaps (below) |
| `ASC_PL_ACCOUNTS.SUP_COMPANY_REG_NO`, `PL_ACCOUNTS.SU_COMPANY_REG_NUMBER` / `SU_CIS_COMPANY_REG_NO`, `ASC_COM_TBL`, `SL_ACC_TEMP`, `SOP_TRN_TEMP` VAT fields | 0 | – |

**Suppliers: there is nowhere else.** The gaps in the supplier file are gaps in Access. A blank
VAT number loads on a non-FR supplier, so Finance only has to supply the FR ones.

#### Customer VAT rule (4 Nov)

`sql/customer_vat_numbers.sql` (read-only; run after `add_new_accounts_to_xref.sql`) lists every
number per customer, from the account and from every address. Then `scripts/fill_customer_vat.py
<output>` works on the address-fixed BPC in place.

Of the 303 customers, 32 had a number. A blank EECNUM is filled only when all of these hold:
- the number passes its country's format (EU VIES formats, GB/XI with HMRC check digits, CH, NO);
- it's for the customer's own country;
- no other customer has it;
- it's the customer's only number, or the only one on an invoice, statement or main address.

Spaces, dots, dashes and NBSP are removed and the country prefix added (GB342074427), matching the
numbers already in the file. Everything else goes on the "VAT check" tab with the reason, e.g.
a Dutch-format number on a UK customer, or a number shared with another customer. Numbers
already in the file are never changed. Afterwards, copy the file to the current set and rerun
`exclude_customers.py` for the without-Tesco copy.

Tested on the six customers' addresses held from `bp_identifiers_run3.sql`:
- TEC105 gets GB342074427 (one copy in Access has NBSPs);
- PER101 gets NL001875607B01;
- a number shared with another account, and a GB number with bad check digits, are both held for checking.

**One company, two accounts.** A shared number is filled when every account holding it has the
same first two words of name and Access holds it on this account's own record. Examples:
SAS100 / SAS101, and TEC110 / TEC115 (TECHTRONIC). X3 doesn't require EECNUM to be unique. These
are marked "shared with …" on "VAT filled".

**Result, 4 Nov evening (output of 18:32):**
- **24 filled, 10 of them shared** (BOO104, CAS100, HHA100, LIP100, PER101, SAS100/101, SIM101,
  TEC106–112, TEC114, TEC115, TEC118–122, TES102, WIL102). **56 of 303 customers now have a VAT
  number, against 32.**
- **5 left on "VAT check":**

  | Customer | Number in Access | Why not filled |
  |---|---|---|
  | LIN101, LIN102 (CH) | the UK company's GB number, on delivery addresses | GB number on a Swiss customer |
  | PET101 (GB, NI) | PET100's IE number | not a UK number |
  | ROL100 | 8 digits | not a GB number |
  | TEC116 (PL) | TEC103's DE number | not a PL number |

- **The other 247 have no number anywhere in Access.**
- Stray numbers on delivery addresses of filled customers are listed and ignored, e.g. TEC119's
  "864199168801" (8 for B).

#### Stock and product prices (checked 4 Nov)

**Every product holding stock is in the product file with a cost line:** 4,888 products,
£4,065,281 at Access lot cost. 4,727 have a real cost. 161 are at 0, and Access values their
stock at £0 too, so the opening stock still ties to Access. SDI should still give them a cost.
Base price (BASPRI) comes from Access STK_BASEPRICE; 0 where Access holds none, and loaded all
the same.

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
- Accounting date for UAT: 20261031. It's used by BICX, BISX and the SOH date moves.
- **Stock (YA004SMR) Posted Date (IPTDAT, column D) = the day the stock is loaded, today's date
  on load day (James, 28 Oct), not the accounting date.** Set `STOCK_DATE` (yyyymmdd) when running
  `populate_guides.py`. It's a fixed value, not the system date, so a rebuild gives the same file.
  The view's 20261031 is replaced, on the Held back tab too. UAT file of 28 Oct: 20261028.
  **Go-live run: 20261231.**
- **Go-live run: dated 31 December 2026 (James, 28 Oct).** For that run:
  - the accounting date is **20261231**. Change the three `-- ACCOUNTING DATE` literals in
    `views_v2.sql` (vw_SMR_V2, vw_BICX_V2, vw_BISX_V2), and `ACCOUNTING_DATE` in `populate_guides.py`,
    which it uses to move SOH dates;
  - the stock posted date is `STOCK_DATE=20261231`;
  - the extract is taken at the 31 Dec close, all files on the same day (golden rule 1).

  An older note said 20270103 (the day before go-live, 4 Jan). That's replaced.
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

- [ ] **STOP if anything was dropped for want of an account.** The "rows dropped - no Sage
  account" check in `views_v2.sql` must read 0 for SOH, POH, BICX and BISX. On 27 Oct it read
  1,428 / 124 / 255 / 241. It was reported but not acted on, and live customers and suppliers
  with open invoices and orders were missing from X3. A non-zero count blocks the hand-over.
- [ ] Every live account (open items, open orders, or traded in 24 months) is in the customer or
  supplier file, whatever its data-quality grade. A grade decides what has to be fixed, never
  whether the account is migrated.
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

**Working lessons (5–11 Nov) – read before every run and every e-mail:**
- **Every date you give someone, check the weekday.** On 11 Nov a deadline went out as "Friday 14 November"; Friday was the 13th. Run `python3 -c "import datetime;print(datetime.date(2026,11,13).strftime('%A'))"` before sending.
- **A fixed replacement date goes stale.** Past required dates were moved to 6 Nov; by the reload on 11 Nov that date was itself in the past. The replacement date must be after the load day. Regenerate on the load day (`--required-date`), or use a date comfortably ahead (30 Nov for Run 4).
- **"Only these files, nothing else" means exactly that** (James, 5 Nov). Holding back lines on PHANT products was an extra nobody asked for, and it was undone. Apply only the change asked for, then say what else you'd recommend, separately.
- **Don't remove rows X3 will skip** (James, 5 Nov). The 116 route lines on bought-in products stay in the file; X3 skips them.
- **When Ethan flags a rule on one file, check every file it applies to.** He found 2023 order dates on POs; the same 385 lines sat in the sales orders and were fixed in the same pass.
- **Reconcile ledgers on a net basis** (invoices less credits and receipts / payments), excluding the accounts not in X3. Check journals' direction: CAP500's £22,500 journal is the only supplier difference (11 Nov).
- **Prove "nothing else changed" cell by cell** before sending a regenerated file, and keep every moved value on a "Re-dated" / "Held back" tab.
- **Keep superseded files out of reach:** move them to a `superseded_<date>` folder so they can't be attached by mistake.
- **E-mails go in the chat, ready to paste** – not in .md files (James, 5 Nov).
- **Lists that name customers or suppliers stay inside SDI.** Send one attachment per team (Purchasing, Customer Service, Finance) with only their items.
- **Never invent a key Acuity will reconcile against** (Ethan, 11 Nov). The -2, -3 suffixes on BISY made
  documents that don't exist in Access. Use the source system's numbers; where one is missing,
  ask (rule 1d), don't make one up.
- **A rule that merges rows must check what the merge loses** – header fields that differ between
  the rows (dates, references) go to the first row only. Say so before sending.
- **Tell the user plainly what wasn't rebuilt or what's missing** (rules 1d and 1e) – never leave a stale file in a "current" set unannounced.


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
- **Macro:** skips two heading rows. BICY and BISY (was BICX / BISX) have one.
- **Missing accounts drop rows silently.** The order and invoice views inner-join to the
  cross-reference, so an account with no Sage code loses its orders and invoices from the export.
  The data-quality grades (customers: GOOD only; products: OLD) left live accounts and products
  out. Every live record is migrated; a grade only says what to fix. See the section 9 STOP check.
- **Queries on SDILive:** read-only against Access (`dbo`), and narrow to the codes needed
  before joining or totalling. Two queries on 27 Oct ran far too long because they totalled whole
  tables first. Check brackets and REPLACE arguments before sending.
- **Don't start a dependent import while the one before it is still running.** On 27 Oct
  YA004BPCDL was loaded while the customer import (over an hour) was still going:
  - TES101 gave "Table modification in progress", because the customer import had the record open;
  - TEC100, DRE100 and MAR101 gave "BCGCOD / BPCPYR mandatory" and "Address code does not
    exist". Those customers weren't in X3 yet, so X3 tried to create them from the three
    delivery-address fields.

  Wait for each import to finish, read its log, then load the next. Reloading BPCDL afterwards is safe.
- **COALESCE over Access text columns:** Access often stores "nothing" as '' not NULL, so
  `COALESCE(a, b, c)` stops at an empty b. NULLIF every candidate:
  `COALESCE(NULLIF(a,''), NULLIF(b,''), c)`.
- **Supplier rejections cascade:** a rejected supplier takes its product-supplier rows, open
  items and purchase orders with it. Load suppliers first and read the log.
- **Linked folders in the transaction chain hold the 27 Oct set** (`out_v8`, `tmpl_t2`,
  `uploads_tmpl5`). Use them for templates only, never data. `build_sheets.py` read the works
  orders from `out_v8/YA004MFG_load8_works_orders.txt`, so the first evening build had 27 Oct's
  638 works orders. It was caught because the change report showed 0 changes. It now reads that
  run's `out_mfg/YA004MFG_load7_clean_run.txt`. **A file showing no change after a week is a
  question, not good news.**

---

## 12. How to rerun

**Being replaced by the rebuild kit in `rebuild/` (from 31 Oct):** read-only extract SQL plus one
run that rebuilds every complete file from current Access data and writes `WHAT_CHANGED.md`
against the previous run. See `rebuild/README.md` for status. Until each part is in the kit, the
steps below still apply.

**Products are in the kit (31 Oct):**
1. Run `rebuild/sql/extract_products.sql` on SDILive (read-only, temporary tables only). Save it
   with Results To File, tab delimited, as `<run>/extract/extract_products.txt`.
2. `python rebuild/run.py <run> --previous <last loaded set> --today <yyyymmdd>`.
3. It writes the complete `ZSDIITM_products_MAPPED.xlsx` and `WHAT_CHANGED.md`.

The product rule is rule 1a, written into `products.py`. A product goes in if it does any of these:
- holds stock;
- is on an open sales, purchase or works order;
- was sold, bought or made in the last 2 years;
- is graded GOOD or INCOMPLETE;
- is a component, at any depth, of a BOM that goes in.

Every other product is on the "Not migrated" tab with its last activity. The run stops if a
stocked or ordered product, or a BOM component, is left out. PHANT uses the usage test (`--phant
access` keeps vw_ITM's category). Tested on the original vw_ITM data: it reproduces the loaded
file, apart from the 137 V6 additions that weren't in the test data and 108 descriptions it
keeps longer, within 30 characters.


1. **Fresh extract** (all on one day): views_v2.sql export grids; bins_and_delivery.sql grid
   1; product_suppliers_v3.sql grid 2; works_orders_extract.sql grid 2; plus the cleansed
   product, BOM, route and cost source files. For the product-suppliers, `product_suppliers_v4.sql`
   (v3 with the new supplier codes inline, read-only). `product_suppliers_new_only.sql` gives just
   the products bought from the new suppliers, and `scripts/build_itmsup_new_suppliers.py` merges
   that into an existing ZSDIITMSUP file.
2. **Cross-reference:** rebuild `xref_sage_codes.sql` with `scripts/make_xref_inserts.py`
   (V4 suppliers, V7 customers) and run it. Then run `add_new_accounts_to_xref.sql` (the 86 + 83
   new accounts, which xref_sage_codes.sql drops; only migration tables change), then `views_v2.sql`.
   Check the first grid of `export_orders_and_invoices.sql`: 86 and 83 new accounts, and the
   "still dropped" counts only for accounts left out on purpose (27 Oct: 56 SO lines, 1 BICX item).
   Then export its four grids. On 27 Oct the xref update had not gone in, so the new accounts'
   rows came from the read-only `export_new_accounts_orders_invoices.sql` instead (section 4.2).
3. **Product side:** `standardise_v3.py` aligns routes, costs and BOMs to the product file
   and splits BOMs into loadable and held back. Then `build_v7_fixes.py` applies the code
   rule, supplier VAT, customer fixes, product-suppliers and delivery addresses.
4. **Master data:** `build_v8_track2.py` applies the character rule, duplicates, tax rules,
   bought-in BOM and route holds, and runs every check as an assertion.
5. **Opening transactions:** `map_bins.py`, then `build_mapped_guides.py` and
   `populate_guides.py` (the five guides, SOHPJ columns, dates, characters). **Set
   `STOCK_DATE=<load day yyyymmdd>`** for the stock posted date; `OUT_DIR` builds to another folder. Then
   `recode_ledgers_v7.py` for the clean-run product codes, `build_mfg.py` for works orders, and
   `build_bicy_bisy.py` (with `COMPANY=S01A`) to turn BICX / BISX into the BICY / BISY layout.
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
| YA004BPS_suppliers_MAPPED | 706 (623 + 83 new) |
| YA004BPC_customers_MAPPED | 6,169 rows (217 + 86 new customers) |
| YA004BPCDL_delivery_addresses_MAPPED | 6,169 |
| ZSDIITM_products_MAPPED | 16,499 |
| ZSDIITMSUP_product_suppliers_MAPPED | 8,644 (965 added, 54 changed for the new suppliers) |
| YA00408BOM_boms_MAPPED | 30,131 |
| ZSDIROU2_routes_MAPPED | 31,255 |
| YITC_product_costs_MAPPED | 9,597 |
| YA004MFG_works_orders_MAPPED_clean_run | 638 |
| YA004SMR_guide_MAPPED_clean_run | 6,303 lots, £3,437,532.29 |
| YA004POH_guide_MAPPED_clean_run | 579 lines (479 + 100 new suppliers') |
| YA004SOHPJ_guide_MAPPED_clean_run | 3,161 lines (2,012 + 1,149 new customers') |
| YA004BICY_guide_MAPPED (was BICX) | 817 items, £8,788,291.72 (+230, £3.54m). Company = C01; B and N swapped (3 Nov) |
| YA004BISY_guide_MAPPED (was BISX) | 2,280 items, £6,953,942.83 (+253, £0.84m). CURLED removed; Company = C01; B and N swapped (3 Nov) |

Data: everything from the 21 Oct export, except the new accounts' rows, which are from 27 Oct.
The real load needs one fresh extract of everything, on one day.

**Known gaps. Nothing else is known to be missing; these are:**

| Gap | Size | Where it shows | Status |
|---|---|---|---|
| Live products graded OLD (section 6.1) | 1,681 products: 1,473 with stock, 250 on open orders | SMR Held back: 2,176 lots, £603,151. SOHPJ Held back: 418 lines. POH Held back: 204 lines | **Must be fixed before go-live (James, 27 Oct).** Rebuild the complete product file with them in (rule 1b, no top-up file), and make sure their stock comes through in SMR. Stock in X3 has to match Access |
| Order lines with a negative value (a credit on an order) | 4 SO lines, 1 PO line | SOHPJ / POH Held back | X3 needs a credit note. SDI to decide |
| Accounts left out on purpose | Customers: 4 intercompany, ESD01, FSC01, IBS01 (no address). Suppliers: 72 employee expense accounts, 6 non-suppliers | Customers_to_add.xlsx, Suppliers_to_add.xlsx. Their 56 open sales order lines and 1 customer item are not loaded | Finance to confirm |
| Product-supplier links for products not in the product file | 575 products (106 bought in 2026; products_bought_2026_not_loaded.sql has their grades) | not loaded | Follows the OLD products decision |
| Alternative suppliers | 3,150 | not loaded: the template has no priority column | Ethan: a PIO column |
| VAT numbers missing | 221 accounts: 194 suppliers (185 dummy numbers removed), 27 customers | `VAT_numbers_needed.xlsx` (out_sue), with a column for the correct number | **Push back on the users / Finance for the real numbers** (27 Oct). Don't load dummies again |
| Products with no standard cost (YITC) | 6,902 of 16,499: 3,522 bought (RAWML / FGSL), 3,380 made (FGML / PHANT). 860 hold stock (£1.86m at lot cost). E.g. FIXING49, FIXING29, FIXING2685, FIXING443, PLASCOAT002, PLASCOAT004 (30 Oct) | YITC has only 9,597 costs: the cost source covered only products with an Access cost | A cost is available for 2,689 bought products: the stock lot cost (655) or the last purchase price (2,034). 833 bought products have none. Made products: ask Marc whether X3 rolls their cost up from BOM and route |
| Rows held in Track 2 | 33 shared product codes, 12 BOM lines, 71 route lines, 28 costs | V8_track2_report.xlsx | SDI decisions below |

**Waiting on Marc:** whether October is open in UAT; the go-live date; carriage as lines or
invoice element; the ship-to field on SOHPJ; static data (999100, 999200, 18L, payment terms,
EUR/USD); the 27 suggested bins, A001 and the racking; whether YA004ITM
replaces ZSDIITM.

**Waiting on Ethan:** DIE/CCE field names; the X3 lot
export; the tax rules for UAT; BOMs and routes on bought-in products; route use status 1 or
10; the sub-assembly code in operation descriptions; a PIO column on ZSDIITMSUP; S500; the
works order questions; clean-run error logs.

**SDI decisions:** which product keeps each of the 33 shared codes; the 14,304 products BOMs
use but the load leaves out; real VAT numbers and EU tax rules (finance); credits on sales
orders; the multi-drop store allocation; the bought-in products with no supplier (fewer now: 965 were the new suppliers' products);
the live products graded OLD; the employee expense and intercompany accounts left out.

**Confidentiality:** when emailing suppliers, email yourself and put the recipients in BCC,
never CC (Claire Newall). Supplier and customer lists are not kept in git.

---

## 14. Fixes applied – both tracks, file by file

**This is the summary of every improvement made to each mapped spreadsheet. Keep it current:**
add each new fix here the day it's made.

Counts are from the 21 Oct – 4 Nov builds. They will move with each fresh extract, but the
fixes themselves are what every rerun must repeat.

**Applies to every file (from 31 Oct):**
- Complete files only, never a top-up (rule 1b).
- A `;` load file built from each saved spreadsheet, in the format of the V1.3 files James
  loaded (rule 1c).
- No exclusions by assumption (rule 1a). **Zero prices and costs are never a reason to leave
  anything out (4 Nov check).** Rows at zero, all loaded: 15,154 products (base price), 602 SO
  lines, 22 PO lines, 241 stock lots, and 937 costs (loaded at 0 since 2 Nov).

### Track 1 – opening transactions

| File | Fixes applied |
|---|---|
| **YA004SMR** opening stock | Mapped column for column to the template. **Description (column E) = the product code, the product key on each line. Posted Date (column D) = 20261031 for Run 3, the last day of the previous period (Ethan, Run 2; was 20261028); 20261231 at go-live**, on the Held back tab too. Full lot cost (material + labour) from the lot records. Product codes as loaded. **Locations:** every Access bin mapped to Marc's list (437 exact, 253 by rule, 27 suggested, 1,213 to A001); 2,317 lots on a real location, 3,986 in A001. **Supplier lots:** 232 cleaned, spaces to hyphens. Held back 2,176 lots (£603,150.76) whose product is not in the product load. Clean run: 131 product codes changed to the V7 codes. |
| **YA004SOH → YA004SOHPJ** open sales orders | New template: Dim Code (DIE) = D02 and Dimension (CCE) = P00003 added between Header text and Line (22 columns). **Dates:** 293 lines with a ship or delivery date before 2025 moved to 20261031; 64 lines shipping before their order date given the requested delivery date; order dates unchanged; header dates the same on every line of an order (253 lines). **Text:** 145 cells cleaned to Ethan's rule; 878 blank descriptions filled from the product file. Lines renumbered from 1000 per order (271); 30 orders rearranged so identical headers are never adjacent. Units to EA, £ to GBP, outstanding quantity, discounted price. Held back 200 lines, including the credits on orders (£93,241.98). Clean run: 47 product codes changed. |
| **YA004POH** open purchase orders | Mapped to the template. **Text:** 36 descriptions cleaned (M&S-TOOLING → M AND S-TOOLING). 272 blank descriptions filled. Lines renumbered (33), 26 orders rearranged. Held back 193 lines. Clean run: 5 product codes changed. |
| **YA004BICX → BICY** customer open items | Mapped to the template. Outstanding balances, positive values, £ to GBP, Sage customer codes via the cross-reference, repeated references suffixed. Reconciles to Access to the penny. The character rule found nothing to change. **28 Oct:** renamed BICY; Company column added at D. **3 Nov:** Company = C01; Document and Source Document swapped as Acuity did, with every Document kept unique (160 suffixed; the 18 receipts and journals with order number 0 take the invoice number). **27 Oct:** +230 items for the new accounts. |
| **YA004BISX → BISY** supplier open items | **3 Nov:** Company = C01; Document and Source Document swapped, every Document kept unique (454 suffixed). **28 Oct:** CURLED removed, Company added at D; 317 blank Source Documents filled with the document reference. As BICX, plus CURLED = GBP (removed in BISY). **References:** 84 document references with spaces or / cleaned (2026158/77 → 2026158-77), still unique. 3,134 text cells tidied (dashes, double spaces). A 23-column version without CURLED exists in case X3 rejects it. |
| **YA004MFG** works orders (new) | 638 of the 744 open Access works orders, one line each. Quantity = ordered less made. Start = created date. End = scheduled date (13 that ended before they started now end on the start date). Held back 106: 36 with nothing left to make, 42 with no BOM, 25 not a product (all 16 prototypes), 3 with no route. Clean run: 42 codes changed. |

### Track 2 – master data

| File | Fixes applied |
|---|---|
| **YA004BPS** suppliers | **4 Nov (`scripts/fix_suppliers.py`), Run 2's FR rejections:** 3 VAT numbers restored from Access: GAL500 → FR65572062594, ICE500 → FR73539546192 and BUR500 → FR96790182786. All pass the French key and SIREN checks. 11 supplier postcodes moved out of the address lines (continental order; 22 field changes). The other 8 have nothing valid in Access. Each is listed on "Supplier check" with what Finance must supply: EECNUM; CRN = the 14-digit SIRET, whose 5-digit site number isn't in Access; BAL500's tax rule DOM; PLS500 is ES with a GB number. **VAT:** 186 dummy numbers blanked. These were two Polish numbers copied across 117 suppliers, TEMPJAF placeholders, and GB numbers on overseas companies; they were the cause of the 180 rejections in UAT. **Tax rule:** 28 suppliers on EU set to ROWS. **Text:** 211 name and address cells cleaned. Address flag 2 on all (already right). A reload file of the 179 rejected suppliers was made for UAT. |
| **YA004BPC** customers | **4 Nov (`scripts/fix_customer_addresses.py`), Run 2's XPOSCOD / XSAT rejections: 507 address fixes by rule, on every customer** (223 on the six X3 rejected), each listed on "Address fixes"; rules in section 6.5. **1 address left to check.** First pass, for the record:
  - postcode moved out of the address lines, 120;
  - GB postcode O/0 or I/1 confusion and spacing, 12, only where one reading is valid and the district is unchanged;
  - text removed from the postcode, 13, with a US / AU state code kept as the State/Region;
  - country corrected, 55: Dublin Eircodes and districts to IE (D15), a country named in the address or typed as the postcode;
  - phone brackets removed, 2;
  - State/Region with ISO codes, 14: CA from the postcode letter, AU / US from the postcode range, AE emirate from the address;
  - AE PO boxes moved out of the postcode, 4.
  10 addresses left on "Address check". The X3 field code and region codes for "County / region" are asked of Ethan. **Tax rule:** the 10 EU customers (56 address rows) set to ROW / ROWC, as UNI100. **VAT:** ROL100's 8-digit number blanked. **TEC100:** postcodes moved out of the address lines (POSCOD error). **Two rows** split by a semicolon between emails put back to 34 fields. **Text:** 367 cells cleaned. Address flag (AG) checked: 001 = 2, others = 1. |
| **YA004BPCDL** delivery addresses (new) | 2,268 rows, one per customer address. For customers with several addresses the name is built from company + store line + postcode, within 30 characters. Built from the cleaned customer file. |
| **ZSDIITM** products | **4 Nov, first live run of the rebuild kit** (`extract_products.sql` + `rebuild/run.py`): **19,868 products, +3,369, 0 removed.** The new products cover 1,412 holding £585k of stock, 358 on open SOs, 97 on open POs, 50 on works orders, 1,954 bought, sold or made in the last 2 years, and 525 BOM components. 2,078 of them were graded OLD and 1,001 REVIEW. Of the held-back transaction rows, 2,080 of 2,176 stock lots, 359 of 406 SO lines, 201 of 205 PO lines and 20 of 25 works orders now have their product; the rest have no stock or open order in Access today. PHANT usage test: 534 to FGML (97 sold, 437 stocked or made). Description 3 filled from PMA_DESC_3 on 10,701 loaded products. 52 description changes are Access edits since October; one looks wrong in Access ("OS OS" on BCR-12503-00-GA). **Already loaded = always stays** (register 22). 22 live products hidden by a shared code are on Check (register 23). **4 Nov, earlier: 1,653 descriptions filled.** Where description 1 was only the code (sub-assemblies, "zombie" parts: "10074-02-SA01" → "BASE WELDMENT"), it takes description 3, then 2 (`scripts/fill_product_descriptions.py`). The other 100 wait for PMA_DESC on the product extract. **Codes (V7):** 451 changed, 160 because of a symbol, 291 only to upper case, with no new duplicates. **Descriptions (V8):** 4,426 cells cleaned (Dowel£s → Dowels, £ per 1000 → GBP per 1000, 50° → 50 deg, & → AND). 68 blank descriptions filled. 137 missing in-use products added (V6). Held back 33 rows: a code on two products. |
| **ZSDIITMSUP** product-suppliers (new) | **4 Nov (`rebuild/product_suppliers.py`): 14,729 pairs, every supplier with a PIO priority:** 10,838 main and 3,891 alternatives (+6,087). 2 pairs gone, both because Access changed the PO line since 22 Oct. 4,148 pairs held, all for products not migrated (no activity). Earlier: | 7,679 products with their main supplier, from purchase history since Sept 2022. 3,150 alternatives held for a priority column. The cause of the blank suppliers in planning: 2,143 rows belonged to the 179 suppliers rejected on VAT. |
| **YA00408BOM** BOMs | **V6:** every code rewritten to the product file's spelling, Excel damage repaired, lines split into loadable and held back. 33,596 held: parent or component not in the product load (14,304 products). **V7:** 10 recovered by the code rule. **V8:** 11 lines on bought-in FGSL products held, 1 exact duplicate dropped, 1 clashing sequence moved on. 92 BOMs load with a component missing (listed). |
| **ZSDIROU2** routes | Work centres checked against X3's list: all 31 used are X3 codes, and each operation is on the right type of centre. 4,607 operation descriptions cleaned (P/C → P-C). 71 lines on 36 bought-in products held. Use status 1 kept (guide example; asked Ethan). |
| **YITC** product costs | **4 Nov (`rebuild/costs.py`): 19,868, one per product.** Loaded costs are kept (15,562). New products: Access material cost 2,523, stock lot cost 352, last purchase price 15, BOM roll-up 4, 0 on Check 475. 232 products loaded at 0 now carry an Access cost. 1,180 at 0 in all, 161 of them stocked. The RATE grid came back empty, so EUR / USD use Access's 30 Oct ledger rates. **2 Nov: a cost line for every product, 16,499** (Run 2 loaded 9,597). Sources, in order: Access standard cost 9,597; stock lot cost 778; last purchase price 2,049 (393 EUR / USD at Access's own ledger rate); BOM roll-up 3,138; **no cost in Access, loaded at 0, 937** (73 of them hold stock), all on Check. Codes aligned to the product file and Excel damage repaired (V6). Confirmed all under material (cost type 1). 28 second costs held, for codes that were on two products. |
| **YA004BPSC** supplier banks (new, 28 Oct) | 626 BACS suppliers. BIDNUM = "XXXX" + 6-digit sort code + 8-digit account. 37 on Check. Confidential: kept in the restricted bank folder, never in git or e-mail. `.txt` written 3 Nov. |

### Mapping and cross-reference work behind both tracks
- **Customer and supplier codes:** the cross-reference was rebuilt by name against the loaded
  files: 623/623 suppliers, 217/217 customers. The old CUS1001/SUP1001 numbering was dropped.
- **Product codes:** one rule everywhere (section 4.1). V6 aligned all product-side files to
  the product master; V7 removed every symbol; V8 cleaned descriptions.
- **Stock locations:** Access bins to Marc's 2,470 X3 locations (section 7).
- **Work centres:** checked against X3's 33 (section 8).
- **The old migration views** were rewritten (views_v2.sql): price-per divisor, order filter,
  site, date format, stock cost source, currency rule.
- **Missing live accounts (27 Oct):**
  - 86 customers and 83 suppliers added, with their addresses, product links, open orders and invoices (section 4.2);
  - existing rows unchanged in every file;
  - left out on purpose, for Finance to confirm: intercompany, ledger and employee expense accounts.

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
| **YA004BPSC_guide.xlsx** | Ethan, 28 Oct | Supplier bank details: BPSNUM, BPAADD, CRY, BIDNUM (XXXX + sort code + account), PAB1, BICCOD, PAB2 blank, CUR, BIDNUMFLG 2. BACS suppliers only | Mapped (section 3); `supplier_bank_details.sql` + `build_bpsc.py`. Built 28 Oct: 626 loaded, 37 on the Check tab |
| **BICY / BISY layout** | James, 28 Oct | BICX and BISX renamed YA004BICY and YA004BISY; CURLED removed from BISY; new column Company between C (Customer / Supplier) and D (Site) in both | Built (`build_bicy_bisy.py`). Company = C01, the value that loaded in Run 2 (3 Nov) |
| **YA004BPCDL_guide.xlsx** | Ethan, 23 Oct (sent twice) | Customer delivery addresses: BPCNUM, BPAADD, BPDNAM. Load after customers | Built, 2,268 rows |
| **ZSDIITMSUP_Guide_V2.xlsx** | Ethan, 23 Oct (sent twice) | Product-suppliers: ITMREF, BPSNUM, ITMREFBPS (= product code) | Built, 7,679 rows; PIO asked |
| **YA004MFG_Guide.xlsx** | Ethan, 27 Oct | Works orders: 11 columns, BOM code and routing code 10, update code C, status 1. Example rows are illustrative, not live orders. Standard spreadsheet tools can't read its styles; it was read from the XML | Built, 638 orders; 6 questions asked |
| **X3 work centre list** (screenshot) | James, 27 Oct | 33 X3 work centres with group, type and title (section 8) | Routes checked against it: all match |

**Still to receive:** the X3 lot export (SMR); the field names for SOHPJ's two new columns; the IME column for BISX; clean-run
error logs; the original BPC and BPS template workbooks, to keep with this runbook.

---

## 16. Where the data stands, and the fixes for the next run (27 Oct)

### Better than where we started
- **Rejections fixed at the root:** the dummy VAT numbers (180 supplier rejections), the missing
  EU tax rule (10 customers), the postcode error, and the symbols in product codes that broke
  products, BOMs, routes and costs.
- **The extract is right:** the old views had a wrong price divisor, a filter that dropped most
  live orders, the wrong site and date format, stock at standard cost, and 97% of supplier items
  at zero. All of that was replaced by views_v2.sql, and BICX reconciles to Access to the penny.
- **One product code rule in every file.** Every file is checked against the product, customer
  and supplier files before hand-over.
- **Every file is a mapped spreadsheet on the template**, read back cell by cell.
- **The live accounts that were missing are in:**

  | | Before | Now |
  |---|---|---|
  | Customers | 217 | 303 |
  | Suppliers | 623 | 706 |
  | Customer open items | £5.25m | £8.79m |
  | Supplier open items | £6.11m | £6.95m |
  | Open sales order lines | 2,012 | 3,161 |
  | Open PO lines | 479 | 579 |
  | Product-supplier links | 7,679 | 8,644 |

- **The main open gap:** live products graded OLD (section 13, Known gaps).

### Fixes to make before the next run, most important first
1. **Product selection: migrate every live product. Required, not optional: every product with stock must be in the product file, and its stock must come through in SMR.** Change the OLD rule in
   `migration.vw_DQ_ITM` (our view, so allowed) so that stock on hand, an open PO or sales
   order, or a purchase in the last 24 months counts as activity. That brings in the 1,681
   products, the £603k of stock and about 620 order lines. Then their stock, orders, BOM lines and
   product-supplier links come through with no extra steps.
2. **Customer and supplier selection: migrate every live account,** whatever the grade.
   - Build the new accounts into the base customer and supplier files, not as an add-on.
   - Make the new account pairs manual pairs in `xref_sage_codes_TEMPLATE.sql`, so the separate
     `add_new_accounts_to_xref.sql` step goes away.
   - Keep the codes already given out: TIE02E = TEC103, TIE02POL = TEC104.
3. **Views: never drop a row without saying so.** Change the four order and invoice views from
   JOIN to LEFT JOIN on the cross-reference and return the Access code. `populate_guides.py`
   already holds back "Account is not in the customer/supplier load", so missing accounts show
   on the Held back tab, not vanish. Keep the section 9 STOP check.
4. **Check Track 1 against the clean-run files.** `populate_guides.py` checks products against
   the UAT product file (`uploads_final/ZSDIITM_Cleansing.txt`), and accounts against the loaded
   files unless `CUSTOMER_FILE` / `SUPPLIER_FILE` are set. Point all three at the final clean-run
   files.
5. **One extract, one day, for everything.** Today's files mix 21 Oct and 27 Oct data. Also make
   the "Data exported ..." date in the guides' Notes a parameter, not fixed text.
6. **Apply the new-account address rules to all customers and suppliers:**
   - split run-together Access address lines (the first customer file has
     "OAKWOOD DISTRIBUTION LTDGREAT BANK ROAD");
   - take the country from the address where Access says GB (994 addresses on the new customers alone);
     350 rows still have GB with a non-UK postcode (27 Oct file): mostly TTI store addresses with
     German postcodes (TEC106 / TEC118 140 each), plus TEC105 152 "77990FRAN". X3 accepted the
     same pattern on the first pass (TES101 "LE5", PER100), so they load, but the country is
     wrong. Detect the country from the postcode format and the town as well as from a country
     line;
   - the character rule on postcodes too: TEC122 002 / 003 have "FOT 2151" with an accented O;
   - move UK postcodes out of the address lines;
   - make delivery descriptions unique;
   - VAT numbers only with a valid country prefix.

   This is `build_new_customers.py` / `build_new_suppliers.py` logic, to run on the whole file.
7. **VAT numbers: push back on the users.** Send `VAT_numbers_needed.xlsx` (221 accounts) to
   Finance or the account owners and load their answers. Never put a placeholder in a VAT field.
   A blank loads; a dummy is rejected or, worse, accepted as wrong.
8. **Load time.** The full customer file (6,169 rows, one per address: Marks & Spencer plc alone
   has 1,207) took over an hour in UAT on 27 Oct. Records were being created; X3 builds every
   address. For go-live:
   - allow the time in the cut-over plan;
   - always load the complete file (rule 1b). Ask Marc how the import treats rows for records that already exist (skip or update);
   - ask Marc whether rows for existing customers are skipped or updated, and whether the import
     can run faster (for example without the address checks).
9. **Product category PHANT is set mechanically.** In `migration.vw_ITM` a product is PHANT if
   it's a BOM parent and also a component anywhere in Access's BOM table, including old BOMs
   that aren't migrated. Example: 9758-00-GA (MASTER TILL ASSEMBLY, £2,285, sold to PER100) has
   its own BOM (22 lines) and route (5 joinery operations). It's on 10 open sales order lines but
   is PHANT, only because two unmigrated BOMs (STDTPSSTORE001, TPS-9758-GA2) use it.

   Of 3,427 PHANT products:
   - 298 are on open works orders;
   - 127 hold stock;
   - 32 are on open sales orders;
   - 138 aren't a component of any migrated BOM.

   **Ask Marc / Ethan what PHANT does in X3.** If it's a true phantom (not stocked, exploded into
   the parent's works order), those products need to be FGML.

   **The test (28 Oct, `PHANT_review.xlsx` in out_sue lists all 3,427):**

   | Group | Test | Count | Category |
   |---|---|---|---|
   | A | Part in its own right: on an open sales order, or not used in any migrated BOM | 165 | FGML |
   | B | Stocked / made sub-assembly: used in a migrated BOM, but holds stock (£24k) or has its own open works order (292) | 367 | not PHANT: FGML, or a sub-assembly category if X3 has one (Marc) |
   | C | Used only inside BOMs, nothing on hand or on order, but has a supplier | 13 | check: RAWML / FGSL |
   | D | True phantom: used only inside migrated BOMs; not sold, stocked, made on its own or bought | 2,882 | PHANT |

   Rule for the next run: set the category from this test in the product build, not from
   "parent and component anywhere in Access". The files have no sales history beyond open
   orders, so a product sold in the past but not now falls to B or D; add last-sold to the extract.
10. **Decisions to get before the run:**
   - Finance: employee expense accounts and intercompany; EU tax rules.
   - SDI: the 33 shared product codes; credits on orders; the OLD-product stock if rule 1 isn't adopted.
   - Ethan: a PIO column for alternative suppliers.
   - Marc: service items (installation, delivery, tooling) and the multi-drop ship-to.
11. **Queries:** read-only against Access; narrow to the codes needed before any join or total;
   check brackets and REPLACE arguments; say what a query changes at the top.

---

## 17. Run 2 results, and Run 3 (4 Nov)

### Run 2, 27–28 Oct: what X3 rejected (Ethan's notes, 28 Oct)

| File | Errors | Cause | Fix | Owner |
|---|---|---|---|---|
| ZSDIITM, YA004BOMP, YITC | 0 | – | – | – |
| ZSDIROU2 | 32 | "Table is full 150": the X3 screen holds 150 operations | Widen the screen | Marc / Ethan |
| YA004BPS | 22 | 10 FR suppliers have no EECNUM (intra-EU VAT number) or CRN (SIRET), which X3 needs for FR. PLS500 is ES with a GB VAT number. BAL500 is FR on tax rule DOM | Finance to supply the numbers; never a dummy | James / Finance |
| YA004BPC | 6 | XPOSCOD postcode format: TEC100, TEC105, UNI103. XSAT missing State/Region: DRE100, MAR101, PER101 | Fix the addresses (register 20) | James |
| YA004BPCDL | 1,400+ | Every one belongs to the six customers above (1,425 addresses; MAR101 alone has 1,205) | Clears once the six load | – |
| ZSDIITMSUP | 22 | Error messages wrong; the records loaded | Ignore | – |
| YA004MFG | 3 | Possibly wrong messages | Acuity to investigate | Ethan |
| YA004POH | 3 | Supplier BAL500 missing (failed in BPS) | Clears with BPS | – |
| YA004SOHPJ | 900+ | "Sales product missing" on PHANT products. 32 PHANT products are on 82 open lines: sold, so not true phantoms (usage test, group A) | FGML, part of the PHANT decision (SCRUM-168) | Marc / Ethan |
| YA004SMR | 1,500+ | "Product not in managed stock" on FGSL products: 451 products, £1.72m | Make FGSL stock-managed (register 21) | Marc / Ethan |
| YA004BISY | 5, then 12 | Blank Source Document (Acuity filled BLANK); then SOG500 and BAL500, which failed in BPS | Blanks were already fixed in our build (the 317, section 3); suppliers clear with BPS | – |
| YA004BICY | 0 | Acuity added Company = C01, and swapped NUM and BPRVCR | Both now in our build (section 3) | – |

Acuity also noted for SMR: Posted Date (IPTDAT) "probably needs to be the last day of the
previous period". For Run 3 that's **20261031**, the same as the accounting date. Go-live stays
20261231.

### Run 3, 4 Nov: the plan (Acuity, 3 Nov)
- **RTZ on all transaction data. Master data stays** (products, customers, suppliers ...).
- Import any missing master data, to make it as clean as possible: the failed suppliers and
  customers above.
- Imports: BPSC, BICY, BISY, SOHPJ, POH, MFG, essentially every opening-transaction import, with
  the Run 2 errors fixed.
- Then reconcile the opening transactions with Jim, to judge their quality and find what's missing.

### Run 3: the extract and build, on the day (replaced 4 Nov: see the next section)

**Superseded.** `views_v2.sql` no longer outputs the data grids (it now ends with checks). Built
as below, the transactions would have had no stock grid and the other grids in the wrong
positions. Use "Opening transactions from a live extract" below.

### Opening transactions from a live extract (4 Nov; use this)

**One morning, three scripts on SDILive, one command:**
1. `sql/add_new_accounts_to_xref.sql`. It changes only `migration.XREF_*` and is re-runnable. Its
   checks should show 86 customers and 83 suppliers.
2. `sql/views_v2.sql`. It changes only `migration.` views and ITM_LOOKUP. Its output isn't needed.
3. `rebuild/sql/extract_transactions.sql`, **only after step 1 has committed** (its last line
   reads "AFTER COMMIT 86 83 0"). Run before the commit, its CHECK grid reads 0 / 0 and about
   1,900 rows are dropped: the 17:06 run on 4 Nov. Read-only. Save the **whole** output, Results To File,
   tab-delimited, as `<run>/extract/extract_transactions.txt`. Its labelled grids are:
   - CHECK: new accounts in the cross-reference and rows dropped for want of an account (the STOP check);
   - TOTALS: the control totals for the reconciliation;
   - SOH, POH, SMR, BICX, BISX, WOR: the data.

Then `python scripts/run_transactions.py <run> --stock-date 20261031`. `<run>/out` must hold the
day's product build (`rebuild/run.py`), so the transactions use exactly that product file's codes.

It runs the proven chain unchanged (map_bins → build_mapped_guides → populate_guides →
recode_ledgers_v7 → build_mfg → build_bicy_bisy → build_sheets) in a fresh `<run>/work` folder.
Reference files are generated from the product build, replacing the old UAT product lists. It
writes the six spreadsheets with their `;` load files, `RUN_SUMMARY.md` (the checks, control
totals, rows and held-back reasons per file) and the change report.

**Tested 4 Nov on the old (21 Oct) extract, to prove the chain:**
- the products from the 4 Nov build cut what's held back: stock lots 2,176 → 83 (8,396 lots load);
  PO lines 205 → 3 (781 load); SO lines 422 → 18 (3,565 load; 17 of the 18 are credits on orders);
- BICY and BISY come out identical to the current set;
- the SO and PO lines that differ are renumbered (new lines on the same orders) or carry a
  filled description. None is lost.
- Works orders: 66 are held for "no BOM", because new products have no BOM in the BOM file until
  the BOM part of the kit is built (SCRUM-164).
**The transaction data must be extracted on the day.** The files built so far come from the
21 Oct extract (`run1/out.txt`) plus the 27 Oct new-accounts export. A reconciliation against
today's Access would fail on everything that has moved since.

On SDILive, in this order (each script says what it changes):
1. `sql/add_new_accounts_to_xref.sql`. Changes only `migration.XREF_*`. Its checks must show
   86 customers and 83 suppliers added. On 27 Oct it hadn't been run, so the new accounts'
   rows were dropped.
2. `sql/views_v2.sql`. Changes only `migration.` views and ITM_LOOKUP. Save the **whole** output
   with Results To File, tab-delimited: it's the `run1/out.txt` that `populate_guides.py` reads
   (grids 7–11). **STOP check:** its "dropped" grid must be 0, or only the accounts left out on
   purpose. The views still inner-join the cross-reference (register 4).
3. `sql/works_orders_extract.sql`. Read-only; save grid 2 as `wor/out.txt`.
4. `sql/bins_and_delivery.sql`. Read-only; grid 1 as `bins/out.txt`, only if bins have changed.

Then build (section 12, step 5), with `STOCK_DATE=20261031`:
`map_bins.py` → `build_mapped_guides.py` → `populate_guides.py` → `recode_ledgers_v7.py` →
`build_mfg.py` → `build_bicy_bisy.py` (C01, swap) → `build_sheets.py`.
BPSC comes from `bank_private/` (confidential; 626 rows; its `.txt` written 3 Nov).

**Before the imports:** the master-data fixes in `out_run3/Run3_master_data_fixes.xlsx`
(`scripts/run3_fix_lists.py`):
- the 11 suppliers and what each needs;
- the 6 customers and their 248 addresses to fix. Examples: GB postcodes with a letter O for a
  zero (SO21, SE1 0HX, CM12 0BP); Cyprus, Shanghai and Dublin addresses marked GB; postcodes left
  in the address lines;
- the 451 FGSL products with stock;
- the PHANT and RAWML products on open sales orders.

**What RTZ means:** "Reset To Zero", Sage X3's reset of transaction data (RAZ, *remise à zéro*,
in the French product). It deletes the transactions for the company or site: stock, orders,
works orders, open items and journals. Setup and master data are kept. For Run 3 this means:
- the opening transactions load again **complete**, which suits rule 1b;
- master data is **not** reloaded. Any fix to a product, customer or supplier (descriptions,
  PHANT / FGSL categories, costs, the 6 customers, the 11 suppliers) has to go in by an update
  import or by hand. Ask Marc whether an import updates an existing record or skips it.
- **Products missing from X3 come first:** every stock lot, order line or works order on a product
  X3 doesn't hold fails again (section 18, item 1).

**Run 3 master data from the extract (4 Nov).** Run `rebuild/sql/extract_products.sql` and
`sql/product_suppliers_v4.sql`, saved as `<run>/extract/extract_products.txt` and
`product_suppliers.txt`. Then:
`python rebuild/run.py <run> --previous <current set> --previous-costs <current YITC> --suppliers <current BPS>`.
It builds three complete files, each with its `;` load file and the change report:
- **ZSDIITM:** every live product, including the OLD ones holding stock, live do-not-use / archived
  products, PHANT by the usage test, and descriptions from PMA_DESC;
- **YITC:** a cost line for every product; a loaded cost is kept, a new product is costed from Access;
- **ZSDIITMSUP:** every supplier pair with a PIO priority.

**First live run, 4 Nov (`runs/2026-11-04`):** done. ZSDIITM 19,868 (+3,369), YITC 19,868, ZSDIITMSUP
14,729. The change report against the current set is in `WHAT_CHANGED.md` and `What_changed.xlsx`.

**Words used with Acuity:**
- **FGSL** = Finished Good, Sold, bought in: a product SDI buys and resells without making it. It's
  one of the four X3 product categories in the template guide: FGML (finished good, made), FGSL
  (finished good, bought in), RAWML (raw material, bought in) and PHANT (sub-assembly). In the
  product file a product is FGSL when it's in no BOM, neither as a parent nor as a component.
- **The FR numbers** = the two identifiers X3 requires on a French supplier:
  - **EECNUM**, the intra-EU VAT number: "FR" + 2 check characters + the 9-digit SIREN, e.g.
    FR12345678901;
  - **CRN**, the company registration number: the SIRET, 14 digits (the 9-digit SIREN plus a
    5-digit site number).
  Both are on the supplier's invoices and letterhead. Finance supplies them; they're never made up.

**Learned 3–4 Nov:**
- **X3 numbers documents itself:** type, site, sequence, e.g. PIN-S01A000015 (purchase invoice;
  creation author ASL = Acuity's user) and MFG-S01A000001. Those numbers are never in our files,
  which carry the Access references. To trace one back, take its supplier, amount and source
  document from X3. Asked Ethan what X3 uses the NUM column for (section 3, BICY).
- **Routes over 150 operations:** only 2 of 6,348, TES-4495-00-08 and TES-4495-00-12 (162 each).
  They caused Run 2's "table is full 150". The screen needs about 170.
- **BPC hand fixes in the loaded V1.3:** James fixed 2 lines by hand: GAL100 phone "0046 (0)
  470705100" → "0046 0 470705100", and TEC105 address 152's postcode "77990,FRAN". The customer
  build must apply both itself: brackets out of phone numbers, and a postcode with no country
  text.
- **The current mapped set** (`Current_mapped_set_2026-11-04`) was checked line by line against the
  files loaded in Run 2:
  - identical: ZSDIITM (before the 4 Nov descriptions), BPCDL, POH, SOHPJ, MFG;
  - different: YITC, BPC (the 2 hand fixes), SMR (columns D and E), BICY and BISY.

### Run 3 build from the evening extract (4 Nov, 18:40)

`add_new_accounts_to_xref.sql` ended "AFTER COMMIT 86 83 0". The rerun of
`extract_transactions.sql` at 18:39:59 showed:
- new accounts 86 / 83;
- dropped rows 56 SO lines / 4 PO lines / 5 customer items / 16 supplier items: the accounts left
  out on purpose.

`extract_products.sql` was run the same evening. Built in
`Current_mapped_set_2026-11-04-pm` (scratchpad):

| File | Rows | Held back | Ties to |
|---|---|---|---|
| ZSDIITM / YITC | 19,883 | 129 (code on two products) | +15 products since the morning, 0 removed |
| ZSDIITMSUP | 14,746 | 4,148 | +17 pairs |
| YA004SMR | 8,621 | 0 | 8,621 lots, £4,090,220.20 = Σ qty × price in the view (the control total £4,090,221.33 is per-lot values rounded to 2 dp: £1.13) |
| YA004POH | 733 | 1 (credit line) | 734 lines |
| YA004SOHPJ | 3,712 | 16 (credit lines) | 3,728 lines |
| YA004MFG | 721 | 48 (38 nothing left to make, 9 no BOM in Access, 1 no route in Access) on the rebuilt BOMs and routes. 634 / 135 on the 27 Oct files | 769 open WOs |
| ZSDIROU2 | 33,499 operations, 7,094 products | 121 (routes on bought-in products) | Rebuilt 5 Nov from the live vw_ROU. The rules reproduce the old file from LOAD_ROU exactly. Of 6,347 routes in both, 6,318 are identical and 29 changed in Access; 747 are new. Access work centre OVEN (9 operations) has no X3 mapping; none is on a migrated product yet. 3 routes over 150 operations |
| YA00408BOM | 32,941 lines, 7,189 BOMs | 170 (155 no quantity, 10 component not a product, 4 exact repeats, 1 on a bought-in parent) | Rebuilt from ASC_BOM_TBL (`rebuild/boms.py`). Of the 6,333 BOMs in both files, 6,210 are identical in content; 856 BOMs are new |
| YA004BICY | 814 | 0 | 814 items, £8,506,050.44 (Σ of amounts, all types) |
| YA004BISY | 2,056 | 0 | 2,056 items, £6,813,472.18 |

The change report can't pair SMR, POH and SOHPJ rows, because the document number is blank: X3
numbers them itself. Their "added / removed" counts there are the whole file. Compare counts and
totals instead.

**Reconciliation (Jim):** `views_v2.sql` prints the control totals: customer and supplier
open items (count and GBP) and opening stock (lots and value, by warehouse). Tie each to X3
after the load. Any difference is a missing or merged transaction.

---

## 18. Everything held back or left out – review (4 Nov)

Under rule 1a, every item here needs a named decision or a fix. The figures are from the current
set. **Items 1–4 affect Run 3 directly.** **4 Nov evening:** the live build (section 17) cleared item 1 for the transactions. The figures now are SMR 0 held, POH 1, SOHPJ 16 (both credits, item 5), MFG 135 (item 6).

| # | What | Where | How many | Why | Revisit: what to do |
|---|---|---|---|---|---|
| 1 | **Products X3 doesn't hold** (live products graded OLD; do-not-use / archived products that are live) | SMR, SOHPJ, POH, MFG Held back; ZSDIITMSUP | **2,176 stock lots (£603k), 405 SO lines, 204 PO lines, 25 works orders; 6,265 product-supplier pairs on 5,689 products (1,752 bought since 2025)**. **4 Nov evening: 0. Every stock lot, SO, PO and WO line has its product** | Product not in the product file | **Run `rebuild/sql/extract_products.sql` and `sql/product_suppliers_v4.sql`, then `rebuild/run.py`. It builds the products, a cost for each and every product-supplier pair.** Import the missing products before the transactions. They're the "missing master data" for Run 3. Without them every one of these rows fails again |
| 2 | FGSL products with stock | SMR | 1,222 lots, 451 products, £1.72m | X3's FGSL isn't stock-managed | Marc / Ethan: make FGSL stock-managed (register 21) |
| 3 | Customers and suppliers X3 rejected | BPS, BPC, BPCDL, POH, BISY | 11 suppliers, 6 customers, 1,425 delivery addresses, 3 PO lines, 12 BISY items | FR numbers missing; postcodes; State/Region | **4 Nov evening: customer VAT gaps filled from Access addresses (24 customers; 56 of 303 now have one; 5 to check; section 6.5).** **Fixed as far as the data goes, 4 Nov:** customers, 220 fixes by rule with 10 addresses to check; suppliers, 2 FR VAT numbers restored, with the rest needing Finance. `sql/bp_identifiers_run3.sql` pulls every Access field for the 17 accounts, in case more is there. Assumptions and questions sent to Ethan. **Lesson: apply a fix the data settles the day it's raised; list only what genuinely needs someone.** The rules are in section 6.5. `bp_identifiers_run3.sql` is optional: it only looks for anything Access holds that we haven't mapped (a SIRET, a county) |
| 4 | PHANT products on open sales orders | SOHPJ | 32 products, 82 lines | PHANT has no sales data in X3 | **5 Nov, Ethan: PHANT stays PHANT, so these stay PHANT.** 91 open SO lines are on PHANT products and will fail as in Run 2, until Marc's workaround. Left in the file (James: Ethan's fixes only). `run_transactions.py --hold-phant` holds them back instead |
| 5 | Credits on sales orders (negative lines) | SOHPJ Held back | 16 SO lines and 1 PO line on 4 Nov evening (£93k on 27 Oct) | X3 takes a credit as a credit note, not an order line | Marc: raise them as credit notes, or Finance to confirm they're open |
| 6 | Works orders | MFG Held back | 5 Nov, after the BOM and route rebuilds: **38 nothing left to make, 9 no BOM, 1 no route** (of 769 open; 721 load) | No BOM / route to make them with, or already made | The 9 and 1 have no BOM / route in Access: SDI to add them or close the orders. The 38 are finished: close them in Access |
| 7 | Shared product codes | ZSDIITM Held back; YITC Held back | 129 on 4 Nov (was 33), **22 live** (register 23); 27 costs | Two Access products clean to one X3 code | SDI: which product keeps the code. Proposal: the other takes a suffix (-B) so neither is lost |
| 8 | BOMs and routes on bought-in products | BOM Held back; ROU Held back | 11 BOM lines; 71 route lines (36 products) | X3 builds and routes manufactured products only (Ethan) | Check each: if SDI makes it, the product is FGML, not FGSL / RAWML, and the lines load |
| 9 | BOM components missing | BOM Missing components | 215 lines on 92 BOMs | Component not in the product file | Clears with item 1 (components at any depth) |
| 10 | Components vw_BOMP drops by a hard-coded list | (never extracted) | 51 components | No reason recorded | SDI / Acuity: why. The kit reads ASC_BOM_TBL, so they come back unless excluded by name |
| 11 | Alternative suppliers | ZSDIITMSUP | 3,150 | The template has no priority column | **Done in the kit (`rebuild/product_suppliers.py`):** every pair goes in, in the template's three columns, main supplier first. The PIO column was rejected by Run 3's import (Ethan, 5 Nov), so the priority is kept on a tab only |
| 12 | Accounts left out on purpose | BPC / BPS, and their orders and items | Customers: 4 intercompany, ESD01, FSC01, IBS01. Suppliers: 72 employee expense, 6 non-suppliers. 56 SO lines, 1 customer item | Not trading accounts | Finance to confirm; the SO lines and item must be dealt with if they're real |
| 13 | Dormant accounts | not migrated | (none open) | No trade for 2 years, nothing open | SDI to confirm |
| 14 | Address text that didn't fit | BPC Check new accounts | 31 lines left out, 5 blank | Over three address lines | Fold into line 3 / 2 rather than lose it, or put the extra in the address description |
| 15 | Suppliers with no address | BPS Check new accounts | 19 | Blank in Access | X3 may need one; Finance / Purchasing |
| 16 | Supplier banks | BPSC Check | 37; 44 on transfer terms not loaded | Not BACS, or details incomplete | Ethan's template is BACS only; Finance to confirm the others |
| 17 | Accounts missing from the cross-reference | the order and open-item views (inner join) | 0 once `add_new_accounts_to_xref.sql` has run; the views' check grid shows it | Inner join drops the row | Switch the views to LEFT JOIN with a Held back reason (register 4) |
| 18 | Costs at zero | YITC Check | 4 Nov evening: 1,178 (159 stocked; Access values that stock at £0 too). Was 937 (73 stocked) before the 3,384 products added on 4 Nov | No cost in Access | Loaded at 0. SDI to supply a cost for the 159 stocked at least |
| 19 | Descriptions | ZSDIITM | 100 still only the code | No other text in the file | PMA_DESC on the product extract |

---

## 19. Where everything stands – 4 Nov 2026, evening

### 19.1 The current files

**`Current_mapped_set_2026-11-04-pm`** (scratchpad) holds every mapped spreadsheet with its `;`
load file, plus `Current_set_manifest.xlsx` (rows and source per file), `RUN_SUMMARY.md` and
`WHAT_CHANGED_2026-11-04-pm.md`. The morning set (`Current_mapped_set_2026-11-04`) is kept for
the comparison.

| File | Rows | Built from | Last changed |
|---|---|---|---|
| ZSDIITM products | 19,883 | `extract_products.sql`, 4 Nov evening + `rebuild/run.py` | **5 Nov: 551 categories put back** (534 FGML → PHANT; 17 to X3's category). In `Ethan_fixes_2026-11-05` |
| YITC product costs | 19,883 | same build; 1,178 at 0 (159 stocked) | 4 Nov evening |
| ZSDIITMSUP product-suppliers | 14,746 | `product_suppliers_v4.sql`, 4 Nov 18:14 | **5 Nov: PIO column removed.** In `Ethan_fixes_2026-11-05` |
| YA004SMR / POH / SOHPJ / MFG / BICY / BISY (POH and SOHPJ re-dated 5 Nov, in `Ethan_fixes_2026-11-05`) | 8,621 / 733 / 3,712 / 721 / 814 / 2,056 | `extract_transactions.sql`, 4 Nov 18:39:59 + `scripts/run_transactions.py --stock-date 20261031` | 4 Nov evening |
| YA004BPC customers | 6,169 rows, 303 customers | 27 Oct build + address fixes (`fix_customer_addresses.py`) + VAT (`fill_customer_vat.py`, from `customer_vat_numbers.sql` 4 Nov 18:32) | 4 Nov evening |
| YA004BPC / BPCDL **without Tesco** | 4,466 / 4,466 | `exclude_customers.py TESCO` on the set above (TES100–102 and Tesco-named addresses out) | 4 Nov evening |
| **YA004BPS suppliers** | 706 (623 + 83 new) | 27 Oct build + `fix_suppliers.py` (4 Nov: FR VAT for GAL500, ICE500, BUR500; 11 postcodes; VAT read from Access via `bp_identifiers_run3.sql`, 14:55) | 4 Nov 14:58. Not rebuilt since: supplier VAT has no other source in Access (6.5) |
| YA004BPSC supplier banks | – | `bank_private/` only, never in git or e-mail | 3 Nov |
| YA004BPCDL delivery addresses | 6,169 | 27 Oct build | 27 Oct |
| YA00408BOM | 32,941 lines, 7,189 BOMs | `extract_products.sql` BOM grid (ASC_BOM_TBL, every line), 4 Nov evening + `rebuild/boms.py` | 4 Nov evening |
| ZSDIROU2 routes | 33,499 operations | `extract_routes.sql`, 5 Nov 09:55 (migration.vw_ROU, a live view over ASC_PLN_TBL) + `rebuild/routes.py` | 5 Nov, as built. 116 lines are on 15 products X3 holds as bought-in; X3 skips them (6.3). In `Ethan_fixes_2026-11-05`. The old file came from migration.LOAD_ROU, a one-off copy of vw_ROU (31,326 of 65,158 operations) |
| Tesco customer pack | – | `build_customer_pack.py` → `out_packs/Tesco_customer_pack.xlsx` | 4 Nov |

**Master data is built from 27 Oct and 4 Nov extracts, not a single one.** The customer,
supplier and delivery-address files are still the 27 Oct builds with 4 Nov fixes (BOMs rebuilt 4 Nov evening, routes 5 Nov). James, 5 Nov: they won't have changed, so they stay for Run 3. `rebuild/sql/extract_accounts.sql` is ready; its NEWC / NEWS grids list any account opened since 27 Oct. RTZ
keeps master data in X3, so Run 3 only needs those already loaded. **The go-live run rebuilds all
of them from that morning's extract (rule 1; SCRUM-166, 164, 165).**

### 19.2 What 4 Nov found and fixed

| # | Finding | What was done | Where |
|---|---|---|---|
| 1 | Transactions were first built on the 21 Oct extract | Rule 1: every extract is live on the day. The transactions were rebuilt from the 18:39 extract | 1, 17 |
| 2 | `add_new_accounts_to_xref.sql` rolled back (implicit transaction) | Explicit COMMIT and an "AFTER COMMIT 86 83 0" check; `run_transactions.py` stops on 0 accounts | 17 |
| 3 | `extract_transactions.sql` run before the commit (17:06): 0 / 0 accounts, 1,458 SO lines dropped | Rerun at 18:39; rule 1d: ask James for missing or unusable data by name | 1d |
| 4 | `build_sheets.py` read works orders from the linked 27 Oct folder | Now reads the run's own works orders; 218 added, 222 removed vs 27 Oct | 11 |
| 5 | 2,176 stock lots, 405 SO, 204 PO lines held for products X3 lacked | Product rebuild (+3,384 products); tonight 0 held for want of a product | 6.1, 18 |
| 6 | Zero-cost products were left out | Loaded at 0 and listed (1,178; 159 stocked) | 18 item 18 |
| 7 | SA / zombie parts had the code as description | Description 3, then 2; 1,653 filled, 100 left | 6.1 |
| 8 | PHANT on sold, made or stocked products | Usage test: 534 to FGML (97 sold, 437 made or stocked), 11 bought, flagged | register 11 |
| 9 | Run 2 customer rejections (XPOSCOD / XSAT) | 507 address fixes by rule; 1 left to check (BEA101) | 6.5 |
| 10 | Run 2 supplier rejections (FR VAT) | 3 FR VAT numbers restored from Access with the FR key and Luhn check; 11 postcodes | 6.5 |
| 11 | Users: "VAT numbers are in Access" | Every VAT column searched (`vat_sources_discovery.sql`). Suppliers: only SU_VAT_REG_NO (79). Customers: addresses hold more, so 24 filled; 56 of 303 have one | 6.5 |
| 12 | Tesco to be taken out of the customer files | Without-Tesco BPC / BPCDL; a Tesco-only pack too | 19.1 |
| 13 | Invoice PIN-S01A000015 asked about | X3's own document number; Access numbers are kept in the open items' document fields | 17 |
| 15 | **BOMs and routes were left as the 27 Oct build** (James: "everything had to be rebuilt") | BOMs rebuilt from tonight's ASC_BOM_TBL lines: works orders held for no BOM 95 → 9. That moved 78 to "no route" (2 → 80): their products have no route in the 27 Oct file. Routes need live data: `extract_routes.sql` asked for. **Rule: every file is rebuilt every run, master data included; a file not rebuilt is named as such, with the reason, when the set is handed over** | 1, 19.1 |
| 14 | Stock control total differs by £1.13 | Per-lot rounding in the control total; the file equals Σ qty × price | 17 |

### 19.3 Open decisions (also SCRUM-168)

| Decision | Who | Blocks |
|---|---|---|
| 22 live products hidden by a shared code: which keeps the code | SDI | 22 products' stock and orders |
| FGSL stock-managed in X3 (451 products, £1.72m stock) | Marc / Ethan | SMR on those products |
| PHANT group B (437 made or stocked sub-assemblies): FGML or a category of their own; group C (11 bought) | Marc / Ethan | Product categories |
| X3 accepts the 9-digit SIREN in CRN until Finance gives SIRETs | Ethan | FR suppliers |
| BAL500 tax rule (SV in Access); PLS500; FR VAT / SIRET for the rest | Finance | FR suppliers |
| 5 customer VAT numbers on "VAT check" | Finance | – (customers load without) |
| County / region field code (SAT) | Ethan | Customer addresses |
| Does X3 need NUM unique (BICY / BISY) | Ethan | Open items |
| Do reimports update or skip existing records | Marc | Every rerun |
| Take Tesco out of the transaction files too | James | SOHPJ, BICY |
| TES102 open items (£13.9k) need the account in X3 | Finance / Marc | BICY |
| 17 credit lines (16 SO, 1 PO): credit notes or not open | Marc / Finance | SOHPJ, POH |
| 38 finished works orders still open in Access | SDI | MFG |
| **The PHANT workaround**: how sold, stocked or made sub-assemblies (534) are held in X3 | Marc | 91 SO lines on PHANT products; stock and works orders on them |
| 15 products X3 holds as bought-in that Access now routes: made by SDI, so FGML? | SDI / Marc | 116 route lines |
| **Re-dated orders: still open?** 85 PO lines (16 from 2023–24) and 2,680 SO lines (799 from 2025) loaded with required date 6 Nov 2026 | SDI (Purchasing / Sales) | Close the finished ones in Access before go-live |
| Required date for the reload: 6 Nov 2026 now. It must be after Ethan's load date | Ethan / James | POH, SOHPJ |
| 623 products with only the code as description | SDI | – |
| 9 works orders with no BOM and 1 with no route in Access | SDI | MFG |

### 19.4 Still to do

- BOMs (`rebuild/boms.py`) and routes (`rebuild/routes.py`, `work_centres.csv`) are in the kit and run from `run.py`. MFG now loads 721 of 769: 38 finished, 9 with no BOM in Access, 1 with no route in Access.
- Customer and supplier builders over every account, from `extract_accounts.sql` (SCRUM-166), before the go-live run.
- SCRUM-165 / 166: routes, customers, suppliers, banks and delivery addresses into the kit, so
  the go-live run rebuilds everything from one live extract.
- SCRUM-160: the automatic e-mail after each rebuild. `RUN_SUMMARY.md` and `WHAT_CHANGED.md` are
  its content.
- E-mail drafts to Ethan (assumptions and questions, the Run 2 fixes) were written on 4 Nov. Send
  them bcc, per Claire Newall's rule, with no supplier names on CC.
- Reconcile the Run 3 load with Jim against the control totals in section 17.

### 19.5 Ethan, 5 Nov 09:13: Run 3 product, SO and PO imports gave thousands of errors

Ethan loaded the remaining product master data, then the sales and purchase orders, on 4 Nov.
He's going through the logs, and will RTZ SDIMIG once the fixes are in. Likely causes, checked
against the files (ask for the logs; don't wait):
- **The product file is complete (rule 1b):** 19,883 products, 16,499 already in X3 from Run 2. A
  create-only import fails every existing one. Ask whether the import can update. If not, send
  the 3,384 new products as a second file next to the complete one.
- **512 existing products change category** (495 PHANT → FGML, 14 FGSL → FGML, 3 others). X3 may
  refuse a category change on an existing product.
- **Knock-on:** 400 of 3,712 SO lines, 179 of 733 PO lines and 2,082 of 8,621 stock lots are on
  the new products.
- Find out which file versions he loaded. The evening set (`Current_mapped_set_2026-11-04-pm`)
  replaces the earlier ones.

Reply drafted 5 Nov (`Email_reply_to_Ethan_2026-11-05.md`, scratchpad). It asks for the logs,
whether the import can update, how to change categories, and which files were loaded.

### 19.6 Routes rebuilt from live data (5 Nov)

`extract_routes.sql` (09:55) showed that migration.vw_ROU is a live view over ASC_PLN_TBL
(65,158 operations). The old route file came from migration.LOAD_ROU, a one-off copy of it.
`rebuild/routes.py` rebuilds the routes from vw_ROU. The rules are the old file's, read back
from LOAD_ROU, and reproduce all 31,253 matched lines:
- work centres map through `rebuild/work_centres.csv` (37 Access work centres, each to one X3
  work centre);
- run time per unit is run time / per quantity;
- operations are numbered 5, 10, 15 by route, operation and sub-operation.

Results: 33,499 operations on 7,094 products. Works orders now load 721 of 769.

### 19.7 Ethan's Run 3 findings (5 Nov 12:29) and the fixes

| File | Ethan | Fix (only this; James, 5 Nov) |
|---|---|---|
| ZSDIITM | Products changed PHANT → FGML were rejected: PHANT stays PHANT. Marc to find another way | 551 categories put back: 534 FGML → PHANT, and 17 products already in X3 take X3's category. `products.py` now defaults to `--phant access`, and a product in `--loaded` (the Run 2 V1.3 file) keeps X3's category, listed on Check |
| ZSDIITMSUP | The added PIO column caused the errors | Column D removed; the priority is kept on a "Supplier priority" tab. Pairs unchanged (14,746) |
| YA004POH | Expected receipt dates in the past (2023) fail: the date must be in the future. Open, or remove? | 85 lines re-dated to 6 Nov 2026 (12 from 2023, 4 from 2024, 69 from 2026), listed on "Re-dated" for SDI to confirm or close in Access |
| YA004SOHPJ | DEMDLVDAT in the past (2025) fails | 2,680 of 3,712 lines re-dated to 6 Nov 2026 (799 from 2025), listed on "Re-dated" |

The date is `run_transactions.py --required-date` (default tomorrow). It must be after the load
date, so rebuild on the day if Ethan loads later. Holding lines on PHANT products is
`--hold-phant`, off by default: James wanted Ethan's fixes only.
Sent with the four: the route file from 5 Nov 09:55 as built (33,499). 116 lines are on 15 products X3 holds as bought-in; X3 skips them (James). Ethan didn't raise this.

All five, with load files: `Ethan_fixes_2026-11-05` (scratchpad). E-mail: `Email_to_Ethan_fixes_2026-11-05.md`.

### 19.8 Order dates regenerated for a later reload (11 Nov)

6 Nov had passed before the reload, so YA004POH and YA004SOHPJ were regenerated from the 4 Nov
extract with `--required-date 20261130`. Every required date before 30 Nov 2026 is now 30 Nov,
so the files load on any day up to 29 Nov:
- POH: 517 of 733 lines (85 from before 6 Nov, 286 from 6–11 Nov, 146 from 12–29 Nov);
- SOHPJ: 3,128 of 3,712 lines (2,680, 201 and 247 in the same bands).

Nothing else changed, checked cell by cell against the extract build. Each file's "Re-dated" tab
keeps the original date. The 6 Nov versions are in `Ethan_fixes_2026-11-05/superseded_6Nov`.

### 19.9 Run 4 (11 Nov): Ethan's results and the fixes

**Loaded with 0 errors:** ZSDIITM, YA00408BOM, ZSDIROU2, YITC, YA004MFG.
**Errors from master data only (no change needed):** BICY, BISY, SMR, BPCDL, ZSDIITMSUP.

**Ledger reconciliation:**
- **Customers:** X3 £6,853,365.26 equals Access net, less the 6 customers not in X3 (MAR101, TEC105, UNI103; TEC100, PER101 and DRE100 hold no items). Ties to the penny.
- **Suppliers:** X3 £5,588,058.58 ties once these are accounted for:
  - the 11 suppliers not in X3 (SOG500, ECO500 and BAL500 hold items);
  - the CAP500 "SAVINGS" journal of £22,500, which the file adds but X3 deducts (a £45,000 swing; Jim to confirm its direction);
  - BRW500 invoice 1209156, £1,772.40, dated 2 Nov 2026, which isn't in X3 (Ethan to check).

  "Net" means invoices less credits and receipts / payments; journals as above.

**Fixes, now rules in `scripts/run_transactions.py` (`x3_rules`):**
- **Sales orders:** order date ≤ ship date ≤ required delivery date (Ethan). A ship date before the order date becomes the order date (548 lines); one after the delivery date becomes it (7). 558 SHIDAT changes in all, counting lines whose order date moved.
- **Order dates before 2024** are outside X3's calendar (`--order-floor 20240101`). They become 01/01/2026 (`--order-to`): 17 PO lines (8 Access POs) and 385 SO lines (115 order references). Ethan prefers closing them in Access. Lists for Purchasing and Customer Service are in `deliver/Run4_actions_for_SDI.xlsx`. If they're closed, the next extract drops them.
- Required dates still move to 30 Nov (19.8). Every move is listed on "Re-dated".

**Still open:**
- **Customers:** XPOSCOD on TEC100, TEC105, UNI103, PER101; XSAT on DRE100, MAR101, PER101, TEC105. Acuity investigating with us. 14 countries appear only on these customers (PT, CA, SG, MY, TH, BR, PY, MC, MT, CY, IN, RO, TR, BM), which points at X3's country set-up (postcode format / mandatory region).
- **Suppliers:** 11 with blank VAT / company number (10 FR, 1 ES). Finance to supply. GAL500, ICE500 and BUR500 have their FR VAT; they need the SIRET.

### 19.10 SDI actions from Run 4 – due Friday 13 November

Sent to all three teams in one e-mail on 11 Nov (one attachment per team, from `deliver/`):

| Team | People | Attachment | Action | Then (migration) |
|---|---|---|---|---|
| Purchasing | Sam, Simon Foister | `Purchasing_2023_POs_to_review.xlsx` – 8 POs dated 2023 (17 lines, ≈£20k; Access PO numbers) | Close each PO that isn't open in Access; mark "Y" + note if still open | Next extract drops closed POs. Any still open keep the 01/01/2026 order date (`--order-floor`) |
| Customer Service | Selina Kuddus, Debbie Freeth | `CustomerService_2023_SOs_to_review.xlsx` – 115 order refs dated 2023 (385 lines, ≈£216k) | Same: close in Access, or "Y" + note | Same. Our step, not Ethan's (same calendar issue as the POs) |
| Finance | Ewa, Farhana Khan | `Finance_Suppliers_VAT_SIRET.xlsx` – 11 suppliers (10 FR, 1 ES) with two yellow fill-in columns | VAT number and SIRET / CIF; PLS500 has a GB number on a Spanish supplier; BAL500 tax treatment | Put the numbers into YA004BPS (`fix_suppliers.py`) and send to Ethan for the supplier reload |
| Finance (question) | – | in the e-mail | CAP500 journal "SAVINGS" £22,500 (12 Oct): owed by SDI or to SDI? | Fixes the BISY reconciliation (also asked of Jim) |

**Also open with Acuity:** BRW500 invoice 1209156 (£1,772.40) not in X3 (Ethan); the six customers' XPOSCOD / XSAT errors (joint session); CAP500 direction (Jim).
**Reconciliation figures to repeat after the next load:** customers £6,853,365.26; suppliers £5,588,058.58 (with the items above).

---

## 20. The programme beyond the migration (integrations, reports, spreadsheets, UAT) – 10–11 Nov

Not data migration, but tracked here so nothing is forgotten. Everything is in Jira under the SageX3 epic **SCRUM-40** and in the **programme register**: `deliver/SDI_SageX3_Programme_Register.xlsx` and `.html` (scratchpad). Both are built from `register/register_data.py`, so update that file and rerun `build_xlsx.py` / `build_html.py` to refresh them.

| Area | Jira | What | Source |
|---|---|---|---|
| Opportunity → live project | SCRUM-208, 214–219 | Briefing creates an X3 opportunity; a win creates the project financial dimension (bespoke), written back; PDF attachment under SaaS is the big unknown | Marc's CRM minutes, 12 Oct |
| Estimating port | SCRUM-209 | Estimating prices from X3 data (codes, costs, suppliers, work-centre rates) | James |
| Estimating import | SCRUM-210, 242–244 | Dave Wright's IMPORT sheet: yellow cells (drawing / rev, BOM, wire, sheet, labour) → X3 product, BOM, route. Work centres match our map on all 30; OVEN unmapped, SALV to confirm. Test part "IMPORT" in X3 | Dave Wright, 23 Oct; James → Marc / Sergio, 28 Oct |
| Works orders auto-created | SCRUM-211 | Confirmed order → works orders with BOM and route, job cards | James |
| Live Orders | SCRUM-241, 245–249 | Production / warehouse schedule ("we can't function without it"): live WOs, material status, work-centre hours per week, WO suggestions flagging no BOM / route, exploded BOM with availability. "MCS" column to confirm | Dave Wright, 27 Oct; Rachael Smith |
| Reports | SCRUM-212, 220–240 | 21 Access reports registered: 11 likely X3 standard, 8 need definition, 2 done by Jim (Tungsten EDI, YINVLIST) | Simon Foister, Debbie Freeth, Selina Kuddus, Farhana Khan, 13–20 Oct |
| Spreadsheets | SCRUM-213, 252 | Working sheets read from / write to X3; self-refreshing Excel for AMs / PMs | James; Selina |
| Customer Service UAT | SCRUM-250, 251–260 | Report list from Marc; AM / PM reports; project-code training; back-to-back training; "&" in codes (migration already drops it – keep Sage's block); global allocation; pro forma; dashboards; real data / history; documented processes | Selina Kuddus |

**Sent / delivered:**
- E-mail to Acuity (Marc, Jim, Sergio) on 11 Nov: every integration, report and spreadsheet need, numbered, asking for an owner and a date for each.
- `deliver/charlotte/SDI_Data_Migration_File_Guide.html` and 14 sample screenshots: what each migrated file represents and every column explained. Rebuild with `register/build_guide.py`.
- `SDI_SageX3_Status_Report_2026-11-10.html` (status report).

**Still missing:**
- Replies from Sales, Estimating, Design and the rest of Finance to the 7 Oct request for reports / spreadsheets.
- Possibly Selina's earlier list (19 Oct: "on the list I sent through").

### 19.11 BISY document numbers and lines (Ethan / Jim, 11 Nov 16:24)

**Ethan's two points:**
1. **Blank Access document number.** Where Access has no document number, the build put the supplier's reference
   in Document (B), so B = Source Document (N). Document should be the Access number (starts with 5).
   Confirm they really are blank in Access; give Claire a handful to explain, or to find the real numbers.
   Then decide how to treat them. **SDI to action (Claire).**
2. **Suffixes.** -2, -3 aren't needed. Rows of the same invoice should be Line 1, 2, 3 (column R)
   under the same Document. Otherwise X3 can't be reconciled to Access (5028370 has 6 lines in Access). Only Access
   numbers, none of our own. **Ours to fix.**

**Done (11 Nov):**
- `scripts/build_bicy_bisy.py` now numbers the lines (`LINES=1`, the default, so every future run does it).
  `ONLY=YA004BISY` rebuilds just that file.
- Rebuilt from the 4 Nov evening run, as before:
  ```
  MIG_BASE=<scratch>/runs/2026-11-04-pm/work SRC_DIR=<scratch>/runs/2026-11-04-pm/work/out_mapped \
  OUT_DIR=<scratch>/Ethan_fixes_2026-11-11_BISY ONLY=YA004BISY python3 scripts/build_bicy_bisy.py
  ```
- Results: 2,056 rows; 1,641 documents; 193 documents with more than one line (415 rows moved to lines 2+);
  259 rows with no Access number left as they were. The line total is unchanged (£7,295,217.75, all
  2,056 rows). Every other cell is the same, as the read-back checks show. The file is in `Ethan_fixes_2026-11-11_BISY/`
  (xlsx + `;` txt, with a "Lines" tab).
- `deliver/Finance_BISY_blank_Access_document_numbers.xlsx` for Claire: 259 items, £1.33m;
  tabs Read me, Examples (8, the largest per supplier), All items (yellow fill-in column), By
  supplier. The biggest suppliers: WHT500 28, OPT500 20, FED503 18. The sheet names suppliers, so
  it stays inside SDI.
- `rebuild/sql/check_bisy_document_numbers.sql` (read-only, one short SELECT, 12 Nov: cut down from a two-query `SELECT *` version) for James: about 259 rows, nine columns, should come back.

**Asked of Ethan / Jim:**
- **Lost header detail.** On a multi-line document X3 keeps line 1's supplier ref, source date and due date.
  Should each line's supplier ref go in the line comment (column W)? Or should a document split where due
  dates differ?
- **Header amount.** We assumed it is the document total on every line. Is that right?

**Open:** Claire's answer on the 259; then James to run the SQL above, then a decision with Jim on their numbers.

### 19.12 What the BISY "document number" really is (12 Nov – James ran the check SQL)

**Result** (`check_bisy_document_numbers.sql` on live data, 12 Nov) for the open items with no 5xxxxxx number:
- PT_HEADER_REF2 is NULL on every row and PT_ORDER_NUMBER is blank.
- PT_HEADER_REF holds the supplier's own invoice reference, or text like "DD", "FP", "BACS", "SO", "FF", "PO 5027482 DEP", "DEPOSIT", "CORRECTION" or "SAVINGS".
- Every row has its own PT_PRIMARY (a transaction number, e.g. 58807–70522).

**What that proves.** The view's Source Document is `COALESCE(PT_HEADER_REF2, PT_ORDER_NUMBER, PT_HEADER_REF)`. REF2 is NULL, so the 5xxxxxx number in BISY column B is **PT_ORDER_NUMBER, the Access purchase order number**. The deposits read "PO 5029719 DEP", and Access PO numbers are 50xxxxx. It is not an invoice document number. So:
- **Ethan's issue 2 rests on a wrong premise.** Rows sharing 5028370 are 6 separate DIR500 supplier invoices (refs 173789 … 174454, 6 Aug – 21 Sep, two due dates) against **one PO**. They aren't 6 lines of one invoice. Merging them into one X3 document loses five supplier refs and their due dates, and breaks matching payments to supplier invoices. The lines build is therefore **off by default** (`LINES=1` to turn it on). The file in `Ethan_fixes_2026-11-11_BISY` should not be loaded; tell Ethan.
- **Issue 1 isn't missing data.** The 259 are items not raised against a PO:
  - overhead invoices keyed straight to the ledger (FUK01, WOS01, OPT01, HAR07, WCL02 …);
  - payments on account (DD, FP, BACS, SO, FF);
  - deposits against POs (XIG01, EDC02, EGT01, XYS01, YGE01);
  - two credits, a correction, and the CAP500 (COT02) "SAVINGS" ADR journal.
  Claire need only confirm. There is no document number to find.
- **Access's real unique key is PT_PRIMARY.** Every open item has one. It isn't in the extract yet.
- **Lead on the missing BRW500 invoice 1209156 (£1,772.40):** it's one of the 259 (BJL01, PT_PRIMARY 70265, dated 2 Nov). Document = supplier ref. Check whether X3 rejected it as a duplicate document number.

**Options for Ethan and Jim (SDI's recommendation is (a)):**
- (a) Document = PT_PRIMARY: unique, in Access, never made up. Source Document = supplier ref; PO number in a comment.
- (b) Document = supplier invoice ref (the Run 2 layout): not unique across suppliers.
- (c) Document = PO number with lines: Ethan's ask, but it loses data as above.

Adding PT_PRIMARY needs one column added to the BISX extract, `extract_transactions.sql` / `vw_BISX_V2`. Do it only once (a) is agreed.

**Lesson:** before restructuring on someone's description of a field ("the Access document number"), check what the field actually is in Access. Find the column it comes from and look at a sample.
