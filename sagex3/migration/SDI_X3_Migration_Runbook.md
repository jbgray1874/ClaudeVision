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
- **12 Nov, AGREED with Ethan / Jim, and it supersedes everything above for BISY:** Document (B) = Access transaction number
  (PT_PRIMARY); Source Document (N) = supplier's reference; Comments (P) = PO number (blank if none);
  Line = 1; no swap, no suffixes. Done in `vw_BISX_V2` (`sql/views_v2.sql`) and `build_bicy_bisy.py`. Section 19.13.
- **Lines, not suffixes (11 Nov) – WITHDRAWN 12 Nov (`LINES=1` only): the 5xxxxxx number is the PO number, see 19.12.**
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

**12 Nov, which BISY is current.** The BISY in X3 is the Run 4 file, from the 4 Nov evening build:
`Current_mapped_set_2026-11-04-pm/YA004BISY_guide_MAPPED.xlsx` + `.txt`. It has 2,056 rows and the -2 / -3 suffixes, and it **stays in X3 as it is**. It was re-sent to Ethan on 12 Nov for reference.

Ethan was told to disregard **both** files sent on 11 Nov with the lines: `YA004BISY_guide_MAPPED.xlsx` and `.txt`, now in `superseded_12Nov_BISY_lines_DO_NOT_LOAD`. The next BISY will be built with PT_PRIMARY as the Document once Ethan and Jim agree option (a).

**12 Nov: does the Run 4 BISY need changing? Yes, for the next run, but only once the document number is agreed.**
- Both of Ethan's points apply to the Run 4 file:
  - **Document (B) is the PO number**, with -2, -3 suffixes on 422 rows.
  - **259 rows have B = N** (the supplier ref, because there's no PO).
  - These can't be fixed by editing the file, because the answer depends on which document number is agreed.
- **If (a) is agreed (PT_PRIMARY):** both points go away together. Every row has its own Access number, so there are no suffixes and no stand-in references.
- **The steps, in order:**
  1. Add PT_PRIMARY to the BISX output of `extract_transactions.sql`, plus the live `migration.vw_BISX_V2` on the server (that view differs from `sql/views_v2.sql` in the repo; check it first).
  2. James re-runs the extract on the day (rule 1, live data).
  3. Change `build_bicy_bisy.py`: B = PT_PRIMARY, N = supplier ref, PO number in a comment, no suffixes.
  4. The read-back checks that B is unique, that no B equals N, and that the totals are unchanged.
- **Until then:** nothing is re-sent; X3 keeps the Run 4 file.
- **BICY is not affected.**
- **If Ethan and Jim choose differently:** (b) supplier ref still needs suffixes where it repeats; (c) loses data as described in 19.12.

**12 Nov: Run 4 BISY rebuilt to prove it is the right file.**
- Rebuilt from the 4 Nov evening run (`ONLY=YA004BISY`, lines off) into `repro_BISY_12Nov/`.
- The txt is byte-for-byte the file loaded in Run 4, and every cell on every tab of the xlsx is identical.
- Copied to `deliver/BISY_Run4/YA004BISY_guide_MAPPED_Run4_as_loaded.*`.

How to tell the two files apart:

| | Run 4 (correct) | 11 Nov lines version (withdrawn) |
|---|---|---|
| Tabs | Mapping, Notes, Data with Headings, Guide | the same + **Lines** |
| Line (column R) | 1 on every row | up to 18 (415 rows not 1) |
| Size, xlsx / txt | 277,346 / 352,566 bytes | 312,005 / 353,016 bytes |
| MD5, xlsx | 134843c4d2bfdd00d377cdf34edb6fce | 271dbf3400b4e251f10592c4b6b327cc |
| MD5, txt | a5eb08a22aa2f99838b57ad738bbb299 | 83336853c8de59cd193b972355ec2737 |

Both have 2,056 rows and GBP £6,813,472.18.

### 19.13 Ethan, 12 Nov 09:39 and 09:50: document number agreed; BRW500 dates; customer accounting codes; aged-report sign-off

**1. BISY document number – agreed.**
- Ethan: the repeated numbers were his mistake. Every Document must be unique, Line is always 1, and X3 accepts a row as long as no Document is missing.
- Agreed layout: B = Access transaction number, N = supplier's reference (as now), Comments = PO number (blank if none). "That works for X3 and for reconciling against Access."
- **Done:**
  - `sql/views_v2.sql`, `vw_BISX_V2`:
    - `Document = CAST(PT_PRIMARY AS varchar(20))`;
    - `SourceDocument = PT_HEADER_REF` (PT_HEADER_REF2, then PT_PRIMARY, if blank);
    - `Comments2 = PT_ORDER_NUMBER`.
    - The `ref_seq` in its CTE is now unused.
  - `scripts/build_bicy_bisy.py`:
    - BISY is no longer swapped (`SWAP_BISY=1` brings back the old swap, for the 4 Nov extract only).
    - New checks: every Document is all digits and unique, none equals N, and Line = 1.
    - On an old extract the build stops: "a Document is not an Access transaction number".
- **Tests (12 Nov):**
  - The 4 Nov extract with `SWAP_BISY=1` still reproduces the Run 4 BISY byte for byte.
  - BICY is unchanged, byte for byte.
  - Simulated new-view data builds cleanly, e.g. `MINV;60001;SIG500;…;0000013372;Purchase Overhead;5029976;;1;…`.
- **Needs the next live run:** James runs `sql/views_v2.sql` (now changes our own view only), then `rebuild/sql/extract_transactions.sql`.
- **BICY** still uses the order number with suffixes (170) and fills blanks (20). Ethan's "every number unique, none of our own" points the same way: BICY could use ST_PRIMARY. **Raised with Ethan, not changed.**

**2. BRW500 1209156 failed on dates, not the document number.** Source date (J) must not be after the accounting date (F). The invoice is dated 02/11/2026 and F was 31/10/2026.
- In the Run 4 files:
  - BISY: 1 item (this one) is dated after F;
  - BICY: **59 items (£763,936.91) are dated 2–4 Nov**, because the extract was taken on 4 Nov with F fixed at 31/10. Ethan reported no date errors on BICY; asked him to check.
- **Cause:** the accounting date (31/10, hard-coded as `'20261031'` in the views and `ACCOUNTING_DATE` in `populate_guides.py`) is earlier than the extract date (4 Nov).
- **DECIDED (James, 12 Nov): accounting date = the extract date.** It's the go-live rule (31 Dec / 31 Dec) and nothing is lost.
  Aged reports are compared as at that day. **Done, see 19.14.**

**3. Customer accounting code (ACCCOD), YA004BPC.**
- All 303 customers were loaded STD, so every customer debit posted to one control account. There should be three:
  - STD = Unassigned;
  - EU = Assigned EUR;
  - ID = Assigned (taken to mean the invoice discounting facility; to confirm).
- **Action: James and Claire.**
  - `deliver/Finance_Customer_Accounting_Codes.xlsx`: 303 customers, the 83 with open items first, largest balance first, with a STD/EU/ID drop-down (blank = STD). There are 21 EUR customers.
  - Once it's back, the codes go into `YA004BPC` (column Q, ACCCOD) and Ethan reloads customers before BICY.
- Confidential (names and balances), so it stays inside SDI.

**4. Aged debtors / creditors sign-off.**
- Ethan sent the X3 trial balance after the SL/PL load, plus the Aged Debtors and Aged Creditors reports from X3. The relevant person must sign them off against the same reports from Access "as at 31/10".
- **Watch:** X3 holds the open items as extracted on **4 Nov 18:39**, not as at 31/10. Run the Access reports as at the same moment, or reconcile on the extract's control totals:
  - customers £8,506,050.44 gross, 814 items;
  - suppliers £6,813,472.18 gross, 2,056 items;
  - net basis as in 19.9.
  Otherwise payments and invoices from 1–4 Nov show as differences.
- Action: James forwards it to Claire (Finance) with Ethan's reports.

**Next:** Ethan wants a new import run of every file we have, once these changes are made. Order:
1. ACCCOD back from Claire.
2. The accounting-date decision.
3. Re-run views and extracts on the day.
4. Full rebuild.

Every file, every run (rule 1e).

**Lesson:** a fixed accounting date in a view goes stale the moment the extract is taken on a later day. Every date set in the build must follow the run date.

### 19.14 Accounting date = extract date (James, 12 Nov) – built and proved

**Code:**
- `scripts/run_transactions.py`:
  - new `--accounting-date`. The default is the extract's own "as at" line (CHECK grid), e.g. 2026-11-04 18:39:59 → 20261104. Go-live gives 20261231 by itself.
  - The value is written into RUN_SUMMARY and passed to the chain as `ACCOUNTING_DATE`.
  - The run stops if the extract has no "as at" line.
- `scripts/populate_guides.py`:
  - BICX / BISX column F = `ACCOUNTING_DATE`.
  - The build **stops** if any item's Source Date (BICX index 8, BISX index 9; BISX has CURLED before it) is after it. That's the BRW500 failure, now caught before Ethan sees it.
  - The SOH rule "ship / delivery date before 2025 → 31/10" keeps its own constant, `SOH_OLD_DATE_TO = 20261031`, so only the ledgers change, as James asked. A first test moved 1,305 SOHPJ ship dates; that was caught and fixed.
- **Bug fixed on the way:** `x3_rules` (11 Nov) crashed on SMR / MFG rows (`IndexError`, r[11]). It had only ever been run on POH / SOHPJ, so the next full run would have failed. Fixed: the "who" columns are only read for POH.

**Proof:** a full `run_transactions.py` run on the 4 Nov extract (`runs/test-accdate`), compared with the Run 4 files:
- **BICY 814 / BISY 2,056:** only column F differs (20261031 → 20261104).
- **POH, SOHPJ, SMR, MFG:** identical.

**Trap found in the test – pass the run's own inputs, never the defaults.** The defaults point at old sets:
- `--bins` must be the run's `extract/bins.txt`. The default `bins/out.txt` moved 97 stock lots to A001.
- `--bom` must be the current BOM set, the 7,189 BOMs in `Current_mapped_set_2026-11-04-pm`. `runs/2026-11-04-pm/out` has 7,174, and 8 works orders were held back as "no BOM".
- `--routes`: the current routes file (`Ethan_fixes_2026-11-05/ZSDIROU2_routes_MAPPED.xlsx`).

Command used:
```
SWAP_BISY=1 python3 scripts/run_transactions.py <scratch>/runs/test-accdate --stock-date 20261031 \
  --required-date 20261130 --bins <run>/extract/bins.txt \
  --bom <scratch>/Current_mapped_set_2026-11-04-pm/YA00408BOM_boms_MAPPED.xlsx \
  --routes <scratch>/Ethan_fixes_2026-11-05/ZSDIROU2_routes_MAPPED.xlsx
```
`SWAP_BISY=1` was only because it was the old extract. **Next live run: no SWAP_BISY.** BOMs and routes are rebuilt by `rebuild/run.py` first, and their outputs are passed here (rule 1e).

### 20.1 Rebate rolling report (12 Nov) – recreate from Access SupplyChain, then in X3

James sent `Rebate_rolling.pdf` (November 2026 copy) and asked for it to be recreated from Access. The register has it as **REP-22**, with no Jira issue yet.

**What the report is (read from the PDF):**
- One row per customer order line for the Morrisons goalpost / branded-bay parts. Columns: customer code and name, part code, description, Price per, then a value in the month it falls in. The months are a rolling 12, December to November.
- Parts: the `10932-00-GA1 <brand>` variants (HAR, M&M, HVL, KEN, B/B, BEL, CAD, TOB, BRU, NES, ROW, GOU, VOL, SH, TET, QW, COM, HEI), `HHA-INSTALL M&M`, `LRS01-RIBENA`, `LRS01-LUCOZADE` and `WMM01-GOALPOST`. The customers are brand owners (HHA01, HVL01, JDE01, LRS01, MUL01, NES03, NTL01, PFG01, TCP01, TOH01, UUL01, DPP01) plus Morrisons, WMM01.
- **Value = quantity × Price per.** E.g. 19,080 = 72 × £265.00, and 32,771 = 172 × £190.53. A credit shows as a negative (HHA-INSTALL, -9,720).
- Monthly totals, then **a rebate of 6% of each month's total**: 90,472.95 → 5,428.38; 231,854.20 → 13,911.25; 52,750.00 → 3,165.00; 174,134.16 → 10,448.05.
- Grand total £549,211.31 and rebate total £32,952.68 (6%).
- Some lines show no value in any month. These are probably ordered but not yet invoiced or delivered in the window: to confirm.

**Unknowns, to settle before building:**
1. Which date puts a line in a month: invoice, delivery or order date?
2. How the parts are selected: a list, a code pattern, a flag, or Morrisons as the end customer.
3. Who the 6% is paid to, and whether it's always 6%.

**Asked of James (rule 1d):**
- (a) In the Access SupplyChain front end, open the report in Design view → Property Sheet → Record Source. Copy the query, or the query name, and its SQL view. That's the exact definition.
- (b) Run `sql/rebate_discovery.sql` (read-only, two short queries). It finds anything named "rebate" in SDILive, and shows every column of up to 60 order lines for these parts. Save the results as `rebate_discovery.txt`.

**Then:**
1. Write `sql/rebate_rolling.sql`, read-only, with the rolling window from the run date.
2. Build an SDI-branded workbook with the same layout, monthly totals and the 6% row.
3. Prove it against this PDF: the same lines, the month totals, £549,211.31 and £32,952.68.

The X3 version goes to Acuity with the reports list (SCRUM-212).

### 20.2 Rebate rolling report – built as a repeatable sample (12 Nov) – REP-22, Jira **SCRUM-275** (under SCRUM-212)

**James's decisions (12 Nov):**
- **Dates:** carry all three (invoice, delivery, order). Months go by invoice date by default; `--basis delivery|order` switches.
- **Selection:** by part code only, any customer – the 22 codes on the November report.
- **Empty lines:** explained as an assumption in the covering e-mail.

**Discovery results (12 Nov, `sql/rebate_discovery.sql`):**
- Rebate fields exist:
  - `UDEF_INVOICED_SALES` (view) "Rebate Val";
  - `vw_SalesLedgerDetailed` / `vw_SalesLedgerFull` "Rebate Value";
  - `UDEF_Customer_DSR_DATA` / `UDEF_DSR_DETAIL` "Rebate %";
  - supplier side: `SUP_REBATE`, `SUP_REBATE_TURNOVER` on `SUP_TBL`, `ASC_SUP_TBL`, `ASC_PL_ACCOUNTS`.
- `ASC_COR_TBL` sample: order lines for many more `10932-00-GA*` variants than the report shows (PEP, DOV, CCE, REG, SB, MOR, PRI, KK, CGA …). So the report uses a **fixed part list**, not a pattern.

**What the Access report is (proved against the PDF):**
- One row per **invoiced** line, not per order line. WMM01 HEI's order for 200 shows as 125 + 75. HHA-INSTALL has a credit of -72.
- Value = quantity × price per, to the penny.
- Rebate = 6% of each month's total, rounded per month; the rebate total is the sum of the twelve.
- Lines with no value are invoices from the month before the window (November 2025: DPP01 HAR, MUL01 x9, NES03 GOU, NTL01 VOL, TOH01 x3). They're listed but not counted.

**Built (repo `sagex3/reports/rebate/`):**
- `rebate_parts.csv`: the 22 part codes. Change the list here; no code change needed.
- `build_rebate_report.py <lines.csv|.txt> <out> [--end YYYY-MM] [--rate 0.06] [--basis invoice] [--sample]` writes `SDI_Rebate_Rolling_<YYYY-MM>.html` and `.xlsx`.
  - **HTML:** KPI tiles; a sales-by-month chart with hover; month and customer tables; the full report matrix (credits in red, out-of-period lines grey); how it's built; assumptions.
  - **Excel:**
    - Summary: tiles, chart, month and customer tables, and **one rebate-rate cell (named `RebateRate`) that every rebate follows**.
    - Rebate report: the PDF layout with live formulas, totals and a rebate row; frozen panes, filter, print setup.
    - Lines: every date and the invoice number.
    - By part.
    - Notes & assumptions.
- `rebate_source_check.sql` (read-only): the definition and five rows of `UDEF_INVOICED_SALES`, so `rebate_rolling.sql` can read it. **James to run it.**

**Sample (scratchpad `rebate/`, not in git – it names customers):**
- `sample_lines_from_Nov2026_pdf.csv`: 39 lines rebuilt from the PDF, quantity = value ÷ price.
- `out/SDI_Rebate_Rolling_2026-11_SAMPLE.html` and `.xlsx`.
- **Proof:**
  - total £549,211.31 and rebate £32,952.68;
  - every month: Dec 90,472.95, Jul 231,854.20, Aug 52,750.00, Sep 174,134.16;
  - the same again in Excel after a LibreOffice recalculation of the formulas.
  - Checked at desktop and phone width with no sideways page scroll.

**Assumptions sent to Finance:**
1. The rebate is on invoiced value.
2. It's 6% on every part and customer, paid to Morrisons.
3. Lines invoiced before the window are listed but not counted.
4. The part list is complete.

**Next steps:**
1. `rebate_source_check.txt` from James.
2. Write `rebate_rolling.sql` (read-only, from the run date back 13 months, the 22 parts) into the builder's columns.
3. Prove it against the PDF.
4. Schedule or document the monthly run.
5. Then the X3 version with Acuity.

**Lesson:** when recreating a report, rebuild the sample from the reference copy and prove the totals to the penny **before** wiring the live feed. The layout and the arithmetic are then settled separately from the data source.

**12 Nov, later – Access's invoiced-sales view (James ran `rebate_source_check.sql`).** `dbo.UDEF_INVOICED_SALES`:
- **Joins:**
  - `TBI_TBL` (invoice lines: TBI_OUR order, TBI_SUB, TBI_CUS, TBI_PART_ONLY / REV, TBI_QTY, TBI_INVOICE_NO, TBI_INVOICE_DATE);
  - to `COR_TBL` on part + rev + order + sub (COR_PRICE_PER, COR_QTY_ORDERED / DELIVERED, COR_CUSTOMER_DUE, COR_PROJECT);
  - to `SL_ACCOUNTS2` on CUCODE2 = TBI_CUS (collation LATIN1_GENERAL_BIN).
- **Values:**
  - Inv Value = COR_PRICE_PER × TBI_QTY;
  - **Rebate Val = Inv Value × CU_USRNUM1 / 100**, so Access holds a **per-customer rebate %** on the customer account (TIE02E: 3%);
  - Value = Inv Value − Rebate Val.
- Dates come out as text dd/mm/yyyy.
- **Consequences:**
  1. The report is built on **invoice lines**. Two identical TBI rows (TIE-1455/1M, 25 + 25 of 50) are two real part-invoices of one order line, not a duplicate.
  2. The Morrisons report's flat 6% is **not** the per-customer % in Access. Assumption 2 now asks Finance to confirm it is a separate Morrisons agreement.
  3. There's no delivery date on the invoice line. The order line's customer due date (COR_CUSTOMER_DUE) is carried instead, so `--basis` is now `invoice|due|order`.
- **Built:**
  - `sagex3/reports/rebate/rebate_rolling.sql` (read-only):
    - the view's joins, on real dates;
    - from the first of the month 12 months back, so 13 months: the Access report also lists the month before the window;
    - the 22 parts;
    - customer name from SL_ACCOUNTS.CUNAME, description from PMA_TBL.PMA_DESC_1 (OUTER APPLY TOP 1, so it never duplicates a line);
    - plus project_no and customer_rebate_pct.
    - Output: tab-delimited with headers → `build_rebate_report.py`.
  - Builder: due date, project and the Access customer rebate % are on the Lines tab.
  - **Tests:**
    - a feed in the SQL's exact layout gives £549,211.31 / £32,952.68;
    - `--basis order` on the sample gives 0, correct because the sample has no order dates.
- **Next:** James runs `rebate_rolling.sql` (save as `rebate_lines.txt`), then I build the live report and compare it with the November PDF line by line.

**12 Nov, evening – live run proved against Claire's November report.**
- James ran `rebate_rolling.sql`: **37 invoice lines**. Saved in the scratchpad at `rebate/live/rebate_lines.txt`; the paste had no header row, so one was added.
- **The month is the order line's customer due date (COR_CUSTOMER_DUE), not the invoice date:**
  - **By due date: total £549,211.31 and rebate £32,952.68, both to the penny.** December 90,472.95, July 231,854.20 and August 52,750.00 match exactly.
  - By invoice date: December is £17,295.60 too high. MUL01 B/B 38, CAD 2 and TOB 30 are on invoice 5014699 dated 16 Dec 2025, but due 28 Nov 2025; Claire's report shows them blank.
  - **So `build_rebate_report.py` now defaults to `--basis due`.**
- **The only difference, by due date:**
  - HHA01 10932-00-GA1 M&M 72 (£19,080, order 0000010016441, invoice 5019203, 30 Sep) is now due 9 Nov 2026, so it falls in November instead of September.
  - That order line was last changed on 12 Nov at 16:04 (the `ASC_COR_TBL` discovery row), after Claire's report. The due date was most likely moved.
  - The rebate total is the same: Sep 9,303.25 + Nov 1,144.80 = 10,448.05.
- **Line count: 37 in Access against 39 on Claire's.** Her HHA-INSTALL M&M shows 4 lines (30, -72, +72, +72); Access has 2 (30, 72) on invoice 5019204. Both net to 102 = £13,770.00. A credit and re-invoice pair that `TBI_TBL` no longer holds, or that sits in a credit-note table. Ask Claire.
- **Access per-customer rebate % (CU_USRNUM1) = 0 for every customer on the report.** The 6% is not taken from the customer account.
- Descriptions on Claire's report are the order-line text; ours are the part description (PMA_DESC_1). The values are not affected.
- **Live report:** `rebate/live/out/SDI_Rebate_Rolling_2026-11.html` and `.xlsx`. The sample stays in `rebate/out` (invoice basis, rebuilt from the PDF).

### 20.3 Rebate report – Jira, register, and a web app to re-run it (12 Nov)

**Jira SCRUM-275:**
- Moved to **In Progress**.
- The description is rewritten: how the report works (proved), step 1 done, web app to come.
- A comment records the live reconciliation: to the penny by due date; December £17,295.60 out by invoice date; the two differences; Access customer rebate % = 0.

**Register REP-22:** status **In test**. The next action is Claire's four confirmations, then the X3 version.

**The query now takes an end month.** `rebate_rolling.sql` has `@end_month` (default: this month), with `@from` = 12 months earlier and `@to` = the month after. That's 13 months, and nothing after the window is pulled in, so a past month can be re-run cleanly.

**Web app: `sagex3/reports/rebate/rebate_app.py`.**
- **Built on Python's own web server.** Nothing to install but `openpyxl`, plus `pyodbc` for "Run from Access". (Flask isn't available in the build environment and isn't needed.)
- **To run it, on a PC or server inside SDI that can reach SDILive:**
  ```
  pip install openpyxl pyodbc
  set SDI_SQL_CONN=DRIVER={ODBC Driver 17 for SQL Server};SERVER=<server>;DATABASE=SDILive;Trusted_Connection=yes;ApplicationIntent=ReadOnly
  python rebate_app.py                 (http://localhost:8765)
  python rebate_app.py --host 0.0.0.0  (shared on the SDI network - there's no login, so keep it inside SDI)
  ```
- **What the page does:**
  - **Run from Access:** pick the last month of the 12, the month basis (due / invoice / order) and the rebate %. It runs the same `rebate_rolling.sql` read-only (pyodbc `readonly=True`).
  - **Paste:** the SQL Server grid, with or without the heading row (the missing heading that caught us on 12 Nov is added automatically). Rows with fewer than 11 columns are refused, with the reason shown.
  - **Every run is kept** in `runs/<timestamp>_<YYYY-MM>/`: `rebate_lines.txt`, the HTML and the xlsx. They're listed on the page with the sales and rebate, and the Excel can be downloaded.
  - `runs/` is in `.gitignore`, because it names customers.
- **Tests (12 Nov):**
  - Paste the 37 live rows with no heading: report £549,211.31 / £32,952.68; Excel downloads.
  - "Run from Access" without a connection: refused, with the reason on the page.
  - A bad paste: refused.
  - "Run from Access" through a stand-in pyodbc that replays the 37 rows: it checks the SQL has the end month set, contains no INSERT / UPDATE / DELETE / DROP / ALTER, and the connection is read-only. Result £549,211.31 / £32,952.68.
  - Checked at desktop and phone width.
- **Still to do:**
  - James to choose the machine and the SQL login (read-only).
  - Optionally a Windows scheduled task to start it at boot.
  - Re-run when Claire answers.

## 21. Building our own reports, imports and integrations in Sage X3 – what to find out first (12 Nov)

James has an X3 admin login. **Work in the test folder only.** Production rules apply as for Access: no change to live X3 data or set-up without sign-off. Build in test, prove it, then move it to live as a patch.

**1. Find out first (ask Acuity: Marc / Jim / Sergio), because everything else depends on it:**
- **Hosting:**
  - Sage-hosted cloud (SaaS): no database access; APIs only.
  - Acuity / partner-hosted, or on-premises: database access possible.
- **Version and patch level:** the "?" (help) menu → About. GraphQL / REST APIs depend on it.
- **Folders and endpoints:** which folder is LIVE, which is TEST / UAT, and which one we may develop in.
- **Database:** type (SQL Server or Oracle), server, database name, and the schema, which is the folder name. Is a **read-only** login possible, or a reporting replica?
- **APIs for wiring in:** SOAP web services, REST, or GraphQL? Is there a "connected application" (OAuth client) for us? Are licences used per call or per user?
- **Reporting tools licensed:**
  - Crystal Reports (designer on our PC plus the X3 print server);
  - requests / inquiries to Excel;
  - Sage Enterprise Intelligence (BI), if licensed.
- **Development rights:** can SDI create specific objects (the Y/Z naming, activity codes)? Who moves patches from test to live?
- **Import templates:** the YA004… templates are Acuity's. May we copy them, and add our own (Y prefix)?

**2. Where to look in X3 with the admin login** (menus vary by version; the function codes are stable):
- **About** ("?" menu): version, patch level, current folder.
- **Administration → Administration → Endpoints / Solutions:** folders, application server, database server and name (on-premises or hosted only).
- **Administration → Users (GESAUS):** our own and any API user.
- **Import / export templates (GESAOE):** every field, separator and structure of each YA004 template. Templates are run from Usage → Imports/exports.
- **Report dictionary (GESARP):** where Jim's YINVLIST lives; one Crystal report per entry.
- **Web services:** classic SOAP pools and published web services (GESAWE). Connected applications for REST / GraphQL.
- **Development → scripts and dictionary:** the specific (Y/Z) objects already built for SDI.

**3. How we work, the same discipline as the migration:**
- Every report and import is first proved against the Access equivalent, to the penny. Rebate REP-22 is the pattern.
- Build and prove it in TEST. A patch takes it to LIVE.
- Write up each one here and in the register / Jira.

### 21.1 What we already know about SDI's X3 (RFI, 15 Apr 2026; Neil Morphew, Acuity, 18–26 May 2026)

**Hosting – settled:**
- **Sage X3 Cloud SaaS**, hosted by **Sage** on AWS UK South (London). Single tenant on Sage's hosting offer.
- **Not** a private cloud.
- **Consequences:**
  - **No direct database / SQL access.** Sage runs the servers.
  - **No server or endpoint settings for us.** Session timeouts are Sage's; the platform default is a check every minute and a 20-minute idle timeout.
  - SDI's network, VPN and Wi-Fi don't matter. X3 is reachable from anywhere over HTTPS. Full-tunnel or split-tunnel VPN is SDI's own choice.
  - **"Connection details" for us = the API endpoints + an API client (credentials)**, not a server, database and login.

**Login:**
- Sage ID with 2FA only.
- Linking Sage IDs to SDI's Azure / Entra tenant is expected in the next SaaS release; not available yet.
- SAML / OAuth to Azure exists only for private cloud.

**Printing:** Vasion Print, supplied through Sage. The Vasion client goes on **a device on SDI's network that can see the printers**, e.g. thermal label printers. A machine has to be chosen.

**Integration (RFI):**
- **SOAP, REST and GraphQL APIs**, plus file exchange.
- Real time via **webhooks**, or batch via the **X3 batch server**.
- Acuity's usual middleware is **Microsoft Power Automate** (security and logging).
- Built-in customisations use **Sage's Safe X3 framework**.

**AI:**
- No public Sage MCP server yet (roadmap, no date).
- **Acuity have built an MCP server on the X3 data model** and offer it.
- Sage Copilot exists; custom agents and workflows are still roadmap.

**Data validation:** Acuity use Excel, Power tools and SQL tools on the extracts, plus record counts, spot checks and report comparisons. That is what we already do.

**Demo environment:** offered, with a Teams workshop session.

**Charlotte (Apr):** X3 is the building block – customisable, open API, links to other software.
- **Note:** under SaaS that linking is **through the APIs**, not direct SQL.
- To ask Acuity / Sage: is there any SaaS read-only data access – a reporting replica, data export or BI connector – for reports that today read SQL directly, like our Access ones?

**What this changes in section 21:**
- Hosting, database and endpoint questions are answered: SaaS, no DB.
- **Ask Acuity for:**
  1. An API client for SDI in the **test** folder, with credentials and the base URLs for REST and GraphQL, and which objects are exposed.
  2. Whether webhooks and batch-server jobs can be set up by us or only by Acuity.
  3. Development rights in Safe X3 (Y/Z objects) on SaaS, and how patches reach live.
  4. Reporting options on SaaS: Crystal designer, requests / inquiries to Excel, any BI connector.
  5. Read-only data access for reports.
  6. Their MCP server: terms, data scope, and whether it works against test.
  7. Vasion device requirements.
- **Rebuild REP-22 in X3 via GraphQL / REST, or a request**, proved against Access as before.

### 21.2 Requirements e-mail to Acuity (Neil Morphew) – SDI developer and API access (12 Nov)

James is **telling** Acuity what SDI needs, not asking permission.
- **To:** Neil Morphew.
- **Cc:** Marc Davies, Jim Hildreth, Richard Sadler, Charlotte Blackwell.
- **Subject:** "Sage X3 Cloud – SDI developer and API access".

What the e-mail requires, first in the **test folder**, then mirrored in **live** once proved:
1. **API access:** an API client / connected application with credentials; REST and GraphQL base URLs; documentation of the objects exposed; read **and write**; a dedicated SDI integration user. **Also confirm whether API calls consume user licences** (add this line if it isn't in the sent version).
2. **Events and scheduling:** webhooks (order, works-order and opportunity changes) and the batch server. Can SDI set them up directly, and if not, Acuity's process and turnaround?
3. **Development access:** Safe X3 rights for SDI objects (Y/Z) in test; the process and lead time from test to live.
4. **Reporting:** the Crystal designer and report dictionary; queries / inquiries to Excel; any read-only data access on SaaS (reporting copy, export, BI connector), or a clear "none".
5. **Acuity MCP server:** scope, terms, access against test.
6. **Printing:** the specification of the SDI PC that hosts the Vasion client.
7. Which items can be set up straight away, dates for the rest, and a call this week.

It replaces the earlier draft ("developer access for reports, imports and integrations"), which asked the same seven things as questions.

**Actions:**

| Action | Owner | Status |
|---|---|---|
| Send the requirements e-mail | James | to send |
| API client + credentials + base URLs (test) | Acuity (Neil) | requested |
| Webhooks / batch server – who sets up | Acuity | requested |
| Safe X3 development rights, test → live process | Acuity | requested |
| Reporting tools + read-only data answer | Acuity | requested |
| MCP server scope and terms | Acuity | requested |
| Vasion PC specification; choose and prepare the machine | Acuity → SDI IT (Chris Sherlock) | requested |
| API licence consumption | Acuity | to confirm |
| Call with Neil | James / Neil | to book |
| Once the API client exists: rebuild REP-22 (rebate) on X3 data, proved against Access | James | after access |

### 21.3 What James can find out himself in the X3 web portal (admin login, TEST folder)

Read-only look-round, with nothing changed. Screenshot each screen for the runbook.
- **Menu paths vary by version.** If a menu isn't where expected, search for the function code (e.g. GESAOE).
- On SaaS, server-level screens may be hidden or locked. That itself is an answer – note it.

1. **The user / help menu ("?" → About):** product version, update / patch level, the current folder. This decides which APIs (REST / GraphQL) exist.
2. **The folder / endpoint selector (top right, by the user name):** every folder you can open – test, live, any seed / demo. Note the exact names.
3. **Administration → Administration → Endpoints / Solutions:** the folder and server set-up (may be hidden on SaaS).
4. **Administration → Users (GESAUS) and Roles / Groups:** our users, any existing integration or API user, and what an admin may change.
5. **Administration → Web services / Connected applications (GESAWE and the connected-apps screen):** whether any API client already exists, what's published, and whether REST / GraphQL appear.
6. **Usage → Imports/exports → Import/export templates (GESAOE):** the list of templates (YA004…, ZSDI…, YITC, the opportunity template). Open one and note the fields, separator and structure.
7. **Usage → Imports/exports → Imports:** how a template is run, and the import log, where Ethan's errors come from.
8. **Report dictionary (GESARP):** the reports present, including YINVLIST; which are standard and which are specific (Y / Z).
9. **Queries / inquiries (Requester):** whether we can build a query and export it to Excel – the quickest route for simple reports.
10. **Development → Data and parameters → Tables / dictionary:** table names behind the screens (ITMMASTER, SORDER, SORDERQ, SINVOICE, BPCUSTOMER, MFGHEAD …). They're the names the API objects use.
11. **Dashboards / landing pages:** what Customer Service will see (CS-08).

Send the screenshots or notes back, and they'll be logged here against each question in the e-mail. Some questions may be answered before Neil replies.

### 21.4 Likely solutions – estimating import (EST-10) and Live Orders (LO-00) (12 Nov, proposal)

**Estimating spreadsheet → X3** (Dave Wright's IMPORT.xls; the yellow cells hold the drawing / rev, BOM, wire, sheet and labour).

*Stage 1 – works now, no API needed.* A converter, built like the migration kit, reads the estimate workbook and writes the **same X3 import files we already produce**:
- product (ZSDIITM layout), BOM (YA00408BOM), route (ZSDIROU2) and cost (YITC);
- with the agreed work-centre map (30 matched; OVEN still to map; SALV to confirm) and run time in minutes → X3's unit;
- and checks before anything is written:
  - the parent code is new (or flagged as an update);
  - every component exists in X3 (or is created as a new product);
  - every work centre is valid;
  - quantities are > 0.
- The user loads the files in Usage → Imports.
- Tested on the "IMPORT" parent part in test.

*Stage 2 – the target, once the API client exists.* An **"Estimate → X3" app** (a button / web page, the same pattern as the rebate app):
1. Reads the won estimate.
2. **Checks it live against X3 through the API**: does the part exist, do the components and work centres?
3. Shows a preview of what will be created or changed.
4. Writes the product, BOM, route and cost through the API (or submits the import through the batch server).
5. Returns the X3 references and keeps a log.

**Repeatable:** run it twice and it updates, never duplicates. Later, it's triggered by the won opportunity / project (OPP-04).

**Depends on:**
- the API client;
- the PHANT decision (sub-assemblies);
- Marc mapping OVEN;
- agreed part numbering (drawing no + rev).

**Live Orders with stock checks, BOMs and routes** (Dave Wright / Rachael Smith: "can't function without it").

*Check X3 standard first* (Acuity to demo):
- works-order planning;
- the MRP workbench / suggestions;
- the work-centre load inquiry;
- material shortages / availability;
- dashboards.

Part of the need may be standard. LO-01 (the sit-down) decides the rest.

*Likely build for the rest* – an SDI board fed by X3:
- **Data:** read through the API every 10–15 minutes (or pushed by webhooks), into a small SDI cache:
  - open works orders with their BOM and operations (MFGHEAD / MFGITM / MFGOPE);
  - sales orders (SORDERQ);
  - stock and allocations (STOCK);
  - open POs (PORDERQ);
  - BOMs (BOMD), routes (ROUOPE) and MRP suggestions.
- **Calculations:**
  - **Material status per works order:** explode the BOM × quantity, set against free stock, allocations and PO due dates. Red: short with no PO. Amber: short, covered by a PO arriving before the start. Green: available. It replaces today's free-text column.
  - **Work-centre load:** route time × quantity, by week by work centre, against capacity.
  - **WO suggestions** from MRP, with parts with **no BOM or no route** flagged red ("can't make yet").
  - **Exploded BOM with availability** (also covers REP-03).
- **Front end:**
  - an SDI-branded web board with filters (work centre, customer, due week, status);
  - drill-down from order → works order → exploded BOM;
  - Excel export;
  - notes / priority held on the SDI side, or in an X3 custom field via the API.
- **Depends on:**
  - the API client;
  - X3 work-centre capacities and MRP set-up (REP-08);
  - the PHANT decision;
  - LO-01, to agree columns, rules and who updates what.

**Suggested order:**
1. Estimating stage 1, now.
2. LO-01 sit-down and the X3 standard demo.
3. Once the API client exists: estimating stage 2 and a first Live Orders board (material status + work-centre load).
4. Each one proved against today's spreadsheets before anyone relies on it.

### 21.5 Estimating import, stage 1 – built (12 Nov) – EST-10 / SCRUM-210, 242–244

**`sagex3/estimating/est_to_x3.py <estimate.xls|xlsx> <out> --products <current ZSDIITM file> [--parent IMPORT] [--category FGML] [--rev-in-code]`**

It reads one estimate in Dave Wright's IMPORT layout (old .xls is converted with LibreOffice, keeping the calculated values) and writes the **same X3 load files as the migration kit**: identical columns, `;`, cp850 and CRLF, checked line against line.

**What it reads (the yellow cells):**
- **Parent:** E5 (drawing), H5 (revision), E4 (description).
- **BOM, by block:**
  - **Standard materials:** rows 11–25. Code I, link quantity L, scrap M.
  - **Wire:** rows 28–35. Code B (from the gauge → WIRE table), link quantity C (kg).
  - **Sheet steel:** rows 38–48. Code B, link quantity C (= quantity / parts per sheet).
  - **Other sheet material:** rows 51–58. Code B, link quantity C.
- **Route:** labour rows 63–100.
  - One operation for each line with a quantity and a rate.
  - **The X3 work centre is already in column R** (the sheet maps Access dept → X3).
  - Run time = column Q (minutes per unit); set-up = column M (minutes).
  - Description = column E, or the labour type (column D) when E is the placeholder "Description of labour n".
  - Operations numbered 5, 10, 15.

**What it writes:**
- `<code>_ZSDIITM` (only if the parent is new): category FGML, code = drawing number, "Rev B" in Description 2.
- `<code>_YA00408BOM`: BOM code 10, use status 2, sequence 10, 20 ….
- `<code>_ZSDIROU2`: route 10, site S01A, use status 1, time unit 2, mode 4.
- `<code>_CHECKS.xlsx` with these tabs:
  - **Checks:** each one STOP / WARN / INFO, with its cell;
  - **BOM read** and **Route read:** what was read, with the X3 category and description of each component.
  - The front tab says READY TO LOAD or NOT READY.

**Checks it makes:**
- Component exists in X3.
- Component's X3 description isn't "DONT USE".
- Work centre is a valid X3 code (from `work_centres.csv`).
- Quantity > 0.
- Parent new or existing.
- Labour lines naming a different parent.
- No more than 150 operations.
- Scrap % noted as not carried.

**Run on Dave's IMPORT.xls (10 Nov copy), 11290-00-73-GA rev B, estimate quantity 900, unit cost £466.98:** a new parent, 14 BOM lines and 30 operations. **NOT READY:**
- **STOP:** `SHEET METAL 10 / 11 / 12` are not products in X3. The sheet-steel block has no gauge → code table, unlike wire.
- **WARN:** FIXING49's X3 description is "DONT USE".
- **WARN:** the labour lines' parent (column C) says IMPORT, not the drawing.
- **INFO:**
  - scrap 4% on wire / sheet is not carried, because the X3 BOM template has no scrap column;
  - all 30 operation descriptions are placeholders, so the labour type is used.

`--parent IMPORT` builds the same files for Dave's test part in X3.

**Questions for Dave (rule 1d):**
1. What is the X3 product code for each sheet-steel gauge? Add a gauge → code table, as wire has, or type the real code in B38:B48.
2. What replaces FIXING49 ("DONT USE")?
3. Confirm the parent code is the drawing number, without the revision (as the migration), and that the category is FGML.
4. Will column E carry real operation descriptions?
5. Column C (labour parent) should follow E5 – a formula.
6. Scrap: build it into the link quantity, or ask Acuity to add the scrap column to YA00408BOM?
7. Confirm run time (Q) and set-up (M) are minutes.

The Material Price Break tab shows #VALUE!, so prices / costs (YITC) are not part of stage 1.

**Next:**
1. Dave's answers.
2. Load into TEST against the IMPORT part.
3. Compare in X3 with the estimate.
4. Stage 2 (API) when the API client exists.

**13 Nov – recorded:**
- **Register:** EST-10 → In progress; EST-01 → Built, with the blockers named. Rebuilt: 65 items.
- **Jira:** SCRUM-210 comment (stage 1 built, blockers, next steps).
- **E-mail to Dave:** the 7 questions above, drafted 12 Nov, for James to send.
- To revisit shortly.

### 21.6 The users' projects and how to implement each on X3 Cloud (13 Nov)

**Routes:**
- **Std:** X3 standard, configured by Acuity.
- **X3 build:** a Crystal report, a request / inquiry to Excel, or Safe X3 code, built by Acuity or by SDI if it is given development rights.
- **API app:** SDI's own tool reading / writing X3 through REST / GraphQL – the rebate-app pattern.
- **Import:** an X3 import file / template.

| Project (register) | Raised by | Likely implementation | Depends on |
|---|---|---|---|
| Live Orders board (LO-00..05) | Dave Wright, Rachael Smith | Demo of X3 standard first (WO planning, MRP workbench, WC load, shortages, dashboards); then an **API app** board: material RAG per WO (BOM explosion vs stock, allocations, PO dates), WC hours per week, MRP suggestions flagging no BOM / route, drill-down exploded BOM, Excel export | API client; LO-01 sit-down; WC capacities; MRP set-up; PHANT |
| Estimating import (EST-10..03) | Dave Wright | Stage 1 **Import** (built: `est_to_x3.py`); stage 2 **API app** button with live checks, preview, write, idempotent; later triggered by a won opportunity | Dave's answers; API client; PHANT |
| Estimating port (EST-00) | James | Estimating reads codes, costs, suppliers and rates from X3 via **API** (a nightly cache), parity runs against Access | API client |
| Opportunity → live project (OPP-00..06) | Marc's CRM minutes / James | **Import** or **API** create / update from SDI Live; a won opportunity creates the project dimension (Acuity bespoke / webhook); PDF fallback = link to an SDI store | Acuity design (OPP-04, 05); API client |
| Works orders auto-created (PRD-00) | James | X3 **Std** (order → WO, MRP) + automation; job cards = an X3 report | PHANT; MRP set-up |
| PO delivery by date, receive goods (REP-01, 02) | Simon Foister (Sam) | **Std** inquiries / reports | Acuity confirm |
| Exploded BOMs incl. cartons (REP-03) | Simon (Sam) | **Std** BOM explosion inquiry; else shares the Live Orders drill-down | Acuity confirm |
| Outstanding POs / SOs to Excel (REP-04, 07) | Simon, Debbie Freeth | **Std** + request to Excel | – |
| Export invoices (REP-05) | Ewa | Define, then **X3 build** (request / Crystal) | Ewa's sample |
| Debtors (REP-06) | Ewa | **Std** aged debtors (also the migration sign-off) | – |
| MRP suggestions (REP-08) | Simon | **Std** MRP | MRP set-up, PHANT |
| End-of-month stock, stock usage (REP-09, 10) | Simon | **Std** valuation / consumption | Valuation basis |
| Internal revenue, total revenue (REP-11, 12) | Simon | Define, then **X3 build** or **API app** | Simon's calculation |
| Stock tracking / locations / movements (REP-13) | Simon | **Std** stock inquiries | – |
| Production Live / Proto Live (REP-14) | Simon | Define the prototype flag (category or project type), then a request / board filter (Live Orders) | Definition |
| Project tracker (REP-15) | Simon | **X3 build** on the project dimension, or **API app** | OPP-04 |
| Manufactured sales (REP-16) | Simon | **Std** sales analysis filtered on made categories (FGML / PHANT) | Definition |
| Department on-time delivery (REP-17) | Simon | **API app** or Crystal: due vs delivered by department (WC / route) | Definition of the measure |
| SDI MRP by operator (REP-18) | Debbie, Selina Kuddus | Request: shortages on orders by order-entry user | New MRP |
| Delivered not invoiced (REP-19) | Debbie | **Std** | – |
| Tungsten EDI, YINVLIST (REP-20, 21) | Farhana Khan | Built by Acuity – UAT only | UAT |
| Rebate rolling report (REP-22) | Claire | **Done on Access** (ties to the penny, web app); X3 version via **API app** or request – same SQL logic on X3 invoices | API client; Claire's confirmations |
| Spreadsheets refresh / write-back (SHT-00, CS-02) | Selina, James | Read: request exports or Power Query on the API; write: imports / API only | Sheet list per team; API client |
| Customer Service UAT (CS-01..10) | Selina | Acuity training / config (project codes, back-to-back, global allocation, pro forma, dashboards); "&" rule kept; AI-drafted process documents (SDI) | Acuity dates |

**Pattern for every one:** define with the user → build in TEST → prove against Access (to the penny, as REP-22) → live via patch / deployment → runbook + register + Jira.

## 22. How we organise ourselves (13 Nov)

**One list:**
- The programme register (`register/register_data.py` → xlsx + html) is the single list.
- Every item has an owner, a status and a next action. Jira mirrors it, and this runbook holds the detail and the lessons.
- Nothing is worked on that isn't on the register.

**Weekly rhythm:**
- **Monday:** update the register and send the status report.
- **One session a week with Acuity,** agenda from the register.
- **Front foot:** for every item, do what SDI can do itself first (as with Dave's estimate), then take Acuity only what needs Acuity.

**Four tracks (13 Nov):**
1. Requirements basis.
2. Technical checks in the X3 UI.
3. The Acuity meeting.
4. The estimating import.

### 22.1 Requirements basis – checked against the e-mails

**Selina Kuddus, 8 Oct ("Sage update from Customer Services"):** every point is on the register as CS-01..10. The register's dates were corrected from "Nov 2026" to **8 Oct 2026** (13 Nov).

| Selina's point | Register | Still needed |
|---|---|---|
| Marc's list of standard reports – compare, have fewer reports | CS-01 | **Marc's list (ask in the meeting)** |
| Reports to Excel that refresh on opening; AM / PM requirements | CS-02 | Ask the AMs / PMs |
| Project-code training (several teams create codes) | CS-03 | Training date |
| Back-to-back orders: training, test asap | CS-04 | Jim's session date |
| "&" in codes (M&S); web-services risk | CS-05 | Decision: the migration already drops "&"; keep Sage's block |
| Global allocation back on | CS-06 | Update date |
| Pro forma / deferred sales payment term | CS-07 | Option added |
| Dashboards demo | CS-08 | Demo date |
| Real data in test; how much history (2–3 years SO history?); cleansing | CS-09 | **History decision**; cleansing so far = dormant accounts / inactive products left out |
| Documented processes with AI | CS-10 | Process list |

**Debbie Freeth, 13 Oct:** her daily Access reports:
- SDI Reports → SDI MRP (pull down DF) = REP-18;
- Sales → Reports → Outstanding Orders = REP-07;
- Sales → Reports → Delivered not Invoiced = REP-19.

James asked her on 19 Oct for screenshots, filters and content. **Not received.**

**Selina, 19 Oct (for Debbie):** "two of the orders… already on the list I sent through". **That list is still not held here.** Ask Selina for it again. SDI MRP by operator (REP-18) may be covered by the new MRP – to test.

**Gaps to close:**
- Selina's list.
- Debbie's screenshots and filters.
- Marc's standard report list.
- Replies from Sales, Estimating, Design and the rest of Finance / Purchasing (asked 7 Oct).
- The history decision.

### 22.2 Technical checks in the X3 UI (James, admin, TEST folder, read-only first)

These follow 21.3, with the "can we do it ourselves?" question added. Screenshot each answer.

1. **About:** version / update. Decides REST / GraphQL.
2. **Folders:** names of TEST / LIVE / demo.
3. **Connected applications / web services:** can our admin create an API client (connected app) ourselves? If yes, **we self-serve the API** and don't wait for Acuity.
4. **Users / roles:** what our admin role can create (users, requests, dashboards, templates).
5. **Requester / queries:** build a test query (e.g. open SOs) and export it to Excel. If it works, many "standard + Excel" reports are ours to make.
6. **Dashboards / landing pages:** can we build and share one (CS-08)?
7. **Import templates (GESAOE) and Imports:** can we run an import in TEST ourselves? Then load the estimate files for the IMPORT part (22.4).
8. **Report dictionary (GESARP) / Crystal:** what exists; whether the designer is available to us.
9. **Development menu:** visible and usable on SaaS? (Y / Z objects, scripts.)
10. **Batch server / recurring tasks:** can we schedule a query or an export?

Record each as one of: **can do ourselves / needs Acuity / not available on SaaS**.

### 22.3 Acuity meeting, 13 Nov – Marc, Shaleenah, Charlotte, James (90 min)

The agenda is in the chat (13 Nov). The pre-reads and the decision / action log go here afterwards.

### 22.4 Estimating – revisited (13 Nov)

- **SHEET METAL 10 / 11 / 12 are in X3**, as SHEETMETAL10 / 11 / 12. The migration code rule removes spaces, and the converter now applies the same rule (`common.product_code`) to every component and the parent.
- **Result: 0 stops.** The estimate can be loaded in TEST.
- **Remaining warnings:**
  - FIXING49 is "DONT USE" in X3. Candidates: FIXING2664 "M6 Half Hexagon Thinsheet" or FIXING2833 "M6 Thinsheet Nutsert Brass" (FIXING47 / 48 / 50 are the M4 / M5 / M8 thinsheet inserts, so FIXING49 was the M6).
  - The labour parent is IMPORT.
- **Questions to Dave, now with proposals** (in the chat, 13 Nov).
- **Lesson:** check codes through the migration's code rule before calling a code missing. The rule is what turns Access codes into X3 codes.

### 22.5 Attachments checked, gaps chased, Jira / register updated (13 Nov)

**Attachments (copied aside to `in_13nov/` in the scratchpad):**
- **`IMPORT.xls` and `Live_Orders.xlsx`:** byte-identical to the 10 Nov copies (`dave_in/`, same MD5). Nothing changes. The estimating converter (21.5 / 22.4) and the Live Orders analysis (section 20, LO-00..05) stand.
- **`TTI_Delivery_Schedule_2021_V3.xlsx`** (Selina, 28 Oct, "TTI Report", kept on OneDrive): **new requirement → SHT-01, Jira SCRUM-276** (under SCRUM-213).
  - **Layout:** a weekly schedule for the TTI group accounts (TIE02E / POL / UK / ENL, TIE16E, RYO03, RY001); tabs Oct 26 Wk 40 – Feb 27 Wk 8; 21 columns, almost all hand-typed; only pallet sums / ratios are formulas.
  - **Order columns X3 can supply:**
    - due date, account, SDI order no, customer PO;
    - part, description, qty;
    - delivery address, invoice number, pick / delivery note numbers.
  - **Logistics columns (manual):**
    - who pays / VAT route ("through French VAT");
    - origin China / UK / Poland, plus the China PO number;
    - trailer, pallets, number per pallet;
    - lorry from SDI / Poland, into ELC;
    - label + batch, booked in with TTI;
    - **proof of export** – evidence for zero-rated EU sales, so it needs a proper home.
  - **Links:** comments reference Live Orders dates and prototype projects (SDI-PROTO / CUST-PROTOTYPE → REP-14).
  - **Proposal:** an X3 query / API feed refreshes the order columns; the logistics stays in the sheet keyed by order line, or moves to X3 user fields on the order / delivery; invoice and proof of export come through from X3.
  - **Next:** a walk-through with Selina.
- **Not Selina's "list".** Her 19 Oct "list I sent through" is still unaccounted for. She may mean the TTI report – the e-mail asks her to confirm.

**E-mails drafted (13 Nov, in the chat):**
1. Selina – her report list, or confirm it was the TTI report.
2. Debbie – screenshots / filters / content for SDI MRP (DF), Outstanding Orders, Delivered not Invoiced.
3. Marc – the X3 standard report list.

**Jira (13 Nov):**
- SCRUM-276 created (SHT-01 TTI delivery schedule);
- SCRUM-212 comment (requirements check, gaps chased, TTI);
- SCRUM-210 comment (0 stops, Dave's confirmations).

**Register:**
- SHT-01 added (**66 items**);
- the TTI report added to Sources;
- REP-00 next action = chase the three gaps;
- Selina's items dated 8 Oct;
- EST-01 / EST-10 updated;
- xlsx + html rebuilt (`deliver/`).

**Standing rule (James, 13 Nov):** every change goes to **Jira and the register (xlsx + html)** as well as this runbook, in the same turn.

### 20.4 Key-account partnership rebate and referral tracking – REP-23, Jira SCRUM-277 (13 Nov, Charlotte) – FINANCE ONLY

**Confidential: Directors don't want the rebate figures visible to AMs.** So:
- **No agreement figures or customer names in git, Jira or the register.**
- The terms, account list and open points live in a **private parameters file** in the scratchpad: `finance_private/partner_rebate_params.json`, folder mode 700. The finance workbook and the revenue query are in the same folder.

**The agreement in outline** (customer's financial year September – August):
1. A progressive tiered rebate. **Marginal bands**: each rate applies only to revenue inside its band.
2. A year-end bonus at a flat rate on qualifying revenue above a two-year-average baseline.
3. A referral reward per introduced customer: a goods rate, and a higher rate on **separately invoiced** design services. It is capped per customer, with no overall cap, over **12 months from that customer's first qualifying invoice**.

"Qualifying revenue" = net invoiced **and collected**, excluding VAT, adjusted for credits, cancellations and returns. Group entities plus **agreed pass-through revenue invoiced via a third party**.

**Built – repo `sagex3/reports/partner_rebate/` (generic, no figures):**
- **`partner_rebate.py`:** the calculator.
  - Tiered (marginal), bonus and referral (with the cap), all to the penny.
  - `--check` proves it against **every worked example in the agreement – all agree**.
  - The agreement's examples round each part to the pound and then add them, so one example is £0.85 from the exact pence figure. The agreement itself says reconcile to pence.
  - Revenue above the top band has no agreed rate (an open admin point), so it is shown separately and not priced.
- **`build_model.py`:** writes the finance-only workbook (proved by LibreOffice recalculation: the same figure as the calculator).
  - **Calculator:** live formulas, one input cell.
  - **Estimate:** monthly actuals by account, with the pass-through share entered by hand, and a run-rate projection.
  - **Referral register:**
    - introducer, registration, SDI confirmation;
    - first invoice → window end (EDATE);
    - goods / design → reward, capped.
  - **Open points.**
- **Private:** `partner_revenue.sql` (read-only, monthly invoiced by account from Sep 2024, the third party's lines for review, the sales-ledger columns). Its purpose is to reconcile to the agreement's two baseline years.

**Open points** (in the workbook):
- Entity scope: one group entity named in the agreement has no SDI account; a hearing-care entity and an Ireland entity – in or out?
- Which of the pass-through account's orders count.
- Collected vs invoiced.
- Revenue above the top band.
- Design services as a separate product / category.
- Settlement method.
- Confidentiality in X3.

**Tracking in X3 (proposal):**
- **Group scope:** a customer statistical group / user field on the group's accounts.
- **Pass-through:** an analytical **dimension or order flag** on the third party's orders that are the partner's work, so the revenue flows to the invoices.
- **Referrals:**
  - a **referral flag on the introduced customer**, plus a register of introducer, registration date (before selling – the X3 opportunity fits: OPP flow) and SDI confirmation;
  - the first qualifying invoice date and the 12-month window, derived from invoices.
- **Design services:** a separate product category so they're invoiced separately.
- **Confidentiality:**
  - the rebate report and the accrual / provision account are in **finance-only** functions and rights;
  - the AM sales report shows revenue only;
  - the monthly accrual is posted by Finance;
  - settlement is by credit note or payment, per the agreement.

Charlotte is checking how today's daily sales report hides the rebate by customer.

**Next:**
1. Charlotte: scope and open points.
2. James: run `partner_revenue.sql`.
3. Reconcile the baseline years.
4. Current-year estimate.
5. Referral register populated.
6. The X3 set-up with Acuity.

**13 Nov – e-mail to Charlotte drafted (in the chat):** the full explanation, how the calculator was proved, the estimate method, X3 tracking and confidentiality, and the questions. The questions are:
- entity scope (beauty, hearing-care, Ireland);
- pass-through identification;
- above the top band;
- settlement;
- brand meaning;
- collected-revenue source;
- quarterly referral reporting owner.

**Working today:** the calculator and the finance workbook (manual monthly figures can be typed in).

**Waiting on:**
- the revenue query results (baseline reconciliation, actuals);
- Charlotte's answers;
- the X3 set-up.

**13 Nov – first revenue run (results kept in the finance-only folder):**
- Accounts found by name: six partner-group accounts plus the pass-through account. One group account has no invoices since Sep 2024.
- **The invoice-line totals do not reproduce the agreement's baselines:**
  - year 1: the closest combination (the main UK account + optical + all pass-through) is ~£32k under;
  - year 2: even all accounts together are ~£454k under.
- **So the agreement's figures were not built from invoice lines.** Either lines without an order-line price drop out of the left join, or invoicing bypasses order lines (sales-ledger invoices, e.g. services).
- **Follow-up:** `partner_revenue_2.sql` (private): sales-ledger net (`ST_NETT`, INV / CRN) by account and month, still-unpaid (for "collected"), the count of unpriced invoice lines, and the pass-through account's lines by part-code prefix (BOT- = partner work?).
- **Lesson:** reconcile to the agreed figures before estimating – the obvious source (invoice lines) was not the agreement's source.

**13 Nov – ledger run (`partner_revenue_2.sql`, results in the finance-only folder):**
- **The sales-ledger net (INV − CRN) equals the invoice-line totals exactly**, and no invoice lines are unpriced. Access is consistent with itself.
- **The gap is real:**
  - year 2 is ~£454k under the agreed figure even with every group account + all pass-through;
  - year 1: main + optical + all pass-through is ~£32k under (invoice-only ~£27k over).
- The pass-through account's lines by prefix: partner-design parts (BOT-), its own codes (SRS-), project parts (11367-, 11019-), carriage, and other retailers' parts (M&S-, BRI-). **Only part of it is the partner's work.**
- **Hypothesis:**
  - revenue on accounts not named for the group (e.g. the group's beauty company / brand company) – `partner_revenue_3.sql`, which looks for accounts by name and brand;
  - or the agreement used a different basis (orders, a different date, or another ledger).
- **"Collected":** the ledger's still-unpaid column is available for the year-end test.
- Ask Charlotte which report produced the baseline figures.

**13 Nov – account search (`partner_revenue_3.sql`):**
- No other group, brand or beauty-company accounts: the same seven (one has no revenue).
- **No combination of accounts reproduces the agreement's two baseline years**, with or without VAT on any account.
  - Best year-2 fit is still ~£43k out, and it doesn't fit year 1 at the same time.
- **Conclusion:** the baselines came from a source other than Access's sales ledger / invoice lines. Possibilities: Boots' own purchase data, orders, another period basis, a pro-forma / manual adjustment.
- **The question goes to Charlotte** (e-mail redrafted in the chat with the reconciliation table).
- **The estimate is on hold** until the definition is known.
- The current-year-to-date figures are held in the finance-only folder.

**13 Nov – finance workbook v2 (`build_model.py`, private output):**
- **New "How to use" tab** (first): what it is, the tabs, then step by step – rebate for a figure, monthly actuals, pass-through share, projected rebate, referrals, year end – plus the built-in checks, what not to overwrite, and support.
- **New "Reconciliation" tab:** each account by agreed year, all accounts, the agreed figure, the difference; note that no combination reproduces both years.
- **Estimate:** pre-filled from the sales-ledger run (INV − CRN by month); the pass-through share is entered by Finance (yellow); all pass-through work is shown greyed for reference, not counted.
- Accounts and names now come from the private parameters file (Access codes; X3 codes noted).
- **Proved** by LibreOffice recalculation:
  - Calculator at the example figure = the calculator script;
  - Reconciliation totals = the ledger analysis;
  - the run rate counts the current part-month as a month, so it understates early in a month.

### 22.6 Back to estimating and Live Orders (13 Nov, after the Teams set-up)

**Estimating – IMPORT test part built:**
- `est_to_x3.py dave_in/IMPORT.xls est/out_IMPORT --products Ethan_fixes_2026-11-05/ZSDIITM_products_MAPPED.xlsx --parent IMPORT` gives **0 stops, 1 warning** (FIXING49 "DONT USE"), a 14-line BOM and 30 operations.
- **Load order in TEST:**
  1. ZSDIITM, only if IMPORT is not already a product in TEST. The products file is the migration list, so it reports IMPORT as new.
  2. YA00408BOM.
  3. ZSDIROU2.
- Then compare the BOM and route in X3 with the estimate.
- FIXING49 stays until Dave picks FIXING2664 or FIXING2833. It is a warning, not a stop, so the test load can go ahead.

**Live Orders (LO-00) – stage 1 without the API.** The same idea as estimating stage 1: don't wait for the API client.
- X3's own inquiries and export templates give the data: works orders and their operations / material lines, sales-order lines, stock, POs, BOMs, routes and MRP suggestions.
- An SDI builder then reproduces Dave's three tabs.
- **Column map for `Live_Orders.xlsx`, 41 columns** (X3 objects to confirm with Acuity):

| Live Orders column(s) | Comes from in X3 |
|---|---|
| Due date | Works-order end date |
| Customer Date | Sales-order line requested date, via the WO's originating order (the sheet's own lookup is broken: `#REF!`) |
| WO Num / SO Num | WO number / its originating SO and line |
| Part code, Description, Drawing, Rev | Product master (drawing = code; rev in Description 2, as migrated) |
| MATERIAL STATUS | WO material lines: allocated vs shortage, with PO due dates → RAG. Replaces today's free text |
| QTY / Booked in / Balance | WO planned / completed / remaining quantity |
| Metal / Joinery / Acrylics | Derived from the work centres on the WO's route |
| LASM … PACP (23 columns) | Remaining hours per work centre from the WO operations; the codes are already X3 work centres |
| Tube req, Comments, Prog | Manual, kept on the SDI side keyed by WO (or X3 user fields) |

- **WO Suggestions tab:** MRP suggestions, with "has BOM / has route" flags; red where either is missing.
- **BOM Report tab:** BOM explosion × quantity, against stock, on PO (with due date), on WO, make / buy.
- **"MCS"** (column 38) is still to be confirmed with Dave.

**Next:**
1. James to approve building the stage-1 board.
2. Prove it from Access today, so it can be compared line for line with Dave's sheet.
3. Switch the source to the X3 TEST exports.
4. LO-01 sit-down to agree columns and rules.

**Recorded:**
- Register: EST-10 and LO-00 next actions;
- Jira: SCRUM-210 and SCRUM-241 comments.

### 22.7 A real estimate from the estimating template (13 Nov) – the converter reads it, and it matches Access

**What James sent:** a real estimate made by the estimators (Tim, 1 Sep 2026) on today's template: **12539-04-GA (0359869) rev B, GIFT CARD HEADER**, quantity 40, unit cost £33.02. It is kept in the scratchpad (`est_in_13nov/`), not in git, because it holds customer data.

**How it relates to IMPORT.xls.** IMPORT.xls is Dave's copy of the **same template with X3 columns added**: component code (B / I), link quantity (C), X3 work centre (R) and run minutes (Q). The real template is one column to the left, and it has:
- **Codes:** standard-material codes in **H**.
- **Sheet steel:** **no code**, only gauge (H) and sheet size (I × J).
- **Other sheet material:** **no code column**.
- **Labour:** by **Access department** (G), with a rate per hour (I) and set-up minutes (L).
- **Parent:** the part code is in the labour block, **A63** (`M&S-0359869`), not the drawing number.
- A **Route Import** tab: the route as the Access import takes it (part code / op number blank).

**Converter (`est_to_x3.py`) now reads both layouts**, told apart by row 10 ("Part code" in H10 = the template):
- **Parent:** A63, through the migration code rule (M&S-0359869 → MS-0359869). Found in X3 (FGML), so only the BOM and route are written.
- **Work centre:** Access department → X3 from `work_centres.csv` (the migration's own map).
- **Run time:** 60 / rate × qty, in minutes per unit.
- **Sheet steel:** gauge + sheet size → the X3 SHEETMETAL product whose Description 2 / 3 reads "L x W x Tmm CR4". `--sheet-material` picks ZINTEC / Galvanised instead. Each pick is listed, with the other materials X3 has for that size.
- **Other sheet material:** the code is taken from the first word of the description, with a WARN. The template has no code column there.
- **Repeated components** are merged into one line, as Access holds them.
- **IMPORT layout output is unchanged** (all three files byte-identical).

**Result: 0 stops, 0 warnings.** BOM 8 lines, route 9 operations.

**Proved against Access:** the part's migrated BOM and route (`track2/Clean_run/*_load7_*`):
- **Route: identical**, operation for operation (work centre, description, set-up, run). The only difference is "ASSEMBLE/BULK PACK" against "ASSEMBLE-BULK PACK"; today's migration text rule also turns "/" into "-".
- **BOM: the same 8 components and quantities.** The one difference is SHEETMETAL11: 0.015848 (exact, two parts added) against Access 0.016, which Access rounded up.

**This answers 5 of the 7 questions to Dave (21.5), from the evidence:**
- **Q3 parent:** it is the part code in A63, not the drawing number. The IMPORT layout keeps E5.
- **Q4 descriptions:** the real template carries them (column D).
- **Q5 labour parent:** A63.
- **Q6 scrap:** Access does not carry it on the BOM either, so we match it.
- **Q7 minutes:** confirmed, because the route matches Access.

**Still open:**
1. FIXING49 (IMPORT only).
2. **Sheet material:** the template has no material, so CR4 is assumed. Add a material column, or type the code.
3. **Other sheet material:** add a code column.
4. Wire gauges 2 / 2.5 / 4.5 / 10mm have no code in the template's gauge table.

**Files:** `est/out_GIFT/` (scratchpad) – MS-0359869 YA00408BOM / ZSDIROU2 / CHECKS.

**Recorded:**
- Register: EST-10 and EST-01;
- Jira: SCRUM-210.

### 22.8 Outlook outage (13 Nov) – today's emails held, plus one to Simon

A Microsoft-wide Outlook outage meant **none of today's emails went out**. They are kept, unsent, in the scratchpad (not git):
- `outbox_13Nov/UNSENT_emails_13Nov.md`:
  1. Selina (report list / TTI);
  2. Debbie (three daily reports);
  3. Marc (standard report list – "before today's meeting" replaced by Wed 18 Nov);
  4. **Dave – rewritten after 22.7**: four questions (sheet material, other-sheet code column, wire gauges without codes, FIXING49) and a TEST session on the IMPORT part;
  5. **Simon – new**: his 6 "needs definition" reports (REP-11, 12, 14, 15, 16, 17), with **REP-14 prototype vs production the priority** because it feeds Live Orders; Ewa cc'd for export-invoice samples (REP-05). His 10 likely-standard reports are listed for information.
- `finance_private/UNSENT_Charlotte_partner_rebate_email_13Nov.md` (confidential, mode 600).

The dates assume sending on Mon 16 Nov.

**Company notice during the outage:** a Teams team **"WeAreSDI – All Company"** was created:
- Private, 114 members added from the All Users group;
- channel **Announcements**;
- the outage notice was posted with an @team mention.

**Follow-ups:**
- the Global Admin to convert it to Org-wide (Teams admin centre → Teams → Manage teams → Privacy), so new starters join automatically;
- post the all-clear when Outlook is back.

**Lesson:** an all-staff channel didn't exist before this outage. Keep this one, so that the next outage doesn't depend on email.

### 22.9 IMPORT.xls has no macro – how it was meant to work (13 Nov)

**Checked:** neither IMPORT.xls nor the real estimate contains a VBA project, macro, button or shape. The only names in them are Excel's own filter names.

So IMPORT.xls is **a mapping, not a tool**. Dave added columns that mirror the X3 import fields:
- B "Component Type" → CPNTYP;
- C "UOM link quantity" → LIKQTY;
- R X3 work centre → WST;
- Q run minutes → OPETIM.

The cells were meant to be copied into X3's import layouts by hand, or picked up by something Acuity would build. Likewise, the estimate's **Route Import** tab is the flat table that Access's own route import reads. Nothing in the workbook does it automatically.

**The converter (`est_to_x3.py`) is that missing button.** It reads the estimate itself, so the IMPORT columns aren't needed.

**Proposed:**
1. A small "Estimate → X3" page, the same pattern as the rebate app: drop the estimate in, see the checks, download the files, then load them in Usage → Imports.
2. Later, stage 2 posts them through the API.

An Excel macro in the template was considered and **not recommended**. It would be harder to maintain and to check, and it would need the macro security settings changed on every estimator's PC.

**22.9 follow-up – email to Dave Wright and James Ryan (drafted 13 Nov, held for the outage).** It replaces the earlier Dave email in `outbox_13Nov/` and asks for the full import process.
- **Sets out** what we know.
- **14 numbered questions:**
  - today's Access steps: when, who, menu path for the Route Import tab, how the BOM gets in, who creates the part code, what else is set up, who checks, volume;
  - revisions and repeats: replace or version; whether made sub-parts become their own parts;
  - the template's gaps: sheet material, other-sheet code column, wire gauges without codes, FIXING49, scrap.
- **Asks for 30 minutes** watching a real Access import, then a TEST load of the IMPORT part.
- **Reply by Fri 20 Nov.**
- **Written to be answered in place** (proposals to agree, one-line answers), so a slow reply is still usable.

### 22.10 Estimate → X3 page built; X3-side gaps and questions for Acuity (13 Nov)

**`sagex3/estimating/est_app.py` – the "button" for the estimating import** (the rebate app's pattern: stdlib server, port **8766**, runs kept in `runs/`, gitignored).

    set EST_PRODUCTS=<latest ZSDIITM file or X3 product export>
    python est_app.py            (add --host 0.0.0.0 to share inside SDI; no login)

- **Upload an estimate** (either layout).
- **Options:**
  - part code override (e.g. IMPORT);
  - category FGML / FGSL;
  - sheet material CR4 / ZINTEC / Galvanised;
  - revision in the code;
  - a newer product list, used for that run only.
- **The result page shows:**
  - **READY TO LOAD / NOT READY**;
  - the part (new or existing), layout, BOM / route counts;
  - every check, STOP first, by cell;
  - the BOM and route as read, with each component's X3 category and description;
  - the files and a zip;
  - the load order in Usage → Imports.
- **Existing parts get a red warning:** load in TEST only, or as the IMPORT test part, until Acuity confirm whether the import replaces or adds lines.
- "Send to Sage X3" is shown but disabled (stage 2, needs the API client).

**Tested** (scratchpad `est_app_runs/`, screenshots `est_app_shots/`):
- the gift card estimate and Dave's IMPORT.xls give **byte-identical files to the command line**;
- a wrong file type is refused;
- path tricks return 404;
- the zip and file downloads work;
- no horizontal scroll at phone width.

**X3-side gaps → email to Acuity (Neil; cc Marc, Jim, Charlotte), held for the outage (`outbox_13Nov`, email 6).** 24 questions, reply by Fri 20 Nov:
- **A. Connection details (TEST, then LIVE):**
  - base URLs (REST / GraphQL / SOAP) and folder names;
  - connected app (client ID / secret) and an SDI integration user and role;
  - IP restrictions, rate limits, licence use;
  - API documentation, including write.
- **B. Estimating import:**
  - **re-import of an existing part – replace, add or reject** (the blocker for LIVE use);
  - does ZSDIITM create the product-site (S01A) record works orders need;
  - a scrap % field in YA00408BOM;
  - the revision approach (replace / alternative / validity);
  - costs (YITC / price lists);
  - OVEN, SALV, and time unit 2 = minutes;
  - user rights to run imports and see the log;
  - a schedulable product and work-centre export for the page's checks;
  - stage 2: API write or import file via the batch server.
- **C. Live Orders:**
  - read access (API object or export template) to works orders (header / products / operations / materials), SO lines, stock and allocations, PO lines, BOMs, routes and MRP results;
  - works-order webhooks;
  - automatic allocation / global allocation;
  - the WO → originating SO link;
  - work-centre capacities and MRP in TEST;
  - user fields on the WO for Production's notes;
  - a demo date for the standard planning screens.
- **D. Live Enquiry → opportunity:**
  - opportunity template / API write;
  - drawings and PDFs on SaaS (attach or link);
  - won → project design, date and event.
- **E.** The items still outstanding from the 12 Nov requirements email (21.2).

**Priority if Acuity can only do a few:** items 1–2 (API client) and 6 (re-import behaviour).

**Recorded:**
- Register: EST-10, LO-00;
- Jira: SCRUM-210, 241, 208.
