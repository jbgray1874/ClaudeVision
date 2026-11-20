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
- **Parent:** the part code is in the labour block, **A63** (the customer part code, e.g. `XX-0359869`), not the drawing number.
- A **Route Import** tab: the route as the Access import takes it (part code / op number blank).

**Converter (`est_to_x3.py`) now reads both layouts**, told apart by row 10 ("Part code" in H10 = the template):
- **Parent:** A63, through the migration code rule (e.g. `X&Y-0359869` → `XY-0359869`: "&" and spaces removed). Found in X3 (FGML), so only the BOM and route are written.
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

**Files:** `est/out_GIFT/` (scratchpad) – the part's YA00408BOM / ZSDIROU2 / CHECKS.

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

### 22.11 Live Orders board built (13 Nov) – LO-00..05, Jira SCRUM-241 / 245–249

**Code – `sagex3/production/live_orders/`:**
- **`live_orders.sql`:** read only. Grids CHECK / WOR / SOH / POH / SMR: open works orders (ASC_WOR_TBL), open SO lines, open PO lines and stock (the migration views, already in X3 codes). It uses the same grids as `extract_transactions.sql`, so **either file feeds the board**.
- **`build_live_orders.py`:** extract + master data in X3 form → `SDI_Live_Orders_<date>.html` + `.xlsx`. Master data:
  - the products file (ZSDIITM);
  - BOMs (YA00408BOM);
  - routes (ZSDIROU2);
  - `work_centres.csv` for the Access names.
  - So codes and work centres are already X3's. After go-live, only the transaction source changes (X3 export or API).
- **`live_orders_app.py`:** web page on port 8767.
  - "Refresh from Access" through pyodbc (SDI_SQL_CONN, read-only), or upload a saved result.
  - Boards kept in `runs/` (gitignored).
  - Master files from LO_PRODUCTS / LO_BOMS / LO_ROUTES; optional LO_DAVE to compare against Dave's workbook.

**What it works out (Dave's three tabs and more):**
- **Live Orders:** one row per open WO. Balance = (amended or ordered) − made.
  - **Customer date:** from the WO's sales order (order + product, else the order). "SO not open" if the order isn't open; "Check SO dates" if it has several dates (Dave's own formula, which was broken with #REF!).
  - Part, description, drawing (part code without the customer prefix), rev.
  - **Material status:** BOM × balance. Stock is shared out in due-date order; shortages are covered by open PO lines, then by works orders for made components.
    - **GREEN** in stock;
    - **AMBER** covered on time, or a call-off material still to order;
    - **RED** short / late / no BOM.
    - Call-off list (provisional): SHEETMETAL, POWDER, PACK, PALLET, WIRE, CARRIAGE.
  - Metal / Joinery / Acrylics from the route's work centres (M / J / A).
  - **Hours** still to do per X3 work centre: run × balance, + set-up if nothing is made yet.
  - Comments / Prog / Tube req are left blank for Production (LO-01).
- **Work-centre load:** hours by week of the due date; overdue counts in this week. Heat-shaded.
- **WO Suggestions:** SO lines for made parts (BOM, route or FGML) not covered by stock or open WOs. Start = SO due − 14 days. Red = no BOM or no route.
  - SO lines due more than 60 days ago are **not** suggested; they're listed on Checks.
- **Exploded BOMs:** all levels, with stock, on PO (next due), on WO and make / buy. A drill-down per WO on the page.
- **Check against Dave:** WO by WO against `Live_Orders.xlsx`.

**Run on the live Access extract of 4 Nov 18:39** (`runs/2026-11-04-pm/extract/extract_transactions.txt`) with the 4 / 5 Nov master files:
- **731 WOs to make** (250 top level):
  - 170 green, 291 amber, 270 red;
  - 9 with no BOM, 10 with no route;
  - **11,103 hours** to do;
  - 135 overdue.
- **145 WO suggestions** (10 with no BOM / route).
- **Against Dave's sheet** (saved ~9 Oct, 220 WOs): **102 still open – part the same on all 102, balance the same on 98**. 118 have been completed since.
- **Data findings for go-live:**
  - **1,508 of 3,728 open SO lines were due more than 60 days ago.** They migrate as open orders (re-dated to 30 Nov in SOHPJ) – to Selina / CS to close or re-date.
  - **135 overdue WOs**, some from 2024–25 – to Dave.
- **Tested:** the page builds from an upload; Refresh is refused cleanly with no connection; filters work (157 red top-level WOs); the drill-down is readable; no JS errors; phone width OK.

**Outputs (scratchpad):** `live_orders/SDI_Live_Orders_2026-11-04.html / .xlsx`, screenshots in `live_orders/shots/`.

**Email to Dave + Rachael (cc Selina), held for the outage – outbox email 8:** 12 questions:
1. the material rule;
2. the call-off list and horizon;
3. top-level vs sub-assembly rows;
4. which due date drives planning;
5. hours to do vs total, and set-up;
6. MCS;
7. Comments / Prog / Tube req as X3 user fields;
8. booked in = made;
9. the 135 overdue WOs;
10. the 1,508 old SO lines;
11. the 14-day suggestion lead;
12. weekly capacity per work centre.

**Next:**
1. James runs `live_orders.sql` today (read-only), or uses the page's Refresh on an SDI PC, to see today's board.
2. Dave / Rachael's answers.
3. LO-01 session.
4. Switch the source to X3 TEST (Acuity email 6, section C).

### 22.12 Where we are – 13 Nov (Outlook outage day): estimating, Live Orders, Acuity, users

| Workstream | Built | Proved | Waiting on |
|---|---|---|---|
| Estimating → X3 (EST-10) | `est_to_x3.py` (both layouts) + `est_app.py` page | Gift card estimate = the part's Access route exactly; BOM the same 8 components | Dave + James Ryan (email 4); Acuity B (email 6); a TEST load of IMPORT |
| Live Orders (LO-00..05) | `live_orders.sql` + `build_live_orders.py` + `live_orders_app.py` | 102 of Dave's WOs: part 102 / 102, balance 98 / 102 | Dave + Rachael (email 8); Acuity C (email 6); LO-01 |
| Live Enquiry → opportunity (OPP) | not started – needs Acuity's design | – | Acuity D (email 6) |
| Rebate report (REP-22) | report + `rebate_app.py` | = Claire's November report to the penny | Claire + Nick (email 7) |

**From Acuity / Sage (email 6, 24 questions):**
- **A. Connection details:** base URLs, connected app / client ID and secret, integration user, IP restrictions, rate limits, licences, API documentation.
- **B. Estimating:** re-import replace / add / reject; product-site; scrap; revisions; costs; OVEN / SALV / time unit; rights; product export; stage-2 route.
- **C. Live Orders:**
  - read access to WOs (header / products / operations / materials), SO lines, stock and allocations, PO lines, BOMs, routes, MRP;
  - WO webhooks;
  - allocation;
  - WO → SO link;
  - capacities and MRP in TEST;
  - WO user fields;
  - a standard-screens demo.
- **D. Opportunity:** template / API write; PDFs; won → project.
- **E.** The 12 Nov items (development rights, reporting, MCP, Vasion).

**Users – emails held in `outbox_13Nov/UNSENT_emails_13Nov.md` (8 emails) + `finance_private/` (Charlotte):**
1. Selina – report list / TTI.
2. Debbie – her three daily reports.
3. Marc – standard report list.
4. Dave + James Ryan – the estimating import process (14 questions).
5. Simon (+ Ewa) – 6 report definitions.
6. Acuity – 24 X3-side questions.
7. Claire + Nick – the rebate report.
8. Dave + Rachael – Live Orders (12 questions).
- Charlotte (private) – the partner rebate.

**Answers already in hand (no need to ask again):**
- Estimating: the parent = A63 part code; descriptions in D; scrap not on Access BOMs; run minutes = 60 / rate × qty (route matches Access).
- IMPORT.xls has no macro.
- Live Orders: Dave's WO numbers = Access top-level WO numbers; his customer-date formula is broken (#REF!).

**Lesson (13 Nov):** part codes carry a customer prefix (e.g. a retailer's initials). Sections 22.7 and 22.11 first went into git with a real customer-prefixed part code. That was corrected in the next commit (history not rewritten, as with c45777d). **Use a neutral example (XX-…, ABC-…) in git; real codes stay in the scratchpad.**

### 22.13 First live run of live_orders.sql (13 Nov, 11:45) – board rebuilt from today's Access data

James ran `live_orders.sql` in SSMS (Results to Text, tab-delimited) and uploaded the output: 741 WOR, 3,880 SOH, 781 POH and 8,626 SMR rows, plus the CHECK as-at line. **It built first time; the parser needed no changes.** The output is kept in the scratchpad (`in_13nov/lo/`), not git.

| | 4 Nov | 13 Nov |
|---|---|---|
| Works orders on the board | 731 (250 top level) | 703 (260 top level) |
| Green / amber / red | 170 / 291 / 270 | 169 / 261 / 273 |
| Hours | 11,103.2 | 8,125.0 |
| WO suggestions | 145 | 118 |
| Overdue WOs | 135 | 99 |
| SO lines more than 60 days late | 1,508 | 1,557 |
| No BOM / no route | 9 / 10 | 51 / 52 |

- Between the two runs, 204 works orders were opened and 232 closed.
- **No BOM / no route rose because master data is still the 4 Nov mapped set.** The parts created since 4 Nov (new GA numbers, PROTOS, SUB… subcontract codes) aren't in it. **This is not a fault.**
  - Every refresh must use the current ZSDIITM / BOM / route set: the next migration extract, or X3 after go-live.
  - Otherwise new parts show no hours.
- **Against Dave's sheet:** 49 of his 220 rows are still open; for all 49 the part matches, and for 43 the balance matches. The other 171 have closed since he saved it.
- **Email 8 (Dave + Rachael)** still quotes 4 Nov, so it goes with the 4 Nov files. The 13 Nov board is the live version to show them.

**Lesson:** a Live Orders refresh is only as current as its master data. Refresh LO_PRODUCTS / LO_BOMS / LO_ROUTES alongside the transactions.

**Simon's email (email 5):** this answers his report list of **13 Oct 2026**: 17 reports (REP-01–17) for himself, Sam and Ewa. Nothing newer has come from him.

### 22.14 Held emails sent (Fri 13 Nov, after the Outlook outage) – Simon's held back for a rewrite

| # | To | Sent | Attachments | Reply by |
|---|---|---|---|---|
| 1 | Selina | 13 Nov | – | Tue 17 Nov |
| 2 | Debbie (cc Selina) | 13 Nov | – | Tue 17 Nov |
| 3 | Marc (cc Charlotte) | 13 Nov | – | Wed 18 Nov |
| 4 | Dave + James Ryan | 13 Nov | `Estimating_to_X3_examples.xlsx`: one workbook with a Read me tab (Gift Card + IMPORT: summary, BOM, route, checks) | Fri 20 Nov |
| 5 | Simon (cc Ewa) | **Not sent**: being rewritten to quote his 13 Oct email, with his report list attached | `Simon_Foister_reports_for_Sage_X3.xlsx` | Fri 20 Nov |
| 6 | Acuity (Neil; cc Marc, Jim, Charlotte) | 13 Nov | – | Fri 20 Nov |
| 7 | Claire + Nick | 13 Nov | Rebate HTML + xlsx | – |
| 8 | Live Orders (Dave / Rachael) | 13 Nov | 4 Nov board, HTML + xlsx (matches the figures in the email) | Fri 20 Nov |
| – | Charlotte (finance only) | 13 Nov | Finance-only workbook | – |

**Lessons (James, 13 Nov):**
- **Never send a pile of raw files.** The first email 4 set was 12 files: Sage load .txt files plus four separate workbooks. It was cut to **one workbook with a Read me tab** that says what every tab is for.
- **Every attachment needs a short "what this is" paragraph in the email body.**
- **Machine load files (.txt) are for Acuity / TEST only, never for users.**
- **Send one version of a board.** Sending the 4 Nov and 13 Nov boards together would show the same people two versions.
- **A reply email must say what it's replying to** (the sender's own email and date) and map each item to the register / Jira reference, so the recipient knows what relates to what. Attach their own list back to them, with a column for their answer.
- Dave's auto-reply: off 13 Nov, back Mon 16 Nov.

The register has been rebuilt (as at 13 Nov): REP-00, REP-05, REP-11–17, REP-22, REP-23, EST-01, EST-10 and LO-00 updated.

### 22.15 Finance's quantity-rebate provision workbook (14 Nov) – REP-23 widened to every rebate scheme (finance only)

Charlotte sent Finance's month-end **quantity rebate provision workbook**. It is **finance only**, so the customer names, rates and values are **not** recorded here, in Jira or in the register. The workbook is kept in the private finance folder.

**What it is:**
- One sheet per rebate customer (eight schemes, including the partner scheme and its referral bonus), plus a summary.
- Each sheet holds:
  - net sales by month, typed in by customer account;
  - the cumulative total for the scheme year;
  - a tier table;
  - the provision required;
  - the monthly movement.
- The summary carries every scheme, plus unreleased prior-year balances, to **one accrual nominal**.

**What it gives us:**
- **The full list of rebate schemes.** REP-23 widens from one partner to a single provision run that covers every scheme.
- **The typed monthly sales come from the sales ledger.** The partner sheet's four month cells match our Access ledger extract **to the penny** (invoices less credit notes, ex VAT). So the typing can be replaced by a query: Access now, X3 after go-live.
- **It answers two partner-scheme questions:**
  - Finance includes two of the group's accounts, the pass-through account, and a third brand whose account is still "??". The Ireland and hearing-care accounts are not included.
  - The scheme year starts in September.

**Questions for Finance:**
- Scheme years differ by customer. Confirm each one.
- For each scheme, is the rate **banded** (each rate only on its band) or **retrospective** (the step rate on the whole year)? The sheets use both.
- One tier table has a lower rate in its first band than in its second.
- One customer's band formulas don't match its own tier table (no effect this scheme year).
- One summary row is typed in, not linked to its sheet.
- Two accounts are marked "Less VAT".
- Two further customers are noted but have no sheet.
- What happens to the prior-year balances (release or settle)?
- REP-22's 6% scheme isn't in this workbook.

**Next:**
- James runs `quantity_rebates_sales.sql` (read-only, private finance folder), so every typed month can be reconciled to Access.
- Then we build the provision run: one parameter table per scheme, the same sheets and summary, and the movement for the journal.
- This lesson goes with the others: **finance rebate data stays in the private folder, whatever the scheme.**

**14 Nov, reconciled.** James ran `quantity_rebates_sales.sql`. We compared every monthly sales figure typed on Finance's workbook (Jan–Oct 2026) with the Access sales ledger (invoices less credit notes, ex VAT).
- **Where a cell holds a straight ledger figure, Access matches to the penny:** 115 of 137 typed cells. The scheme-year totals carried forward from 2025 also match exactly.
- **The other cells are of two kinds:**
  - deliberate adjustments in formulas (a rebate credit note added back, "less VAT" deductions, prior-year moves, year-end deductions);
  - a few unexplained differences (one typo'd account code, one possible typing slip).
- **Accounts the workbook leaves out:** Access has accounts for the same customer groups that aren't on the workbook, some with material sales. They're listed for Finance to say in or out.

The finance-only check workbook (28 questions) is in the private finance folder only.

**Design rules to agree before the monthly sales come from the ledger:**
1. **Rebate credit notes must not reduce qualifying sales.** We need a way to identify them in Access and X3, e.g. a nominal code or a product.
2. **Adjustments need a reason that can be recorded.** Each exclusion or move becomes a rule or a logged manual line, not an edit inside a formula.
3. **Each scheme gets an explicit list of accounts.**

### 22.16 Rebates – where everything stands (14 Nov): REP-22 (Claire / Nick) and REP-23 + quantity rebates (Charlotte, finance only)

SDI has **three kinds of rebate**. They are separate, and each needs its own data rules:

| | REP-22 Rebate rolling report | REP-23 partnership rebate | REP-23 quantity-rebate provisions |
|---|---|---|---|
| Who | Claire Newall, Nick Garrish (Charlotte copied) | Charlotte (finance only) | Charlotte (finance only) |
| What | 6% on the sales of a fixed list of 22 goalpost / branded-bay parts, any customer, 12 rolling months | One key account's agreement: banded tiers, a bonus above a baseline, referral rewards | Finance's month-end provision for **every** customer rebate scheme, to one accrual nominal |
| Basis | **Invoice lines** (TBI_TBL × COR_TBL), month = order line's **customer due date** | Net invoiced (and collected) by account, group's financial year | Net sales ledger by account and month (invoices − credit notes, ex VAT), each scheme's own year |
| Proved | **To the penny** against Claire's November report (12 Nov) | Calculator agrees with every worked example in the agreement | **115 of 137** typed monthly cells = Access to the penny; carried-forward totals exact (14 Nov) |
| Built | `sagex3/reports/rebate/` (SQL, builder, web app port 8765) | `sagex3/reports/partner_rebate/` (calculator, model builder; generic) | Read-only SQL + reconciliation (private finance folder) |
| Sent | Write-up + HTML / xlsx to Claire and Nick, **13 Nov** | Email + finance-only model to Charlotte, **13 Nov** | Check workbook + covering note to Charlotte: **ready 14 Nov** |
| Waiting on | Claire: the HHA01 due-date move, the HHA-INSTALL credit / re-invoice, flat 6% as a separate agreement, the part list (other GA variants) | Charlotte: entity scope, pass-through share, baseline source, collected vs invoiced, above top band, settlement | Charlotte: 28 cell questions, account scope, method / year / tiers per scheme, rebate credit notes, prior-year balances |

**REP-22 in detail (not finance-only; names were already in this runbook):**
- The rebate is a flat 6%, paid to the retailer. It is **not** the per-customer rebate % in Access (CU_USRNUM1 is 0 for every customer on the report).
- The run date sets the 13-month window. The month basis can be `due` (default; matches Claire), `invoice` or `order`.
- The web app keeps every run.
- The two line differences don't change the totals. Both are with Claire (email 7).
- Charlotte has been asked whether this 6% is accounted for outside the quantity-rebate workbook, because it isn't in it.
- **X3:** the same logic on X3 invoice lines, through the API app or a request. Prove it against the Access run first.

**Quantity rebates (generic: the detail is in `finance_private/REBATES_FINANCE_NOTES.md`):**
- **Eight schemes in Finance's workbook:**
  - one flat-rate scheme;
  - banded tier schemes with different scheme years;
  - one scheme that steps retrospectively at year end;
  - the partnership scheme and its referral bonus.
- The summary also carries unreleased prior-year balances.
- **Access already holds a per-customer rebate % (CU_USRNUM1).** For the flat-rate scheme it is set to that scheme's rate, and the daily invoiced-sales view nets it off. Charlotte is asked whether every flat rate should be held that way. In X3 that becomes a customer field or a price / discount structure.
- **What the reconciliation found:**
  - deliberate formula adjustments: a rebate credit note added back, "less VAT" deductions on two accounts, prior-year moves, a year-end deduction, one reversed sale;
  - slips: a typo'd account code, one month typed £26.7k high on one scheme;
  - accounts of the same customer groups missing from the sheets (one is material).
- **The covering note:** one attachment only, the check workbook. Charlotte already has her own workbook and the partnership model.
  - Five sections: adjustments, slips, account scope, rules per scheme, balances and the 6% scheme.
  - The open partnership questions from 13 Nov are repeated.
  - It asks for a 30-minute walk-through, or answers in the workbook's Answer column.

**The provision run to build (after Charlotte's answers), REP-23:**
1. **One parameter table per scheme:** account list, scheme year, method (banded or retrospective), tier table, caps, bonus or baseline, referral rules.
2. **Monthly sales from the ledger:** Access SL_TRANSACTIONS now, X3 invoices after go-live. Rebate credit notes are excluded, and adjustments are logged as rules or manual lines with a reason.
3. **Output in Finance's own layout:** a sheet per scheme and the Summary, with provision required, the monthly movement for the accrual journal, prior-year balances, and a checks tab listing unclassified items.
4. **Finance only:** private folder now. In X3, finance-only rights and an accrual account the AMs can't see, kept off the AM sales report.

**Lessons (rebates):**
- **Prove each report against the user's own figures, cell by cell, before automating.** Typed sheets hide judgement calls (credit notes added back, VAT taken off net figures, year-end deductions). Each becomes an explicit rule.
- **Rebate credit notes must not reduce the sales a rebate is calculated on.** We need an identifier for them in Access and X3.
- **Check account scope against the ledger by prefix, not just the user's list.** Missing accounts can be material.
- **Finance-only rebate data stays in the private folder**, whatever the scheme: no names or figures in git, Jira, the register or emails to anyone but Finance.
- **A covering note sends one explained file**: never the user's own workbook back, and never raw extracts.

**14 Nov, provision check (REP-23, finance only).** We recalculated each scheme's October provision three ways:
1. from Finance's own typed sales;
2. from Access on a banded basis;
3. from Access on a retrospective basis.

**Results:**
- **(1) agrees with Finance's provision to the penny for every scheme.** The workbook's arithmetic is right.
- **(2) differs only through the formula adjustments and slips already listed.** Most of the difference is one scheme's adjustments.
- **(3) shows the real exposure is the method.** One scheme was settled retrospectively last year, but it is accrued banded during the year. Two other schemes' closed-year amounts are held on a banded basis, and retrospective settlement would roughly double them.

**Changes to the covering note:**
- An "In short" block at the top, with five priority questions and a reply-by date of **Wed 25 Nov** (so November can run in parallel).
- A provision-check section.
- The check workbook gains a "Provision check" tab.
- It is still one attachment.

**Lesson:** checking the inputs isn't enough. Recalculate the outputs under each plausible rule and say plainly whether the posted figure is right, and what would change it.

### 22.17 BEFORE THE NEXT RE-EXTRACT (week of 16 Nov) – checklist, so nothing from 12–14 Nov is missed

**Read this first on the day.** Every item below changed after the Run 4 extract of 4 Nov. Rule 1 still applies: live data, extracted on the day, every file rebuilt.

**A. On SDILive, before extracting (our own `migration.` objects only, never Access's tables):**
1. **Run the 12 Nov `sql/views_v2.sql`.** This is the change that gives **BISY** its agreed document numbers (19.13, agreed with Ethan):
   - Document (B) = `PT_PRIMARY`, the Access transaction number. It's unique and contains nothing made up;
   - SourceDocument (N) = the supplier's reference `PT_HEADER_REF`, falling back to `PT_HEADER_REF2` and then `PT_PRIMARY` if that's blank;
   - Comments2 = the PO number `PT_ORDER_NUMBER`, blank if there isn't one;
   - Line = 1 on every row.

   - **It also carries the 17 Nov sign fix** (vw_BICX_V2 and vw_BISX_V2): an INV with a negative open amount loads as MCRN, a CRN with a positive one as MINV. Without it the two MAR101 credit notes (£148,751.02) load as invoices again.

   **Check first** that the live `migration.vw_BISX_V2` on the server is the repo version. On 12 Nov the server view differed from `sql/views_v2.sql`, so compare before running.
2. **After running it, check:** `SELECT TOP 5 Document, SourceDocument, Comments2 FROM migration.vw_BISX_V2`. Document must be all digits, and no Document may equal its SourceDocument.
   - **Sign check:** `SELECT COUNT(*) FROM migration.vw_BICX_V2 WHERE InvoiceType='MINV' AND <open amount> < 0` must be 0 (same for MPAY / MCRN in vw_BISX_V2). On the 4 Nov data, MAR101 refs 5019602 and 5018410 must show MCRN.
3. `sql/add_new_accounts_to_xref.sql` only if new customers or suppliers have been created since 4 Nov. Its checks show how many were added.

**B. Extract (on the day):**
4. `rebuild/sql/extract_transactions.sql`: save the **whole** output. Its CHECK "as at" line sets the accounting date.
   - **Claire runs the Access Aged Debtors and Aged Creditors (detail and summary) at the same moment** as the extract; agree the time with her (asked 17 Nov). That removes the timing differences (£859,654 on creditors at Run 4).
   - **Before extracting, find why the 5 invoices dated 27–30 Oct were not in the 4 Nov extract** (AFB01, MUN01, TDG03, BWS01, KOM01; £55,342.05). Check them in this extract's BICY rows; 3 of the 5 customers weren't in X3, so check they're in the customer file too.
5. Products, BOMs and routes are re-extracted and rebuilt by `rebuild/run.py` **first**. New parts since 4 Nov exist: the 13 Nov Live Orders run found 51 works orders with no BOM / route in the 4 Nov set.

**C. Build (19.14):**
6. `scripts/run_transactions.py` **without `SWAP_BISY`**. `SWAP_BISY=1` was only for the old 4 Nov extract.
   - The accounting date defaults to the extract's own "as at" date, so there is no 31/10 hard-coding.
   - The build **stops** if any item is dated after it (the BRW500 failure).
7. Pass the run's own inputs, never the defaults:
   - `--bins <run>/extract/bins.txt`;
   - `--bom` = this run's rebuilt BOM set;
   - `--routes` = this run's rebuilt routes.
8. **BISY checks** in `build_bicy_bisy.py`: every Document is all digits and unique, none equals N, and Line = 1. On an old extract the build stops with "a Document is not an Access transaction number", which is correct.
9. BICY is unchanged: still the order number, with suffixes. Ethan has been asked about using ST_PRIMARY instead; **not changed**.

**C2. Works orders (YA004MFG): Live Orders questions 6–9, sent to Marc and Ethan on 16 Nov (22.26). Settle these before the works orders are loaded again:**
- **Q6, operations already done.** Today WOs load at the remaining quantity with **all** operations open, so hours already worked in Access show as still to do. Options: load the completed quantity per operation, or load only the open operations.
- **Q7, WO → SO link.** Can YA004MFG carry the originating sales order and line, so the customer date shows?
- **Q8, Access WO number.** Carry it in a reference field (MFGNUM is blank, so X3 renumbers).
- **Q9, made to date.** Load the original quantity plus completed, not just the remaining quantity (EXTQTY).
- **If there's no answer by the run,** build as now and record that these four are open. Don't guess field names.

**D. Before Ethan imports:**
10. **ACCCOD** from Claire's Customer_List_master column T (ASSIGNED → ID, EURO → EU, NON-ASSIGNED → STD): 279 of 303 coded. Before loading, Claire must decide the **4 merged-account conflicts** (MAR101, BOO102, DEL101, WHI102) and the **20 unmatched** (TEC109 has a balance, EUR, probably EU) – asked 17 Nov, by Wed 18 Nov. Then put it into YA004BPC column Q and reload customers **before** BICY.
10a. **Customers must load before the open items.** Ethan was asked (17 Nov) to fix X3's country set-up for the 6 customers rejected on addresses (MAR101, TEC105, UNI103, TEC100, PER101, DRE100: XPOSCOD / XSAT) before Thursday. **Check all 6 load**; if MAR101 fails, £1.12m of debtors misses again.
10b. **Suppliers:** Claire to supply VAT / SIRET for the 11 FR / ES suppliers (and BAL500's tax rule). SOG500, ECO500, BAL500's open items only load once the suppliers do.
10c. **CAP500 £22,500 "SAVINGS" journal:** direction still open with Ethan / Jim.
11. The aged debtors / creditors sign-off is compared **as at the extract moment**, not 31/10. Use the run's control totals.
   - Ethan to produce X3's aged debtors and creditors as a **summary by account** as well as the detail (YBALAGEHIST), for the extract moment.
   - Ethan to send the **import logs** for any item that doesn't load.
   - Re-run the private reconciliation (`scratchpad/ar_ap_signoff/`: parse_access.py, parse_x3.py, recon_sl.py, recon_pl.py, build_wb.py) on the new reports and extract. **The target: Access = loaded = X3, with only explained differences.**
12. The master-data fix lists (Run 3) are still to be cleared.
13. Send Ethan **every file** (rule 1e), and say this is the run with the new BISY document numbers.

**E. Other things waiting, not part of the migration run:**
- **Charlotte's self-refreshing rebate workbook (REP-23): BUILT 14 Nov.** Attachment 2 of her email; the builder `qr_work/build_provision_wb.py` is in the private finance folder.
  - It reproduces the October provision check for every scheme, to the penny.
  - Still to come: her answers, entered as settings.
  - It needs **read-only SQL access to SDILive for Charlotte's Windows login** (IT or Acuity).
  - Design:
    - a Sales tab refreshed from the ledger;
    - a Schemes tab with the rules (accounts, year, banded / retrospective, tiers);
    - her sheets and Summary by formula;
    - a Checks tab.
  - It must reproduce October's £-for-£ provision check before she gets it.
  - Finance only: Finance folder, never in git.
- **Live Orders:** refresh `LO_PRODUCTS` / `LO_BOMS` / `LO_ROUTES` from this run's rebuilt set.

**F. Git on James's PC: never check out this branch in `C:\ClaudeVision`.**
- On 14 Nov, `git checkout claude/eloquent-babbage-o9etz3` in the working folder swapped James's estimating code for `main`'s version and estimating stopped working. Nothing was lost; going back to his own branch restores it.
- The branch only **adds** `sagex3/` (plus three `.gitignore` lines). James's folder was on another branch with its own work.
- **On James's PC, `origin` is a different remote. This branch lives on the `jbg` remote.**
- Use a separate folder:
  ```
  git worktree add C:\ClaudeVision_X3 claude/eloquent-babbage-o9etz3
  cd C:\ClaudeVision_X3
  git pull jbg claude/eloquent-babbage-o9etz3
  ```
  Or unzip the update zip into that folder.

**Lesson:** before giving any git command for James's PC, ask which branch and remote his folder uses. Default to a separate worktree, never his working folder.

**14 Nov – self-refreshing provision workbook built (REP-23, finance only, private folder).**
- **What it is:** formulas only.
  - Paste the read-only query output on the Sales tab and pick the as-at month.
  - Settings for each scheme: year start, banded or retrospective, the month the previous year was settled, the date a new scheme began. Tiers and accounts (include Y/N) are settings too. Manual adjustments must carry a reason.
  - Output: Summary (provision, movement for the accrual journal, prior-year balances, checks) and Monthly in Finance's layout.
- **Proved:**
  - Recalculated in LibreOffice: October equals the provision check's ledger-based banded figures for every scheme, to the penny.
  - A pasted header or dashed line is ignored.
  - Changing the as-at month works.
- **Sent to Charlotte** as attachment 2, with the check workbook.
- **For Charlotte to refresh it herself:** her Windows login needs read-only access to SDILive (IT / Acuity). Until then, James runs the query.
- **Lesson:** build the tool so the user's answers become settings, not formula edits. Prove it against the agreed check before it goes out.

### 22.18 Status check (15 Nov): rebates (Finance), estimating import, Live Enquiry – what's done, what's waiting, and the gap

| Workstream | Built and proved | Emails | Waiting on | What we can still do before replies |
|---|---|---|---|---|
| Finance rebates (REP-23 + quantity rebates) | Check workbook (115 / 137 cells to the penny, provision check); self-refreshing provision workbook (= check to the penny) | Charlotte: **ready, 2 attachments, not yet sent** | Charlotte's answers (5 priorities by Wed 25 Nov); read-only SDILive access for her login | Nothing: the next step is her answers |
| Rebate report (REP-22) | Report + app (to the penny) | Claire + Nick: sent 13 Nov | Claire's 4 confirmations | – |
| Estimating import (EST-10) | Converter + web page; the real estimate = the Access route / BOM | Dave + James Ryan: sent 13 Nov (14 questions + examples workbook); Acuity B: sent 13 Nov | Their replies by Fri 20 Nov; Acuity on re-import / product-site | **A TEST load of the IMPORT test part, if James has import rights in X3 TEST** |
| Live Enquiry → opportunity (OPP-00..06) | **Not built.** There's no template from Acuity yet, and we don't have the Live Enquiry workbook | Acuity D (3 questions): sent 13 Nov. **Users: none sent. That's the gap.** | Acuity (Fri 20 Nov); the users' workbook and answers | **The users' email is drafted (13 questions), waiting on James to confirm who it goes to** |

**Live Enquiry facts already in hand:**
- The list is `K:\Estimating\Completed\Manual Estimates\Live Enquiry.xls`, sheet "Live Enquiries". Its columns include Customer, Drawing No., Job Description and Enquiry Received.
- `src/live_enquiry_collector.py` already gathers each enquiry's drawings into `K:\Estimating\Completed\AI Estimating\Live Enquiry\<drawing – description>`. If X3 SaaS can't store files, that folder is the fallback link for OPP-05.

**Next:** once the workbook arrives, build stage 1 in the same way as estimating:
- read the list;
- check each customer against X3;
- write the opportunity import file with checks.

Then go to the API once Acuity has given us the template and the access.

### 22.19 Rebate rolling report (REP-22): installation lines removed (Nick Garrish, 15 Nov)

**Nick's reply to the 13 Nov email:** "the only immediate thing I can see is there are some lines that refer to install which would need removing."

- **The install lines are part code `HHA-INSTALL M&M`, the only installation code on the list.** Claire's November report shows four lines (30, −72, +72, +72). Access holds two invoice lines (30 and 72) on invoice 5019204. Both come to 102 units at £135, so **£13,770.00**.
- **Done:**
  - removed from `rebate_parts.csv` (now 21 codes) and from the part list in `rebate_rolling.sql`;
  - the report's notes say why: the rebate is on goods only;
  - the web app follows the CSV automatically.
- **Result (12 months to Nov 2026, by due date):**
  - **sales £535,441.31** (was £549,211.31, −£13,770.00);
  - **rebate £32,126.48** (was £32,952.68, −£826.20, i.e. 6% of the install value).
  - The rebuilt report is in the scratchpad `rebate/live/out/`.
- This also settles the open "HHA-INSTALL credit / re-invoice" question from the 13 Nov email, because the line is no longer on the report.
- **Still open with Claire:**
  - the HHA01 M&M due-date move (Sep → Nov);
  - the flat 6% as a separate agreement;
  - whether the part list is complete (other 10932-00-GA variants);
  - whether the 6% is accounted for outside Finance's quantity-rebate provisions (asked of Charlotte).

**Lesson:** a report recreated from a user's copy reproduces their mistakes as well as their totals. Ask the users to read the line list, not just the totals.

### 22.20 Dave's Live Orders sheet re-analysed (15 Nov) – his two "game changer" notes; "Live Enquiry" means this sheet

**Correction:** when James says "live enquiry" for Rachael and Liz, he means **Dave's Live Orders sheet** (`Live_Orders.xlsx`). The 15 Nov upload is byte-for-byte the copy we built the board from, MD5 4a2406…. The opportunity work (Live Enquiry → X3 opportunity, OPP-00..06) is a separate thing and stays with Acuity. The draft users' email in 22.18 is **withdrawn** and won't be sent.

**What Dave's sheet holds:**
- **Live Orders:** 304 rows. Due date, customer date (a broken #REF! formula), WO, SO, part, description, drawing, REV, material status (typed), qty / booked in / balance, Metal / Joinery / Acrylics, tube req, comments, prog, and 23 department hour columns. Black "weekly break lines" separate the weeks.
- **WO Suggestions:** MRP-style.
- **BOM Report:** an example exploded BOM, with level, part, description, qty used, required, in stock, on PO, **PO due date** ("new thing"), on WO, BOM, route, mat cost, **mat cost each** ("new thing"), department, procurement.

**His two notes (cell comments):**
1. **E30, part code: "Apply a link from this cell that takes the user to the BOM report (as per tab 3). This would be a game changer for a lot of people in office and on shop floor. BOM to show stock of parts / if on order / due date of order."**
   - **Done.** The web board already opened each works order's exploded BOM on click.
   - **New (15 Nov):** in the Excel version, every part code on Live Orders is now a link to that works order's line on Exploded BOMs. All 703 were checked: each lands on the right works order.
   - **New columns on Exploded BOMs, so it matches his tab 3:**
     - Has route;
     - Department (Metal / Joinery / Acrylics, from the component's route);
     - Mat cost each (X3 standard cost, YITC);
     - Mat cost (required × each), with a total on each works-order line.
   - The cost file is optional: `--costs <YITC .txt>` on the builder, or `LO_COSTS` for the web page.
   - The board's totals are unchanged: 703 WOs, 169 / 261 / 273.
2. **H13, REV: "Highlight REV cell in red if the letter / number in this cell does not match the rev indicated on the GA of the drawing located in the production folder."**
   - **Not built.** It needs the drawing files on W:\Production, which this session can't reach.
   - **Plan:** a small read-only script on James's PC.
     - It lists the GA drawings (PDF) for each board drawing number, reads the rev from the file name (or from the title block if the names don't carry it), and compares it with the works order's REV.
     - Mismatches turn the REV cell red, with a "Drawing rev" column next to it.
     - The existing `live_enquiry_collector.py` already searches `W:\Production\<customer>` by drawing number, and the rev check reuses that search.
   - **Needed from James:** a file listing to learn the naming, from
     `dir /s /b "W:\Production\*-GA*.pdf" > ga_list.txt`.

**Also on Dave's sheet and already covered:** WO Suggestions; department hours (work-centre hours and load by week); the black week break lines (the board sorts by due date; week grouping is a display choice for LO-01). Comments, Prog and Tube req stay typed by Production (LO-01).

### 22.21 RULE (James, 15 Nov): drawing sources

- **TTi (prototype work):** the **Design** and **Prototype** folders.
- **AI runner:** the **Design** folder only.
- **Never** `W:\Production`.

(The AI estimating runner lives outside this repo copy. This is only a record of the rule.)

### 22.22 Estimating import and Live Enquiry – James's direction (15 Nov)

**Estimating import.**
- **How it works today (James):** Dave copies and pastes from his estimating sheet into an **import spreadsheet with macros**, runs a few macros, and "the database is updated".
- **What we've seen:** the `IMPORT.xls` we have (10 and 13 Nov copies, MD5 02f980…) **contains no macros at all**: no VBA project. So the macro spreadsheet is a **different file**, probably an .xlsm or an add-in.
- **Questions for Dave:** which file it is, and **which database its macros write to**. Sage X3 isn't live yet, so today it's presumably Access SupplyChain or X3 TEST.
- **Target:** the same flow into X3. The estimate goes through our converter (`est_to_x3.py`, proved on a real estimate) and comes out as X3's product / BOM / route import files. Stage 2 loads them through the API.
- **Needed:** a copy of the macro workbook. With it, its macros are read and their steps reproduced, so nothing Dave's process does is missed. This was already asked in email 4 (Q2–Q3); the copy of the file is the quickest answer.

**Live Enquiry → recreated in Sage X3 (opportunities).**
- **Approach (James):** understand the data Access SupplyChain holds for enquiries, then map it onto X3.
- **Step 1, done:** `sagex3/live_enquiry/live_enquiry_discovery.sql` is read-only (SELECTs only). It returns:
  - tables and views whose names point to enquiries, quotes, estimates, prospects, opportunities, projects or CRM, with row counts;
  - every column with such a name on any table;
  - 5 sample rows from the 15 largest candidates.
- **James to run it** (Results to Text, tab-delimited) and upload the .rpt.
- **Step 2:** map the fields found against X3's opportunity (customer / prospect, description, value, dates, probability, stage "Identified" → "Won or lost", project on a win). The X3 field names must come from Acuity's opportunity template (OPP-01, asked 13 Nov).
- **Step 3:** build the stage-1 converter, the same pattern as estimating: Access enquiries → X3 opportunity import file with checks. Then go to the API.

**15 Nov – first discovery result (`live_enquiry_discovery.sql`, 177 objects, 480 columns, 39 sample rows):**
- **Access SupplyChain has a CRM module:** views for sales opportunities, pipeline, outstanding estimates, prospects, contacts, campaigns, tasks and leads.
  - The opportunity view carries an estimate number, estimate value, probability, and prospect fields (character, date and number).
  - **But** the only CRM table by name is `CRM_LOOKUPS`, with 15 rows from 2014, and the MetaData.Enquiry* and Workspace.Quote* tables are empty. So the CRM may never have been used.
- **`ORD_HEADER`** (the order header) has `OH_PROBABILITY`, `OH_QUOTE_DATE` and `OH_ESTIMATE_DROP_DATE`. Quotes and estimates may sit on order headers.
- **Projects exist:** the `CST_PROJECT` views (estimated sales and costs, an "IsProspect" flag), `ASC_ORC_PROJECTS`, `UDEF_SALES_ORDER_PROJECT_NUMBER` and `UDEF_WOR_PROJECT`. These are relevant to won → project (OPP-04).
- **Leads:** `DLR_LEADUPDATE` (lead id, status, lost status).
- **`historical_quote_*`** (1,982 estimates; materials, operations, labour; built May–June 2026) are **our own AI-estimating history tables** (paths `C:\ClaudeVision\src\output…`). They come from the manual estimate files. They're not Access's enquiry data, but they're useful for estimate values.
- **Next:** `live_enquiry_discovery_2.sql` (read-only). For those objects it gives:
  - real row counts;
  - full columns;
  - view definitions;
  - quote counts on ORD_HEADER by year;
  - recent rows.

  That shows whether the CRM / quotes are actually used, or whether the live enquiry process lives only in the K: workbook.

**15 Nov – follow-up result (`live_enquiry_discovery_2.sql`): enquiries are NOT held in Access.**
- **0 rows:**
  - sales opportunities (header / detail);
  - pipeline (current, analysis);
  - outstanding estimates (header / detail);
  - the CRM estimate report;
  - contact history;
  - leads (`DLR_LEADUPDATE`);
  - `ORD_HEADER`, so there are no quotes on order headers.
- **So the Live Enquiry pipeline exists only in the `K:\Estimating\Completed\Manual Estimates\Live Enquiry.xls` workbook. That workbook is the source to map onto X3 opportunities.**
- **What Access does hold around it (the master data the opportunity needs):**
  - **Accounts:** `AA_CRM_ACCOUNT_VIEW` has 1,034 rows: code, name, account manager / analysis (e.g. "Other – N. Garrish"), status, address, phone, email, credit limit. `AA_REP_CRM_PROSPECT_LIST_VIEW` has 517. These map to X3 customers (migrated) and **prospects** (for enquiries from non-customers).
  - **Contacts:** `AA_CRM_CONTACTS_SIMPLE_VIEW` has 14,419.
  - **Projects (Sage costing, `CH_*`):** 2,627 projects, codes **400000+** (e.g. 400000, 402591). Each has a name, customer (`CH_ACCOUNT`), status, type (e.g. PROTO), start / deadline / completed dates, estimated and actual sales and costs, and an IsProspect flag.
    - Sales-order lines carry the project (`COR_PROJECT`; `UDEF_SALES_ORDER_PROJECT_NUMBER`, 17,286 order / project pairs).
    - `UDEF_PROJECT_DETAIL` (13,611) links project → sales order → part / drawing.
    - `UDEF_WOR_PROJECT` (2,627) links project → GA drawing → value.
    - `ASC_ORC_PROJECTS` holds 11 distinct project codes on works orders.
  - **This is today's "won → project number".** In X3 it becomes the project / financial dimension created on a win (OPP-04). Its numbering (400000+) and fields are what Acuity's design has to carry.
- **Needed:**
  1. a copy of `Live Enquiry.xls`;
  2. who creates the project number in Access today, and at what point (on a win, or at enquiry?).

**15 Nov – CORRECTION (James): "Live Enquiry" IS the Live Orders sheet.** There is **no** `K:\Estimating\Completed\Manual Estimates\Live Enquiry.xls`. That path came from the July collector's example config and was wrongly treated as a real file. **Stop asking for it.**
- The task is to recreate **Dave's Live Orders sheet** in X3, mapped from the Access SupplyChain data. That's the work in 22.6 / 22.11 / 22.13 / 22.20.
- The two `live_enquiry_discovery` queries were a detour. They aren't needed for Live Orders, but their facts stand: no CRM / opportunity data in Access, and 2,627 Access projects.
- **Lesson:** use James's names for things. When a name is ambiguous, check the conversation before trusting old config files.

**Live Orders: Access source → X3 (the map for Acuity; X3 table names to be confirmed in their reply to C15):**

| Dave's column | Access SupplyChain today | X3 |
|---|---|---|
| Due date | `ASC_WOR_TBL.WOR_DATE_SCHED` (works-order scheduled date) | Works-order end date (MFGHEAD / MFGITM) |
| Customer date | `WOR_SALORD` → sales-order line due date (`vw_SOH_V2`); Dave's own formula is `#REF!` | Originating sales-order line (SORDERQ) requested / ship date |
| WO Num / SO Num | `WOR_ORDER`, `WOR_PARENT_ORDER`, `WOR_SALORD` | WO number; originating SO and line |
| Part code, Description | `WOR_ITEM_ONLY` → product master | ITMMASTER (code, description 1) |
| Drawing, REV | Part code; `WOR_ITEM_REV` | Product code / description 2 (rev, as migrated) |
| MATERIAL STATUS | Worked out: BOM × balance against stock (`vw_SMR_V2`), open POs (`vw_POH_V2`) and works orders. Today it's typed free text | WO material lines (MFGMAT): allocated / short, PO lines (PORDERQ) with due dates → RAG |
| QTY / Booked in / Balance | `WOR_ORIG_QTY` / `WOR_AMD_QTY`, `WOR_GOOD_QTY`; balance = qty − good | WO planned / completed / remaining (MFGITM) |
| Metal / Joinery / Acrylics | Route work centres (mapped LASM→MMAC002 etc.) | Work centres on the WO operations (MFGOPE) |
| LASM … PACP (23 hour columns) | Route run time × balance (+ set-up) per work centre | Remaining operation time per work centre (MFGOPE) |
| WO Suggestions | Uncovered sales-order lines for made parts | MRP suggestions (X3 MRP) |
| BOM Report (stock / on PO / PO due / on WO / cost) | Exploded BOM against stock, PO and WO; cost from YITC | BOM (BOMD) explosion with stock (STOCK), PO lines, WOs; standard cost |
| Tube req, Comments, Prog | Typed by Production (not in Access) | X3 user fields on the WO, or kept on the board side (LO-01) |

**15 Nov – "Live_Orders.shopfloor.xlsx".** This is byte-for-byte the same file as Dave's `Live_Orders.xlsx` (MD5 4a2406…), the fourth copy received.
- **New fact from its properties:** created by **"Crystal Decisions"** and last saved by David Wright on 26 Oct 2026, 09:16. So today's sheet is a **Crystal Reports export from Access**, which Production then edits by hand: material status, comments, Prog, tube req, the colours and the week break lines.
  - The Crystal report file (.rpt) behind it holds the exact Access tables and formulas. If it can be found on the network, it confirms the source of every column.
- **The 13 Nov Live Orders email went to Rachael and Liz** ("Hi Rachael, Liz"), not Dave and Rachael as earlier entries say. It was the 4 Nov board with 12 questions, replies due Fri 20 Nov.

### 22.23 Dave's original request (26 Oct, to James, cc Rachael) – and the Monday copy-over

> "This is probably the most important report we will need from SAGE, which will produce the Live Orders (Production Plan). I have attached a copy of the current one we use which **Rachael has to manually copy over every Monday into a new Live Orders for the week**. Can we link this to SAGE as a **live document, so all the manual work is taken away**. Live Orders (tab 1), WO Suggestions (tab 2), BOM Report (tab 3). This email is only my initial thoughts… will need a few meetings to figure out the details." – David Wright, Head of Estimating & Purchasing

**The requirement in his words:**
1. A live document from Sage, not a weekly copy.
2. No manual work.
3. The three tabs.
4. Meetings to settle the details (LO-01).

**Built 15 Nov: the Monday copy-over is gone.** `build_live_orders.py --carry <last week's sheet>` (or `LO_CARRY` for the web page) reads Production's typed columns and puts them on the new board against the same works order:
- Comments, Prog and Tube req;
- Production's typed material note.

It reads either Dave's own sheet or a board that Production has edited and saved.

- **Tested:**
  - from Dave's sheet, **45 works orders** got their notes on the 13 Nov board (of the 49 still open);
  - from that board saved again, the same 45 came through, so the round trip loses nothing;
  - the part-code → BOM links (703) are unchanged.
- **So the weekly cycle becomes:** refresh the board (or run the query), and last week's notes come across by themselves.
- **In X3:** the same notes become user fields on the works order (question 7 to Rachael and Liz), so they stay with the order.

### 22.24 Emails ready for Monday 16 Nov: Ethan + Dave (estimating TEST load) and Ethan (Live Orders on X3 data)

These are saved in the scratchpad `outbox_16Nov/` (not git).

**A. Estimating (to Ethan and Dave, cc James Ryan and Neil). Decision (James, 15 Nov): don't wait for Dave's macro sheet.**
- The converter's files use the migration's own templates and match Access on a real estimate. The macro sheet is now only a cross-check.
- **Ethan loads two real estimates into TEST:**
  - Dave's IMPORT part: product, 14 BOM lines, 30 operations. The parent IMPORT already exists, with a manual routing.
  - The Gift Card Header: 8 BOM lines and 9 operations, identical to the migrated ones.
- **The load answers Acuity Q6 and Q7 directly:** what re-importing an existing product, BOM or route does, and whether a works order can be raised for IMPORT straight away (product-site).
- **Dave:** the macro workbook as a cross-check, and 30 minutes on screen with the TEST load. Questions 10–13 still stand.
- **Attachments:**
  - `Estimating_X3_TEST_load_files.zip`: 5 load files (CRLF) plus a read-me, for Ethan;
  - `Estimating_to_X3_examples.xlsx`, for Dave.

**B. Live Orders (to Ethan, cc Neil and Dave).** An export from TEST so the board runs on X3 data. Section C of email 6 in practice. It asks for:
1. open WOs with the originating SO / line;
2. WO operations;
3. WO materials (required, allocated, short);
4. open SO lines;
5. open PO lines with expected dates;
6. stock.

**Questions in it:** do the Run 4 works orders (721) and the WO → SO link exist in TEST; three WO user fields (Comments, Prog, Tube req); has MRP run.
**Attachment:** the 13 Nov board.

**Live Orders: what's understood and what isn't.**
- **Understood and proved:** every column's source and logic, against Dave's sheet.
- **Still open:**
  - Production's rules: the 12 questions to Rachael and Liz, due Fri 20 Nov;
  - the REV drawing folder (Dave says production folder; to confirm with James);
  - the Crystal report behind the sheet;
  - work-centre capacities;
  - the X3 side, which Ethan's export answers.

**16 Nov – Finance's cell notes read; the email and attachments are rebuilt (REP-23, finance only, no figures here).**
- Finance's workbook carries **cell comments** that explain most of the differences:
  - deferred sales moved to the right month;
  - VAT on one country's invoices taken off;
  - rebate credit notes (a conference credit, and a credit that released prior-year balances);
  - one sale left out because it wasn't paid;
  - one scheme's year-end retrospective correction.
- **The 14 Nov check had read the values and formulas but not the comments.** That raised questions the notes already answered.
- **Now:**
  - 15 of the questions are marked answered, each with Finance's own note;
  - the provision workbook carries those adjustments, each with its reason;
  - the gap left is small and itemised;
  - one final email replaces the 14 Nov draft.
- **Lesson:** when checking a user's workbook, **read the cell comments first**. They're the user's own explanations. Never ask a question their workbook already answers.

**16 Nov – SENT to Charlotte (finance only):** the quantity-rebate email with two attachments (the check workbook with 33 questions, 15 answered by her own notes; the provision workbook). Reply due Wed 25 Nov. Next: a full November run on 1 Dec and a side-by-side with her November.

### 22.25 Estimating converter – how it runs, and embedding it in the estimating portal (16 Nov)

**Full technical write-up:** `sagex3/estimating/README.md`. It's the reference for James's estimating-portal build.

- **Restart (16 Nov):** estimating is now worked from **Tim's original estimate only** (12539-04-GA (0359869) Gift Card Header rev B, 1 Sep 2026, quantity 40). The file is identical to the 13 Nov upload.
  - **Fresh run:** `MS-0359869 (existing): BOM 8 lines, route 9 ops, 0 stop, 0 warn`.
  - The BOM and route `.txt` are byte-identical to the 13 Nov run.
  - **No ZSDIITM:** the part already exists in X3. A product file is only written for a new part, as with Dave's IMPORT test part before.
- **The email to Dave, Tim, James Ryan, Ethan and Marc (16 Nov, James's wording) has three attachments:**
  1. Tim's original `.xls`;
  2. `Tim_GiftCard_estimate_to_SageX3.xlsx`: Read me, Estimate → X3 line by line, BOM file, Route file, Checks;
  3. `Tim_GiftCard_SageX3_import_files.zip`: BOM and route `.txt` plus a read-me.
- **It asks for:**
  - **Tim:** check the conversion; is CR4 right?
  - **Dave:** check the conversion; send the import macros (Alt + F11 shows which file holds them).
  - **Acuity:** load in TEST, BOM then route; what does re-import do to an existing BOM / route (replace, add or reject); send logs and screenshots.
  - A 30-minute TEST walk-through with everyone; done by Fri 20 Nov.
- **How it runs:**
  - `est_to_x3.build(est_path, out_dir, products_path, parent, category, rev_in_code, sheet_material)` returns `{code, new, bom, ops, stop, warn, files, checks}`;
  - the same call from the command line;
  - or the `est_app.py` web page (port 8766: `POST /run`, `GET /run/<id>`, `/zip`).
- **Needs:**
  - Python 3.10+ with openpyxl;
  - LibreOffice for `.xls` estimates only;
  - the current X3 product list (ZSDIITM file or an X3 product export);
  - `migration/rebuild/common.py` and `work_centres.csv`, kept in the same layout.
- **Portal embedding:**
  - call `build()` from a background task;
  - show READY / NOT READY and the checks;
  - offer the `.txt` files only when `stop == 0`;
  - warn when the part already exists (Acuity B6);
  - keep every run;
  - stage 2 = the X3 API.
- **Correction:** with STOP checks, the load files **are still written** (so the user can see what was read). The result is NOT READY and the files must not be loaded. The 16 Nov README.txt in the converter zip said STOP prevents writing; that was wrong, and README.md replaces it.

**16 Nov – estimating emails (James to send):**
1. **To Dave, James Ryan, Tim, Ethan and Marc:** Tim's Gift Card Header converted. It asks for:
   - a check of the conversion (Tim, Dave);
   - CR4 for sheet steel (Tim);
   - Dave's import macros (Alt + F11);
   - the TEST load and re-import behaviour (Acuity);
   - a walk-through by Fri 20 Nov.
2. **To Dave (cc James Ryan): where "Send to Sage X3" will live.**
   - **Option 1, recommended:** the estimating portal runs the converter. It shows READY / NOT READY with checks by cell and keeps every run. It sends straight to X3 once the API is available.
   - **Option 2:** a "Send to Sage X3" button in the estimate template. The recommended form is a short macro that sends the estimate to the portal, so the rules stay in one place. Python on every PC, or rewriting the rules as macros, are not recommended.
   - **Asks:**
     - the trigger (quoted, won or ordered) and who presses the button;
     - Excel, the portal, or both;
     - the macros;
     - template changes (a Material column on sheet steel, a code column on other sheet).

### 22.26 Live Orders – focus on the Sage X3 piece (James, 16 Nov)

**Decision:** we are **not** replacing Rachael and Liz's sheet now. The follow-up email to them is dropped. The focus is **how Sage X3 delivers Live Orders**.

**Approach:** standard X3 first, then fill the gaps. Acuity confirm, for each of Dave's columns, which standard X3 screen or report covers it. They demo those screens, and propose how to deliver anything X3 doesn't cover (inquiry, report, WO user fields, or an export).

**For Acuity (Ethan, Neil, Marc; cc Dave):**
- `LiveOrders_requirement_to_SageX3.xlsx` takes every column of Dave's three tabs (Live Orders, WO Suggestions, BOM Report). For each it gives: what the column means; the Access source today; the X3 data; a possible standard X3 screen (ours, to confirm); and two answer columns for Acuity.
- Dave's current sheet goes with it.

**The SDI-built board (live_orders_app) stays as:**
- the reference for what each column means;
- the fallback for any gap X3 can't cover.

It isn't a replacement for Production's sheet now.

**16 Nov – Live Orders: Production's sheet reconciled automatically and mapped onto the X3 templates (James's direction: keep the work, make it useful to Acuity).**
- **`sagex3/production/live_orders/reconcile_dave.py`** is read-only. It compares Production's sheet (Dave's Crystal export of 26 Oct) with the Access extract nearest that date (4 Nov), works order by works order and column by column. It then traces every column to its Access source and to the X3 import template it was loaded with (YA004MFG, YA004SOHPJ, YA004POH, YA004SMR, ZSDIITM, ZSDIROU2, YA00408BOM).
- **Output: `LiveOrders_reconciliation_and_SageX3_mapping.xlsx`.** Tabs: Read me, Findings, Column map, By works order, Dept hours, Not open.
- **Results (102 of 220 works orders still open in both):**
  - part 102 / 102;
  - quantity 102 / 102;
  - balance 98 / 102 and booked-in 98 / 102 (made since);
  - sales order 98 / 102 ("Stock" = none);
  - due date 76 / 102 (25 of the 26 rescheduled later);
  - Metal / Joinery / Acrylics 63 / 102 (definition);
  - department hours: 297 of 334 work-centre lines agree where both have hours.
- **Gaps found between Production's sheet and X3 as loaded:**
  1. **Department hours:** the sheet uses each WO's own open operations. YA004MFG loads WOs at the remaining quantity with **all** operations open, so hours already done would show as still to do.
  2. **WO → SO link not loaded**, so there's no customer date.
  3. **Access WO number not carried** (MFGNUM blank; X3 renumbers).
  4. **Made-to-date not carried** (EXTQTY = remaining).
  5. **REV:** blank on 757 of 769 Access WOs; typed by Production. In X3 it's on the product only.
  6. **Notes and material status are typed:** they need WO user fields, or a calculation from WO materials.
- **Email to Marc and Ethan (cc Neil, Dave):** is there a process in Sage X3 today to provide this report, with the full explanation and the two attachments? It replaces the 22.26 requirement-only workbook.

**16 Nov – Live Orders process written up so both workbooks can be re-created (`sagex3/production/live_orders/README.md`).**
- **The board** (`SDI_Live_Orders_<date>.xlsx`, the "example of the target") comes from `build_live_orders.py`: extract + products + BOMs + routes (+ `--costs`, `--dave`, `--carry`).
- **The reconciliation** (`LiveOrders_reconciliation_and_SageX3_mapping.xlsx`) comes from `reconcile_dave.py`: Production's sheet + the extract nearest its date + the same master files.
- **Inputs used on 16 Nov:**
  - extracts: 4 Nov pm (`extract_transactions.txt`) for the reconciliation, and 13 Nov (`live_orders.sql` .rpt) for the board;
  - master files: the 4 Nov pm mapped set (BOMs, costs), with Ethan's 5 Nov fixes for products and routes.
- **Fixed:** the Findings tab had been added to the sent workbook by a one-off script, so a re-run would have left it out. It's now generated inside `reconcile_dave.py`, from the comparison itself, including the REV count over all 769 open works orders.
- **Proof:** re-running both commands on the original inputs reproduces every tab and row of the two workbooks as sent. The only difference is that the Findings text is now generated, with no fixed dates.
- **Lesson:** every tab of a deliverable must come from committed code, never from a one-off edit, so it can be re-run.

**16 Nov – Live Orders email SENT to Marc and Ethan (cc Neil Morphew, Dave Wright).**
- **Subject:** "Live Orders – how Production's report works today, reconciled to Access, mapped to Sage X3, and what we need from you".
- **Content:** how it works today; the three parts; the reconciliation; the mapping to X3; the example of the target; the six gaps; 12 questions (report 1–5, migration load 6–9, set-up / demo 10–12).
- **Attachments (3):** LiveOrders_reconciliation_and_SageX3_mapping.xlsx; Live_Orders (Dave, current sheet).xlsx; SDI_Live_Orders_2026-11-13.xlsx.
- **Correction (checked against the email as sent):** the sent version has **no reply-by date**, and nothing asks for Q6–9 sooner. It also doesn't say that no import is needed, that the after-go-live data comes from X3 itself, or that gaps 1–4 only affect the works orders migrated as open. A short follow-up was drafted to cover these, with a reply by Fri 27 Nov and Q6–9 before the migration run. Q6–9 are on the 22.17 re-extract checklist (C2).
- **Still open on our side:**
  - Dave: which drawing folder to use for the REV check;
  - Production's own rules: call-off list, sub-assembly rows, old overdue orders, capacities;
  - how "live" the report must be, and printing.

**16 Nov – Live Orders follow-up SENT to Marc and Ethan (cc Neil, Dave), as a reply on the same thread.**
- **Says:** Live Orders is a **view**, not a new import. Every figure comes from data X3 will hold:
  - at go-live, from the migration files (YA004MFG, YA004SOHPJ, YA00408BOM, ZSDIROU2, YA004SMR, YA004POH, ZSDIITM, YITC);
  - after go-live, from X3's own transactions, with the **estimating import** supplying BOMs and routes for new parts.
- **Gaps 1–4** (hours, customer date, WO number, made-to-date) affect **only the works orders migrated as open at go-live**. They are fixes to YA004MFG, not a new import, but they matter on day one.
- **Gaps 5–6** (revision per WO, Production's notes) are ongoing and need user fields on the works order.
- **What we need:** the YA004MFG fixes (questions 6–9), user fields, the standard view (or a proposal), capacities / MRP in TEST, and a demo with Dave.
- **Reply by:** questions 6–9 by **Wed 18 Nov** if possible (re-extract this week); everything else by **Fri 27 Nov**.
- **Lesson:** questions pasted from an email can lose their numbering. Refer to a question by its number **and** its heading or wording.

**16 Nov – estimating emails SENT (James confirmed):**
1. To Dave Wright, James Ryan, Tim, Ethan and Marc: Tim's estimate converted into the Sage X3 BOM and route load files.
2. To Dave: building the converter into the estimating portal and/or a spreadsheet (22.25).
- **Still to send:** the rebate reply to Nick (cc Claire, Charlotte): install line removed, now £535,441.31 sales and £32,126.48 rebate (22.19).
- **Still to do, in order:** Simon's email, then Claire's and Debbie's messages.

**16 Nov – rebate reply SENT to Nick Garrish (cc Claire Newall, Charlotte Blackwell).**
- **Says:** the install line (HHA-INSTALL M&M, £13,770.00) is removed from the part list, so the rebate is on goods only.
- **New figures, Dec 2025 – Nov 2026:** £535,441.31 sales and £32,126.48 rebate at 6% (was £549,211.31 and £32,952.68).
- **Attachments:** SDI_Rebate_Rolling_2026-11.xlsx and .html, each explained in the email.
- **Three questions to Claire, reply by Fri 20 Nov:**
  - the HHA01 72-unit order re-dated to 9 Nov;
  - whether 6% is paid to Morrisons under a separate agreement;
  - whether the 21 codes are complete (other 10932-00-GA variants).

**16 Nov – Simon's email SENT (to Simon Foister, cc Ewa).**
- **What it is:** a reply to his 13 Oct list. All 17 reports are on the register as REP-01 to REP-17, each with its Jira ticket.
- **Attachment:** Simon_Foister_reports_for_Sage_X3.xlsx. It has a Read me tab and a "Your 17 reports" tab with a "Your answer" column.
- **Reports:**
  - 10 look standard (REP-01–04, 06–10, 13): Acuity confirming, then we test with Simon;
  - 6 need his definition (REP-11, 12, 14–17). REP-14 (Production vs Proto Live) is the most important, because Live Orders needs the same split;
  - REP-05: export invoice samples from Ewa.
- **Reply by Fri 27 Nov** (moved from 20 Nov in the attachment).
- **Next:** Claire's and Debbie's messages from last week.

**16 Nov – Claire's year-end email (11 Nov, to all staff) and Debbie's reply (13 Nov).**
- **Claire's dates and rules:**
  - Access SupplyChain has a hard cut-off on **21 March 2027**, and the audit must finish before then;
  - hard customer-invoicing cut-off at the end of December: everything delivered is invoiced in Access;
  - Finance work through the holidays. Anything not processed in Access before the final extract is processed twice (Access for the year-end audit, then X3).
- **What this means for the go-live run:** the final extract (31 Dec) loads whatever is open in Access. **1,557 open SO lines are due more than 60 days ago** (13 Nov run); they need invoicing or closing, or they migrate as open orders.
- **Reply to Claire SENT (cc Charlotte, not reply-all; James confirmed 18 Nov).** It offers weekly read-only Access lists (old open SO lines, delivered not invoiced, receipts with no PO / open POs, subcon not booked in) and asks for the last invoicing time on 31 Dec. Only the old-SO-lines list exists today.
- **Debbie** gave the three Access menu paths and offered a call. Reply drafted: a 20-minute call Tue 17 / Wed 18 Nov, with screenshots taken on the call.

**16 Nov – Sage X3 standard screens for these reports (Sage online help, v11 / v12):**
- **Delivered not invoiced (REP-19):** Sales > Inquiries > Deliveries > Delivery list (CONSCSD) / Delivery lines (CONSCSF), "Not invoiced" filter; Deliveries by period; Invoices to be issued (FUNAUTFAE) for the month-end accrual.
- **Outstanding SOs (REP-07):** Order lines inquiry (CONSCSP); Sales order status report SLSSTAT.
- **Received not invoiced:** List of receipts (CONSCPR) with the "Not invoiced" tick box; Receipt lines (CONSCPS); FUNPTH accrual. Part-received lines are a known weak spot.
- **Subcontract not booked in:** Manufacturing > Inquiries > Subcontract (CONSSST); Purchasing > Subcontract lines (CONSSSC).
- **SDI MRP by operator (REP-18):** only partly standard. There's a shortage inquiry and MRP results, but **no standard filter by the user who entered the order**, so it's likely a custom inquiry. Ask Acuity.
- **James has admin access to the training site (sdi-displays-trn)** and checks each screen there (the menu search box takes the function names).
- **Lesson:** check function codes against the help URL before quoting them. The first list gave two wrong codes (CONSSCD / CONSSCF for CONSCSD / CONSCSF).

**16 Nov – Sage X3 screens guide for Debbie started (`sagex3/user_guides/x3_screens/`).**
- **What it is:** James captures each screen on the training site (sdi-displays-trn, X3ERPV12 / SDIMIG, Super administrator), **five at a time**. `screens.json` tracks all 13 screens and their status. `build_guide.py` builds the Word guide: per report, the Access path today, the X3 path and code, numbered steps, screenshots, and a "What to check" table.
- **Batch 1 (16 Nov):**
  - Delivery line list (CONSCSF), Shipments by period (FUNGRHSDH1) and Order lines (CONSCSP): selection screens captured;
  - the Sales invoice entry screen (GESSIH) was sent as "Invoices to be issued", but **it's the invoice entry screen**. Invoices to be issued is FUNAUTFAE, a Finance closing process, and still to find.
- **Seen on the screens:**
  - Start and End dates are mandatory (default about 3 months);
  - every enquiry has an Excel / CSV export;
  - Shipments by period has Memo / Recall, a saved selection;
  - Sales > Enquiries > Orders also holds List of orders (CONSCSO) and Orders per period.
- **Still to capture:** a results screen for each; Sales order status; Delivery list; Invoices to be issued; List of receipts; Receipt lines; Subcontract; Shortage; MRP results; Requester.
- **Then:** Marc validates (email drafted), then the guide goes to Debbie.
- **Open:** does Debbie have a login to the training site?

**16 Nov – the Sage X3 user guides redesigned (James: "an impressive document").**
- **`annotate.py`** crops each screenshot to the Sage X3 frame (no browser bars) and draws numbered red callouts on the boxes to set.
- **`build_guide.py debbie|claire`** builds a designed Word guide:
  - a cover page, then "At a glance" (Access report → X3 screen → ready / being confirmed) and "Before you start";
  - one chapter per report: a Today-in-Access / In-Sage-X3 panel, steps numbered to match the callouts, the marked screenshot, a tip, and a "What to check" table.
- **Debbie (7 pages):** Delivered not Invoiced; Outstanding Orders; SDI MRP (being confirmed).
- **Claire (8 pages):** Delivered not invoiced; Received not invoiced; Invoices to be issued (being confirmed); Subcontract (being confirmed).
- **Screenshots sent while Claude is working are not saved as files.** Send them after a reply has finished, or as one zip file. Never ask James to re-send what has already been read.

**16 Nov – rebate rolling report (REP-22): answers from Claire and Debbie.**
- **Correction:** the 16 Nov reply (and the 12 Nov sample email) went to **Nick Hedge**, not Nick Garrish. Claire forwarded it to Nick Garrish at 12:06. The rebate contact is **Nick Garrish**; check the recipient's surname before sending.
- **Q1 (HHA01 M&M, 72 units, £19,080, order 10016441):** Debbie says the due date should be **September**; the 9 November date is wrong, and **she will change it back in Access**. The next run puts it in September. The 12-month total doesn't change (£535,441.31 sales, £32,126.48 rebate): both months are in the window, and 6% of £19,080 is exactly £1,144.80, so per-month rounding is unaffected.
- **Q2 (rate):** Claire confirmed that **Morrisons invoice SDI for the 6% rebate separately once agreed**. So it's a flat 6%, a separate agreement from the customer-account rebate % in Access. The assumption stands.
- **Q3 (part list complete? other 10932-00-GA variants such as PEP, DOV, CCE, REG):** Debbie isn't sure; **Nick Garrish to discuss later this week**. Still open.
- **Next:** re-run after Debbie's date change; settle Q3 with Nick; then switch the report to live Access data and build it in X3.
- **No reply sent (James, 16 Nov):** Debbie and Claire answered, and Q3 is with Nick Garrish and Debbie. Wait for Nick.
- **To correct in the next rebate email:** the 12 Nov email said "months are taken from the invoice date". **It's the order line's due date** (the code default `--basis due`, as the Access report does; the 16 Nov email had it right).

**16 Nov – Sage X3 report guides SENT to Debbie Freeth and Simon Foister (cc Selina, Sam, Ewa).**
- **Attachments:** Sage_X3_guide_Debbie_Customer_Services (9 pp) and Sage_X3_guide_Simon_Sam_Ewa_reports (25 pp), each as PDF and Word (Word to fill in).
- **Ready to try:**
  - Debbie: Delivered not Invoiced; Outstanding Orders.
  - Simon: POs (REP-01/04), receipts (REP-02), sales orders (REP-07), debtors (REP-06), exploded BOMs (REP-03), stock usage and movements (REP-10/13).
- **Being confirmed:** SDI MRP by user (REP-18), MRP all-products list (REP-08), month-end stock value (REP-09), printouts.
- **Asked of them, reply by Fri 27 Nov:**
  - Debbie: a call Tue 17 / Wed 18 Nov; her MRP filters.
  - Simon: definitions for REP-11, 12, 14 (most important), 15, 16, 17; MRP and month-end needs; what he prints.
  - Sam: BOM call-off cartons.
  - Ewa: export-invoice samples (REP-05).
  - Selina: her 19 Oct list; a TTI schedule session.
- **Promised:** training-site logins, once Acuity confirm the environment.
- **Next:** Claire's guide and covering email; Marc's validation email (user filter, 200-result limit, load dates on migrated orders, environment, MRP list, stock valuation, BOM / subcontract).

**16 Nov – call with Acuity at 14:15 (Marc, Jim, Sergio).**
- **Brief:** the 10 Nov integrations email, item by item; the register as at 16 Nov, Acuity copy (`deliver/SDI_SageX3_Programme_Register_for_Acuity.*`, without the REP-22 / REP-23 rebate rows and figures).
- **The 13 Nov connection-details email** (to Neil, Marc, Jim, Sergio and Roberto; questions A1–A5 connections, B6–B14 estimating, C15–C21 Live Orders, D22–D24 opportunity, E outstanding) has **no reply yet**. James has sent the connection details to Sergio.
- **On the call:** chase an owner and date for each section of the 13 Nov email.
- **Rule:** the register shared with Acuity never carries the rebate rows or figures. Build the Acuity copy from a filtered `register_data.py`.

**17 Nov – DECISION: SDI builds Live Orders in-house on X3 data. Acuity are asked for access, not development. Jira SCRUM-329 (In Progress; under SCRUM-241).**
- **Why:**
  - 13 Nov: questions to Acuity, 24 of them.
  - 13 Nov: Marc's reply put the functional questions on his project review issues list and gave connectivity to Neil only. No answers or dates.
  - 16 Nov call: Acuity intend to do the development themselves, with no SDI access.
- **Email to Acuity drafted** (Marc, Sergio, Roberto, Jim, Ethan; cc Neil, Charlotte, Dave). It puts the full business and technical requirement on record and lists 10 access items (TEST first):
  - connection details, a connected app, an integration user;
  - read access (works orders with operations / materials / allocations, sales-order lines, stock / allocations, PO lines, products / BOMs / routes, work centres / capacities, MRP);
  - export templates; API documentation; IP / rate / licence;
  - three works-order user fields; webhooks; Safe X3 in TEST.
  - Dates asked: owner by Fri 20 Nov, TEST access by Fri 27 Nov; migration-load questions 6–9 by Wed 18 Nov.
- **Email to Charlotte drafted:** who holds the Sage subscription; the contract position; a written position from Neil by Wed 18 Nov; a three-way call; escalation if dates are missed; the fallback (hand-loaded imports, scheduled exports, board on Access until cut-over).
- **Neither email confirmed as sent yet.** Update SCRUM-329 when they are.
- **17 Nov – BOTH emails SENT (James confirmed):**
  1. **To Acuity** (Marc, Sergio, Roberto, Jim, Ethan; cc Neil, Charlotte, Dave): the Live Orders full requirement, the in-house build, and the 10-item access request. Attachments: LiveOrders_reconciliation_and_SageX3_mapping.xlsx; Live_Orders (Dave, current sheet).xlsx; SDI_Live_Orders_2026-11-13.xlsx.
  2. **To Charlotte:** the escalation (subscription holder, contract position, Neil's written position by Wed 18 Nov, a three-way call, escalation if dates are missed, the fallback).
- **Watch:**
  - Wed 18 Nov: Neil's written position, and the migration-load questions 6–9.
  - Fri 20 Nov: owner and date at Acuity for the access.
  - Fri 27 Nov: TEST access.

**17 Nov – production server facts, and the Remote Desktop problem.**
- **ACCESS-DB01** (`ACCESS-DB01.sdi.local`) is the production ERP database and app server: a Windows Server 2019 VMware VM, 32 GB RAM.
  - SQL Server (MSSQLSERVER), 19 databases: SDILive, SDIFinance, SDI_ACBL, ASC722, ADM, ADS, AA_*, TCDatabase.
  - Access SupplyChain Server 7.2.2 and Access NFP Server.
  - **All our SQL against it is read-only** (production rule); administrator rights don't change that.
- **The reverse DNS for its IP still says `server2k8`:** a stale record, reported to IT. Use `ACCESS-DB01` by name.
- **17 Nov afternoon:** Remote Desktop timed out at "Securing remote connection" (it worked that morning). Ping and port 3389 were fine. Likely cause: server load or memory (SQL Server default max memory starving Windows) or a stuck session. Passed to IT to check from the vSphere console.
  - **Never restart the server or SQL Server ourselves:** it cuts off every Access user.
  - **Work-around for the extracts:** run them from SSMS on James's PC, connecting straight to ACCESS-DB01 (port 1433), not by Remote Desktop.
- **The shared account `sdi.local\access` was made an administrator on 17 Nov.** That's a risk (shared, no audit trail); raise it with IT.

**17 Nov – Claire's sign-off reply (16 Nov): aged debtors and creditors reconciled three ways: Access report, our 4 Nov extract, X3 YBALAGEHIST (31 Oct, printed 11 Nov).**
- **The workbook is private** (`scratchpad/ar_ap_signoff/`, names balances, never in git); builder `build_wb.py`.
- **Debtors walk, exact to the penny:** Access £7,876,626.13 (821 items)
  - +£148,751.02: **our sign bug.** Two Access credit notes held as type INV with a negative amount (MAR101, refs 5019602 £74,375.50 and 5018410 £0.01) were loaded as MINV, i.e. positive.
  - −£55,342.05: **5 invoices dated 27–30 Oct missing from the extract.** Cause being checked; 3 of the 5 customers aren't in X3 yet.
  - +£5,069.40: 2 items paid in Access since the extract.
  - = **loaded £7,975,104.50 (814 items).**
  - −£1,121,739.24: **81 items not loaded by the X3 import**: MAR101 (77, the whole account), TEC105 (3), UNI103 (1).
  - = **X3 £6,853,365.26 (733 items).** Every other item matches X3 exactly.
- **Claire's "credits missing": they aren't.** All 20 payments on account and 5 credit notes are loaded. X3 shows them as BACS-2..11, FP-2..5 and STRIPEFP because Access's references repeat. The exceptions are MAR101's (account not loaded).
- **Claire's "Alfred Franks & Bartlett missing": it's one of the 5 invoices not in the extract** (£8,191.34, dated 30 Oct).
- **Creditors walk:** Access £6,483,733.01 (2,691 items)
  - −£859,654.23: most likely timing (to confirm). Entered or paid in Access after the extract but dated ≤ 4 Nov, as Claire's 24 Distribution example shows; spread over 162 suppliers.
  - = **loaded £5,624,078.78 (2,056 items)**
  - −£36,020.20: **8 items not loaded by the X3 import**: SOG500, BRW500 (dated after the accounting date), ECO500, BAL500.
  - = **X3 £5,588,058.58 (2,048 items).**
- **ACCCOD from Claire's customer list, column T:** ASSIGNED → ID, EURO → EU, NON-ASSIGNED → STD. Of the 303 X3 customers:
  - 279 coded (204 ID, 17 EU, all EUR in X3; 58 STD);
  - 4 where merged Access accounts disagree: MAR101, BOO102, DEL101, WHI102;
  - 20 with no match (1 with a balance: TEC109).
- **To fix before the re-extract:**
  1. **BICY build:** an Access INV with a negative amount must load as a credit note (MCRN). Check BISY for the same. (Not fixed yet; only on James's go-ahead.)
  2. Why the 5 late-October invoices weren't extracted.
  3. ACCCOD into YA004BPC column Q.
  4. Acuity's import log for the 81 debtor and 8 creditor items.
  5. **Run the Access aged reports at the same moment as the extract** (Claire's request), with summary reports.
- **17 Nov – sign bug FIXED in `sql/views_v2.sql` (vw_BICX_V2 and vw_BISX_V2) and `sql/export_new_accounts_orders_invoices.sql`.** The type now follows the sign of the open amount: INV with UNALLOCATED < 0 → MCRN; CRN with UNALLOCATED > 0 → MINV.
  - **Effect on the 4 Nov data:** the 2 MAR101 items become credit notes, and the loaded debtors fall from £7,975,104.50 to £7,826,353.48 (−£148,751.02). Nothing else changes: no other negative INV in debtors, none in creditors.
  - **Takes effect when views_v2.sql is run on SDILive** before the re-extract (22.17 step A1). These are our own `migration.` objects, the only kind we may change.
- **Why the 81 debtor items didn't load: their customers aren't in X3.** MAR101, TEC105 and UNI103 were rejected by the YA004BPC customer import (see Run 3 above):
  - XPOSCOD (postcode format): TEC100, TEC105, UNI103, PER101;
  - XSAT (missing State / Region): DRE100, MAR101, PER101, TEC105.
  - MAR101 has 1,205 delivery addresses; one failing address rejects the whole customer.
  - **Check before the re-extract** that the address fixes (Run3_master_data_fixes) are in the customer build and that all 6 load. Then their open items load too.

**17 Nov 15:50 – SL / PL sign-off email SENT to Claire Newall, Ethan Davies, Marc Davies and Jim Hildreth, cc Charlotte Blackwell.**
- **CORRECTION (18 Nov, checked against the sent copy): the EARLIER DRAFT went, not the corrected final.** It contains five errors:
  1. "all 20 payments on account loaded": it's 18 of 20 (WAT01 £4,469.40 and WRB01 £600 were entered after the extract).
  2. "the £859,654 is timing": it's *almost all* timing, to be proved by the same-moment reports.
  3. "Fixed: these now load as credit notes": only **from the next extract**. In X3 today the two MAR101 items are still invoices.
  4. "11; three also need a SIRET": it's 8 needing VAT + SIRET and 3 needing SIRET only; BAL500 also needs its tax rule, and PLS500 has a GB VAT number.
  5. **The "Before you send" note was sent at the bottom.**
  - **A short correction email was drafted on 18 Nov.**
  - **Lesson:** when a draft is revised, check the pasted sent copy against the final before marking it sent. Keep notes to James outside the email block.
- Below is the corrected final, as intended.
- **Subject:** "Aged debtors and creditors – reconciled Access → load → Sage, and what's needed before Thursday's reload".
- **Attachment:** SL_PL_signoff_reconciliation_4Nov_FINANCE.xlsx (private: names customers and balances; within SDI and Acuity only; never in git). Tabs: Read me, Summary, Debtors by account, Debtor items, Creditors by account, Customer codes.
- **What it said:** both walks as above, to the penny; all 5 credit notes and **18 of 20** payments loaded (the other 2, WAT01 £4,469.40 and WRB01 £600, were entered after the extract); creditor gap **almost all** timing; SOG500 / ECO500 / BAL500 are among the 11 FR / ES suppliers missing VAT / SIRET; the sign fix applies **from the next extract**.
- **Asked of Claire (by Wed 18 Nov):** the 4 ACCCOD conflicts, the 20 unmatched customers, the FR / ES supplier numbers, a time on Thursday to run the Access aged reports with the extract.
- **Asked of Ethan:** the country set-up for the 6 customers before Thursday (customers before open items); the import logs for the 81 + 8 items; ACCCOD in YA004BPC column Q; the CAP500 direction (with Jim); X3 aged reports as a summary by account too.
- **On our side:** sign fix into the extract (A1), the 5 late-October invoices found (B4), ACCCOD into the customer file (D10). All are on the 22.17 checklist.
- **Lessons from drafting it (so they're not repeated):**
  - Count before claiming "all": 18 of 20 payments, not 20.
  - Say "almost all timing" until the same-moment reports prove it.
  - Name the real reason per supplier (VAT / SIRET), not a generic "not loaded".
  - A fix in our SQL views only takes effect on the **next extract**; it doesn't change files already built.

**17 Nov – do we regenerate the files from the 4 Nov run? No. The next run is a fresh extract (Thu 19 Nov) with every file rebuilt.**
- The sign fix lives in the SDILive views (`migration.vw_BICX_V2` / `vw_BISX_V2`). The 4 Nov extract already holds the old types, so rebuilding from it changes nothing.
- The other fixes also need new data: BISY document numbers (A1), new parts / BOMs / routes since 4 Nov (B5), ACCCOD and address fixes in the customer file (D10, 10a), Claire's same-moment aged reports (B4).
- Rule 1 applies: live data, extracted on the day, every file rebuilt and sent to Ethan, with the reconciliation workbook rebuilt on the new extract.
- **Not affected, no rebuild needed:** the Live Orders workbooks (sent 16–17 Nov) and the X3 report guides. Live Orders' master files get refreshed from the new run's rebuilt set afterwards (22.17 E).

**17 Nov (late) – Remote Desktop to ACCESS-DB01 fixed without restarting the server: the Remote Desktop service was hung.**
- **The account is `sdi.local\access.group`, not `sdi.local\access`.** That's why `net user access /domain`, `qwinsta` and the first `Invoke-Command` failed: we were sending a name the server doesn't have. It's the name saved in James's Remote Desktop connection.
- **The symptoms, in order:**
  - a hang at "Securing remote connection";
  - with the right account, a certificate warning: the certificate is `Access-DB01.sdi.local`, and we connected by IP. Accept it, or connect by name;
  - "Remote Desktop Services is currently busy". **The service itself was hung.**
- **Cause:** one hung `administrator` session (session 1). Even `logoff 1` hung. No other users were on the server.
- **Fix:** James is IT. It was done over WinRM (port 5985), which keeps working when Remote Desktop is hung:
  ```
  $c = Get-Credential sdi.local\access.group
  $s = New-PSSession -ComputerName ACCESS-DB01 -Credential $c
  Invoke-Command -Session $s { quser }                                   # who is on: warn any Active users first
  Invoke-Command -Session $s { logoff <ID> }                             # gentle fix; hung here
  Invoke-Command -Session $s { tasklist /svc /fi "services eq TermService" }   # must list ONLY TermService
  Invoke-Command -Session $s { taskkill /PID <pid> /F; Start-Sleep 5; sc.exe start TermService; sc.exe query TermService; sc.exe query UmRdpService }
  Remove-PSSession $s
  ```
  Both services came back **RUNNING**.
- **What this touches:** only Remote Desktop sessions on ACCESS-DB01. SQL Server, Access SupplyChain Server and users on their own PCs are unaffected.
- **Never:**
  - kill `csrss` or `winlogon` (it crashes the server);
  - kill a svchost that hosts other services as well;
  - restart the server or SQL Server (it cuts off every Access user).
- **Oddities to look at later:**
  - **`Get-CimInstance` failed in the remote session.** A file named `Get-CimInstance` exists in `C:\Windows\system32` on ACCESS-DB01, probably from a stray output redirect. Check it and remove it.
  - The `access.group` account being an administrator, and the stale `server2k8` reverse DNS, are still open with IT.
- **Lesson:** read the username saved in the Remote Desktop connection before trying other account names.

**17 Nov (17:00–17:20) – the first fix wasn't the end: Remote Desktop still hangs, because of a hidden session that can't be killed.**
- **After restarting TermService:**
  - port 3389 was LISTENING, the firewall rules were on and no reboot was pending; the TCP test was True about a minute later;
  - a clean `Restart-Service TermService` timed out but did no harm.
- **The login succeeds** (RemoteConnectionManager event 1149: `access.group`, from 10.0.0.33). But no desktop appears, and the client gives up after about 90 s.
- **Cause: session 2, the `access.group` session from earlier today, still exists but is hidden.** It's missing from `qwinsta`, and `logoff 2` says "not found". Windows reconnects every new login into it.
  - Its Desktop Window Manager crashed: `WerFault` was running as DWM-2.
  - Task Manager in it had used about 30 minutes of CPU.
- **Its processes can't be killed.** After `Stop-Process -Force`, every process is still there, with its user name blank. They're stuck inside Windows' kernel, so the cause is most likely a driver. Candidates, to check after the restart:
  - the CrowdStrike Falcon sensor;
  - the LogMeIn Rescue driver (about 25 `LMI_Rescue*` processes in that session);
  - the display driver after the Windows Modules Installer run (16:43–16:46).
- **Session 1 (administrator) is in the same state:** its logoff hung.
- **Only a server restart clears kernel-stuck processes.** Do it out of hours: warn Access users, and check what the Active `intercity` console session (session 5) runs first, so it comes back after the restart. `Jack.adm` (session 3, disconnected) is lost too.
- **Until then:** extracts and queries go through SSMS on James's PC, straight to ACCESS-DB01:1433.
- **Find out who ran LogMeIn Rescue on the production server.**
- **Lesson:** if a process is still listed after `Stop-Process -Force` with a blank user name, it's stuck in the kernel. Stop trying to kill things; the way out is a planned restart.
- **17:18–17:21: new sessions fail too, so it's not only the `access.group` session.**
  - Session 6, a fresh session, failed while starting, at the step where Windows' screen-and-graphics layer connects it (LocalSessionManager event 36: `CsrConnected` / `EvCsrInitialized`, 0x800708CA).
  - On disconnect, the same layer timed out (event 20, "send disconnect message to Windows video subsystem failed", 0x80070102 = timeout).
  - **Windows' graphics subsystem is hung, so no new desktop can start.** Only a restart clears it.
  - Remote Desktop reuses the username saved in the connection (`access.group`), even when you mean to log in as another user. Choose "Use a different account", or run `cmdkey /delete:TERMSRV/10.0.0.200` first.
  - `SDI\james.gray` was added to the local Remote Desktop Users group on ACCESS-DB01 (17 Nov), for this test. Keep it or remove it after the restart (`net localgroup "Remote Desktop Users" SDI\james.gray /delete`).
- **Decision (James): no rush restart.** Access, SQL Server, PowerShell remoting and SSMS all work. Restart at an agreed out-of-hours time, or the next patch window.
- **About 17:30: a desktop got through the stuck subsystem by shadowing the console session.** Shadowing attaches to an existing session instead of starting one, so it doesn't need the hung part.
  - The console session is session 5, `intercity`, Active. Leave its programs alone.
  - Allow control without a prompt: set `Shadow = 2` (DWORD) under `HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services`. It wasn't set before.
  - Run `runas /netonly /user:sdi.local\access.group "mstsc /v:10.0.0.200 /shadow:5 /control /noConsentPrompt"`.
  - A black screen with white outline shapes is the console's screensaver: move the mouse to wake it.
  - **Afterwards, remove the value:** `Remove-ItemProperty ... -Name Shadow`. Leaving it set lets any admin take over the console unseen.
  - The vSphere web console is the other route, with no changes needed.
- **OUR MISTAKE: `New-Item <key> -Force` on a registry key that exists DELETES the key and recreates it empty.** We ran it on the Terminal Services policy key above.
  - Recovery: `gpupdate /target:computer /force` re-applied domain and local policy. Afterwards the key held only `Shadow`, so no Group Policy sets anything there. The key was most likely empty before.
  - Only a value written there by hand, outside Group Policy, could have been lost. Told the MSP so they can compare with a backup.
  - **Rule: to set a registry value, use `Set-ItemProperty` alone. Create the key with `New-Item` only after `Test-Path` shows it's missing, and never with `-Force`.**

- **Shadow value removed again (17 Nov, James).** The Terminal Services policy key is back to empty, as it most likely was before. Still open: the planned restart, and the MSP email.
- **About 17:40: tested with `SDI\james.gray` (a new user, saved username cleared). It hangs the same way.** That confirms no new session can start for any user. The way forward is the vSphere console now, or the planned out-of-hours restart.

**17 Nov – new product requests: two emails SENT (James confirmed).**
1. **To Acuity (Marc, Ethan): product fields and cost / sales by manufacturing route. Jira SCRUM-330, register MIG-12. Reply asked by Wed 25 Nov.**
   - **Fields wanted on the product, labelled in SDI's wording:** drawing number, drawing revision, commodity code, stock nominal, COS nominal, sales analysis account.
     - Asked Acuity to add them to the product record **and to the ZSDIITM template** (13 fields today, none of these six).
     - X3 has a standard commodity code field. The BOM screen already has SDI Drawing / Revision fields: can they go on the product?
     - **Nominals:** in X3 these normally come from the product's **accounting code**, which holds the stock / COS / sales accounts, not three fields per product. If Acuity agree, Finance agree the codes and one goes on each product (as ACCCOD for customers).
   - **Cost / sales by route:** in-house, UK sub-contract, Poland sub-contract, Chinese sub-contract. The request was to rename the categories. Asked whether a **statistical group** is better, because:
     - categories drive made / bought behaviour;
     - the import won't change the category of an existing product (the PHANT lesson).
   - **Our side, once the fields exist:**
     - drawing = the part code without the customer prefix;
     - rev = as now (Description 2);
     - commodity and nominal codes: **find the source in Access** (not known yet).
2. **To TTI Customer Services: reviewing the TTI top-level parts before the transfer. Jira SCRUM-331, register MIG-13. SDI builds this; Acuity aren't needed.**
   - **Asked, by Wed 25 Nov:**
     - how to identify a TTI top-level part (customer prefix, TTI sales orders, or their own list; a date cut-off; top level only or with sub-assemblies);
     - which columns (proposed: code, description, drawing, rev, category, unit, price, cost; BOM and route tabs; the new fields);
     - which columns they'll edit;
     - how changes get in;
     - any data not held in Access;
     - who reviews.
   - **How changes get in:**
     - **(a) Corrections in Access before the final run.** Recommended: one source of truth.
     - **(b) An override sheet** that every run applies, with a change log.
   - **Edits made only in the spreadsheet are lost at the next rebuild.**
   - **Timeline:** the workbook goes out after their answers; changes back by **Fri 4 Dec**, in time for the trial run.
   - **On standby (James, 17 Nov):** build the workbook from the latest rebuilt product / BOM / route / cost files as soon as TTI answer. If they choose (b), add an override step to `rebuild/run.py` that logs every change it applies.

**18 Nov – Ethan: master data (customers, suppliers, products, BOMs, routes) and the estimating sheet to be imported again. Plan: what's rebuilt and what's reused.**
- **Rule 1 stands: live data, extracted on the day.** Nothing time-sensitive is reused.
- **Products, BOMs, routes: re-extract and rebuild with the kit** (`rebuild/run.py`). Not reused, even though Run 4 loaded them with 0 errors: parts have been created since 4 Nov (51 works orders had no BOM / route in the 4 Nov set), and the kit makes it automatic.
- **Customers and suppliers:** there's still no builder over every account (SCRUM-166). **Reuse the Run 4 files** (27 Oct build + 4 Nov fixes), then add:
  - new accounts since 27 Oct (`extract_accounts.sql` NEWC / NEWS, then `build_new_customers.py` / `build_new_suppliers.py`);
  - Run 4 / Claire fixes:
    - the 6 address-rejected customers, once Ethan confirms the country set-up;
    - ACCCOD in column Q, once Claire settles 4 conflicts + 20 unmatched;
    - FR / ES VAT / SIRET for the 11 suppliers, once Finance supply them (`fix_suppliers.py`).
- **Estimating sheet:** re-run `estimating/est_to_x3.py` against **this run's** product file.
- **Open items, orders, stock, works orders:** a fresh extract after `views_v2.sql` (sign fix, BISY numbers). Never reused.
- **The 2023 orders test:** `sql/check_old_open_orders.sql` (read-only). It lists every open SO / PO line dated before 2024 from the same views the extract reads, plus a summary by year.
  - At Run 4: 17 PO lines / 8 POs; 385 SO lines / 115 orders.
  - Compare with the two review lists: anything gone has been closed.

**18 Nov – correction email SENT (James confirmed), reply-all on the SL / PL thread** (Claire, Ethan, Marc, Jim; cc Charlotte). It fixed the five errors of the 17 Nov send:
- 18 of 20 payments loaded;
- creditor gap "almost all" timing;
- sign fix from the next extract;
- 8 suppliers need VAT + SIRET and 3 need SIRET only (plus BAL500's tax rule and PLS500's GB VAT);
- ignore the "Before you send" note.

The figures were unchanged.

**18 Nov – Claire (10:13): add the suppliers' email addresses from Access to Finance's supplier list. Remittances are bouncing; some addresses are wrong or don't say which company they are. "ASAP".**
- **Her list:** `Supplier List.xlsx`, sheet "List Data", 1,000 suppliers, column J "Remittance email address" empty (row 2 note: "From address section"). Kept private in `scratchpad/claire_supplier_emails/`, never in git.
  - The same email chain repeats her **29 Oct requests, still open:**
    - customer emails into the right Sage fields (4 places; invoices list from Selina; notes for a query address);
    - supplier bank details;
    - do the invoice addresses on her lists match the Sage accounts;
    - copies of all sales invoices / credits and all purchase invoices in ADM.
- **Where it is in Access:** Supplier → Address/Contact → **"Email (Statements)"** (Claire's screenshot). The column name isn't known, so:
  - **`sql/supplier_emails.sql` (read-only)** finds every text column with an '@' in every PL_ table keyed by supplier (SUCODE / AD_ACC_CODE). It returns a SUMMARY grid (suppliers per table.column) and an EMAIL grid (supplier, table, column, value).
  - **`scripts/fill_supplier_emails.py "<Supplier List.xlsx>" supplier_emails.txt out.xlsx`:**
    - fills J (PL_ACCOUNTS column with MAIL in its name first);
    - adds "Other emails in Access" (each with its table.column) and an "Email check" column: not valid / several in one field / free mail / doesn't contain the supplier's name / no email in Access.
    - It changes nothing else. Tested on dummy data.
- **Bank columns (L, M) are not filled here.** Bank details live only in `bank_private/` (rule), and go to Finance separately if asked.
- **Did Claire supply bank details? No.** Her list's "New Sage code", "VAT code", both email columns, "Bank sort code" and "Bank Account number" are **empty on all 1,000 rows**. Her 29 Oct email asks **us** to fill them. The filled columns (name, balance, phone, address, currency, contact) came out of Access, which we already load from.
- **James (18 Nov): what Finance send on, they intend to be reloaded.** So whatever we fill must also go into the X3 supplier files: emails and VAT checks into YA004BPS, bank details into YA004BPSC. They shouldn't stay only on her sheet.
- **Extended the same day:**
  - `supplier_emails.sql` adds a **SAGE** grid (Access → Sage code from XREF_SAGE_BPS) and a **TAX** grid (every VAT / TAX column on PL_ACCOUNTS).
  - `fill_supplier_emails.py` fills A (Sage code), G (VAT code: the column with VAT + CODE in its name), J, and, with `--bank <supplier_bank_details.sql output>`, L and M.
  - **With --bank, the workbook is confidential:** Finance only, private folder.
  - Re-run `supplier_bank_details.sql` live; the copy in `bank_private/` dates from 28 Oct.
- **Bank status in X3:** YA004BPSC was built 3 Nov (626 BACS suppliers; 37 on Check; 44 on transfer terms not in the file). Whether Ethan loaded it in Run 3 / 4 isn't recorded. **Ask Ethan.**
- **CORRECTION (James, 18 Nov): Claire asked only for the email addresses.** Apply only what's asked. `fill_supplier_emails.py` now fills **emails only** by default. `--codes` (Sage / VAT code) and `--bank` stay switched off unless Finance ask. The Sage code, VAT code and bank columns are left as she sent them. The 29 Oct items stay logged as open, not done unasked.

**18 Nov 10:40 – Jim Hildreth (Acuity) answered the product-fields email (SCRUM-330).**
- **Nominals: no product fields needed.** The stock / sales / COS accounts come from the **accounting code**, which the **product category** sets. The import inherits it; it isn't in the import file.

  | Category | Accounting code | Stock | Sales | CoS |
  |---|---|---|---|---|
  | FGML (sold, manufactured) | FG_MANUF | 230100 | 600100 | 700100 |
  | FGSL (sold, bought in / outsourced) | FG_OUTSRC | 230500 | 600500 | 700500 |
  | PHANT (sub-assembly) | FG_MANUF | 230100 | 600100 | 700100 |
  | RAWML (raw materials) | RAWMAT | 230000 | 600400 | 700400 |

- **What this means for the migration: the category now decides where every product posts in the ledger.**
  - **In-house vs outsourced is already split:** FGML → 600100 / 700100, FGSL → 600500 / 700500.
  - **The open category questions are now finance questions:**
    - the 451 FGSL stock-managed products (£1.72m stock) post to 230500;
    - the 15 products X3 holds as bought-in that Access routes would post as outsourced;
    - the PHANT group B decision.
  - **And the import won't change an existing product's category,** so a wrong category means wrong postings until someone changes it by hand.
  - **Finance (Claire) should confirm these accounts** against the chart of accounts and the year-end opening balances.
- **Jim's question:** "would the same single product not potentially be shared across those 3 'routes'?" (UK / Poland / China sub-contract).
  - If a product can come from more than one country, the split belongs on the **purchase** (supplier or order), not the product.
  - If each product has one route, three FGSL-type categories, each with its own accounting code, would give separate ledger accounts.
  - **To answer with data:** `sql/products_by_supplier_country.sql` (read-only) shows, for every product bought in the last 24 months, how many supplier countries it came from (SUMMARY), and lists every product bought from more than one (SHARED).
- **Still unanswered by Acuity:** drawing number / revision / commodity code on the product and the ZSDIITM template; statistical group vs categories.

**18 Nov – RULE (James): no failed loads. Month-end-style reconciliations must line up 100%, apart from documented adjustments made after the extract.**
- **Did we use fake VAT numbers or bank codes? Not ours; dummies were inherited and removed.**
  - **VAT:** the UAT data before our rebuild had dummy VAT numbers: two real Polish numbers copied across 117 suppliers, TEMPJAF placeholders, GB numbers on overseas companies. They caused 180 supplier rejections. Run 2 blanked 185 of them.
  - **Our rule since:** never a placeholder. A blank loads for UK accounts; FR / ES accounts need the real number, which is why the 11 suppliers still fail.
  - **Bank:** BIDNUM = `XXXX` + real sort code + real account number. The `XXXX` stands in for a bank identifier Access doesn't hold, as Ethan's template note asks. The account details are real.
  - **To confirm with Ethan:** that X3 accepts `XXXX`, and whether YA004BPSC was loaded.
- **How we get to no failed loads:**
  1. **Pre-load check on our side.** Before handing files over, check every customer and supplier against the rules X3 rejected on: postcode format (XPOSCOD), mandatory region (XSAT), FR / EU VAT format and key, SIRET, tax rule, and two emails in one field. Anything that would fail goes to a named owner before the run, not into the load.
  2. **Load order:** customers and suppliers before open items and orders, so no transaction misses its account.
  3. **Load report from Ethan for every file:** rows sent, rows loaded, rows rejected, with the log. A file isn't done until rejected = 0, or each rejection has a named reason and owner.
  4. **Same-moment reports:** Access aged debtors / creditors run at the extract moment (Claire), then a three-way reconciliation (Access = loaded = X3). The only differences allowed are documented adjustments made after the extract.

**18 Nov – master-data fix-up for Ethan's reload (James: "we can't wait; do what we can, eliminate rejections"). Output: `scratchpad/run5_master/`.**
- **BUG FOUND AND FIXED: the 4 Nov address fixes never blanked anything.** `ws.cell(r, c, None)` in openpyxl **leaves the old value**: it only writes when the value isn't None.
  - So every fix that should *empty* a field was logged on "Address fixes" but not applied:
    - DRE100's "239600" stayed in the postcode;
    - "IRELAND", "TURKEY", "ROMANIA", "INDIA", "MALAYSIA", "MEXICO" stayed in M&S / PER101 postcodes;
    - postcodes moved out of an address line stayed in the line too.
  - 26 values in all (customers 11 postcodes + 15 address lines; suppliers 1). **This is part of why the six customers failed again in Run 4.**
  - Fixed in `fix_customer_addresses.py` and `fix_suppliers.py` (`ws.cell(r, c).value = new or None`). No other script writes a blank this way: checked by grep.
  - **Lesson:** to blank a cell in openpyxl, assign `.value = None`; never `ws.cell(r, c, None)`. Check the data, not just the change log.
- **Supplier VAT checked:** no dummy or repeated VAT number left in YA004BPS (431 with VAT, none repeated, no TEMPJAF).
- **Rebuilt, same inputs as Run 4 plus the fixed scripts:**
  - `fix_customer_addresses.py` (507 fixes, now applied) → `fill_customer_vat.py` (4 Nov grid) → `fix_suppliers.py`.
  - Then two new steps:
    - **`hold_risky_addresses.py` (new): one failing address rejected a whole customer.** For the six rejected customers it holds back each non-default address that is:
      - in a country needing a State/Region X3 doesn't receive yet (AE, CA, AU, US; the template's region column has no field code);
      - in a country found only on the rejected customers (BM, BR, CA, CY, IN, MC, MT, MY, PT, PY, RO, SG, TH, TR);
      - or has a postcode failing our format check.

      26 held (MAR101 11, PER101 10, TEC105 4, TEC100 1), in `Held_addresses_for_later.xlsx` (BPC + BPCDL rows) to load once X3's country set-up is fixed. Nothing invented.
      - **Not rescuable this way:** DRE100 (AE) and UNI103 (CA), whose only address is the problem. They need Ethan's region field / country set-up. DRE100 holds no items; UNI103 holds 1.
    - **`fill_customer_acccod.py` (new): ACCCOD in column Q** from Claire's column T. ID 208, EU 21, STD 74.
      - **24 provisional**, on the "ACCCOD" tab for Claire:
        - 4 merged-account conflicts → majority, tie → ID (MAR101, BOO102, DEL101, WHI102 → ID);
        - 20 not on her list → EU for euro accounts (TEC106 / 109 / 111 / 116), else STD.
- **Result:** YA004BPC 6,143 rows / 303 customers (MAR101 1,194 addresses); YA004BPCDL 6,143; YA004BPS 706.
- **The 11 French / Spanish suppliers: NOT mocked.**
  - **Why:**
    - A mock VAT number that passes X3's check could be another real company's number.
    - We don't know yet whether a reload can overwrite an existing supplier (open with Marc), so a mock could stick.
    - The Run 2 dummies cost 180 rejections.
  - **Instead:** the real numbers are on the French public register (annuaire-entreprises.data.gouv.fr; blocked from this session's network).
    - **Only the SIRET is needed per French supplier:** the VAT number = FR + key + SIREN is calculated. The formula reproduces the 3 VAT numbers we hold.
    - `apply_supplier_ids.py <YA004BPS> Suppliers_SIRET_to_fill.xlsx` checks SIRET / SIREN (Luhn) and VAT key, and loads only valid numbers, logged on "Supplier ID fixes".
  - **Still open with Finance:** BAL500's tax rule (DOM, kept as Access has it); PLS500 (ES supplier with a GB number that fails the check).
- **DECISION (James, 18 Nov): for SDI source data that's missing, mock data we know will load, for this trial load. Questions about X3's set-up go to Ethan; source data comes from SDI.** Done with `apply_supplier_ids.py --mock`:
  - **8 suppliers with obviously fake numbers that pass X3's checks:** AMG500, AGE500, GRO500, VUS500, SOG500, BAL500, ECO500 (FR) and PLS500 (ES).
    - FR: SIREN `0000000nn`, which no real company has, never all zeros; SIRET = SIREN + `0001n`; VAT = FR + key + SIREN.
    - ES: `ESB0000000n`, a CIF of zeros with its control digit; it replaces the invalid GB number.
  - **3 with real SIREN / VAT but a mocked 5-digit site number:** GAL500, ICE500, BUR500.
  - Every mock is marked MOCK on the "Supplier ID fixes" tab. BAL500 keeps tax rule DOM (as Access) until Finance decide.
  - **GUARD:** without `--mock` the script refuses a file holding any mock, by the `0000000nn` / `ESB000000` patterns or the MOCK lines in the change log. So mocks can't reach the dress rehearsal or go-live.
  - **Before the dress rehearsal:** the real SIRETs (public register, annuaire-entreprises.data.gouv.fr; only the SIRET is needed per French supplier), then re-run without `--mock`.
  - **Risk to watch:** if a reload can't update an existing supplier (question to Ethan / Marc), the mocks stay in SDIMIG and the real numbers would need entering by hand.
- **Questions for Ethan (all X3 set-up, none Access data):**
  1. the field code for YA004BPC's "County / region" column, and whether region codes are ISO;
  2. country set-up for the held addresses' countries;
  3. do ID / EU / STD exist as accounting codes;
  4. does a reload update existing customers / suppliers;
  5. load order (customers → delivery addresses → open items / orders) and a sent / loaded / rejected report per file;
  6. was YA004BPSC loaded, and is the `XXXX` prefix accepted.

**18 Nov 11:30 – products, BOMs, routes and costs rebuilt from today's live extracts** (`extract_products.sql`, `extract_routes.sql` as at 11:27; `rebuild/run.py runs/2026-11-18 --previous runs/run4_loaded --loaded <Run 4 ZSDIITM> --previous-costs <Run 4 YITC> --suppliers run5_master BPS --today 20261118`; 59 seconds, every builder's checks passed).
- `runs/run4_loaded/` holds what Ethan loaded in Run 4: ZSDIITM, ZSDIITMSUP and ZSDIROU2 from `Ethan_fixes_2026-11-05`; YITC and BOM from `Current_mapped_set_2026-11-04-pm`.

| File | Run 4 | 18 Nov | Added | Removed | Changed |
|---|---|---|---|---|---|
| ZSDIITM products | 19,883 | 20,124 | 250 | 9 | 85 (descriptions 84, weight 1; **no category changes**) |
| YITC costs | 19,883 | 20,124 | 250 | 9 | 33 (zero → real cost) |
| YA00408BOM lines | 32,941 | 33,122 | 317 | 136 | 33 |
| ZSDIROU2 operations | 33,499 | 33,864 | 482 | 117 | 23 |

- **The 9 removed products** are one-off service codes no longer live in Access (COSHHREPORT, EN101122-FIRE, EN101133-ANNUAL...). They stay in X3; leaving them out doesn't delete them.
- **Held back, by rule:**
  - 129 products;
  - 439 BOM lines (268 on bought-in products, 157 with no quantity in Access, 9 with a component not in the product file, 5 exact repeats);
  - 318 route operations on bought-in products.
- 3 routes are still over 150 operations.
- 1,164 products are costed at zero (158 stocked).
- **Estimating import re-run** (`est_to_x3.py dave_in/IMPORT.xls ... --products <18 Nov ZSDIITM> --parent IMPORT`): 0 stops, 1 warning (FIXING49 "DONT USE"), BOM 14 lines, route 30 operations. Same as 13 Nov.
- **Not rebuilt today:** ZSDIITMSUP product-suppliers. It needs `product_suppliers_v4.sql`; it wasn't on Ethan's list.
- **extract_accounts.sql failed** (Msg 207: an ORDER BY used column aliases inside an expression). Fixed and re-sent; James is re-running it. It will show any customer or supplier opened since 27 Oct.
- **Hand-over folder:** `scratchpad/Run5_master_data_2026-11-18/`: customers, delivery addresses, suppliers (trial mocks), held addresses, products, costs, BOMs, routes, WHAT_CHANGED, and `estimating_IMPORT/`.

**18 Nov 11:31 – `extract_accounts.sql` (fixed) run: 303 customers and 707 suppliers have Sage codes; 37 customers and 96 suppliers that trade in Access have NONE (NEWC / NEWS).**
- **FOUND: why the 5 late-October invoices weren't in the 4 Nov extract.** AFB01, MUN01, TDG03, BWS01 and KOM01 have **no Sage code** in `migration.XREF_SAGE_BPC`. The views join on it, so their items and orders are dropped.
  - The transaction extract's CHECK lines ("BICX items dropped - customer has no Sage account") count exactly this. They weren't 0 on 4 Nov and weren't acted on.
  - **Rule from now:** the CHECK "dropped" lines must be 0, or only the accounts left out on purpose, before any build. `run_transactions.py` should stop otherwise.
- **New trading accounts with open business (must be added, or their items / orders miss X3):**
  - **Customers with open items, 7, £97,961.53:** AFB01 (2), BWS01, TDG03, ISL04 (£30,000), KOM01, LBU02, MUN01.
  - **Customers with open SO lines only, 15:** FWP01, CPG01, GFL02, GUL02, MRO01, TIE16E, CRC01, JMS01, WJS01, CSL03, CTS01, ISG01, OTL01, UAB02, WPI01. Several have only 2023–24 lines: check against the old-orders clean-up.
  - **Suppliers with open items / PO lines, 14:** GRD01, CIL01, TWW02, UAL01, WGS02, CLL01, DCD01, EMA01 (note "see AUL03": a duplicate?), FBS01, KRD01, PIF01, SCI01 (£16,586.40), SDS05, SJD01.
- **Left out on purpose (27 Oct rule; still for Finance to confirm):**
  - intercompany (VIV01, SDI02);
  - ledger accounts (ESD01, FSC01, HMR01, PET03, LBC04);
  - no address (IBS01);
  - "do not use" (ERG01, ZZZ01);
  - **employee expense accounts.** 18 of them hold open items (~£4.4k, mostly dated 31 Oct). If they stay out, those items are a reconciling difference. Finance to decide.
- **Trading but nothing open:** BOT04 (part of BOO102) and MAR38 (M&S Ireland) aren't in the cross-reference, along with ~10 others. Add them for completeness when the new accounts go in.
- **To add them (the 27 Oct route):**
  1. `new_customer_details.sql` / `new_supplier_details.sql` (read-only) → `build_customers_to_add.py` (new codes) → `build_new_customers.py` / `build_new_suppliers.py`;
  2. merge into the run5 files with today's fixes;
  3. a cross-reference insert for `migration.XREF_*` (our own objects), run before Thursday's transaction extract.

**18 Nov (pm) – the trading accounts with no Sage code are added: 32 customers, 35 suppliers.**
- **Inputs:** `new_customer_details_live.sql` (new, read-only, live rule; 37 customers, 84 addresses) and `new_supplier_details.sql` (96 suppliers).
- **Customers:**
  - `build_customers_to_add.py` gave new codes, checked against today's customer file: e.g. AFB01→ALF100, MUN01→MUN100, TDG03→TOP103, BWS01→BRI101, KOM01→KOM100, ISL04→INN102, LBU02→LMB100.
  - `build_new_customers.py` built 33 customers / 53 address rows.
  - **Left out:** ESD01 and FSC01 (ledger accounts), VIV01 and SDI02 (intercompany), and ISO100 / IBS01 (no address in Access, nothing open: it would only be rejected).
  - ACCCOD from Claire's column T, where she has the account; otherwise provisional (EU for euro accounts, else STD).
- **Suppliers:** `build_new_suppliers.py` added 35 (every supplier with open items or PO lines, **including 18 employee expense accounts with open claims**, plus trading suppliers). It left out 56 expense accounts with nothing open and 5 non-suppliers.
  - **Claire to confirm** that expense claims load as suppliers; it's needed for creditors to reconcile 100%.
- **TWO BUGS CAUGHT BEFORE ANYTHING RAN:**
  1. **`build_new_suppliers.py` picked codes against the October file (`out_v8`)**, so 5 new codes (CLA501, CON504, STA501, STE502, WIL501) already belonged to other suppliers. `merge_new_accounts.py` refused to add them.
     - **Fixed:** the builder now takes `EXISTING_BPS` = the run's supplier file. The codes became CLA502, CON505, STA502, STE503 and WIL502.
     - All 67 new codes were checked against the full cross-reference (extract_accounts XREFC / XREFS): no clash.
  2. **The builder's generated `sql/xref_new_supplier_accounts.sql` starts with `DELETE FROM migration.XREF_SAGE_BPS WHERE MATCHED_BY = 'new account'`.** Run as is, it would have removed the 83 suppliers added on 27 Oct, and their invoices and orders would drop out.
     - The 27 Oct file was restored from git (the builder overwrites it on each run: restore it after every run).
     - **Use `sql/add_new_accounts_2026-11-18.sql` instead:** insert-only (never deletes), skips any account or Sage code already there, explicit transaction and COMMIT, then checks: added 32 / 35; after commit 335 customers / 742 suppliers in the cross-reference.
- **`merge_new_accounts.py` (new):** appends the rows to the run's customer, delivery-address and supplier files, rewrites the load files, and adds a "New accounts" tab. It refuses a code already in a file.
- **Result:** YA004BPC 6,195 rows / 335 customers; YA004BPCDL 6,195 (keys match the customer file); YA004BPS 741.
  - Hand-over folder and zip refreshed. The to-add decision lists stay in `runs/2026-11-18/new_accounts/`, not in Ethan's zip: they name employees.
- **Order for Thursday:**
  1. Ethan loads customers → delivery addresses → suppliers.
  2. James runs `add_new_accounts_2026-11-18.sql` (it changes only our migration tables), then `views_v2.sql`.
  3. Then the transaction extract: its CHECK "dropped" lines must now show only the accounts left out on purpose.

**18 Nov – `add_new_accounts_2026-11-18.sql` RUN by James (earlier than planned; safe, insert-only): ADDED 32 / 35; AFTER COMMIT 335 customers / 742 suppliers in the cross-reference, exactly as expected.** A re-run on Thursday shows 0 / 0. From now on the extracts carry these accounts' items and orders; Ethan must load the new customers and suppliers before the open items.

**18 Nov – Tim's estimate files (MS-0359869, Gift Card Header 12539-04-GA rev B), as sent on 16 Nov, checked against today's data.**
- **Re-run on today's product file:** byte-for-byte the files James holds (route 9 operations, BOM 8 lines; 0 stops, 0 warnings).
- **Against the migration's own route and BOM from Access (in today's ZSDIROU2 / YA00408BOM):**
  - the route is **identical**;
  - the BOM has the **same 8 components and quantities**, but:
    - the line order differs (Access 10 = SHEETMETAL11; estimate 10 = UPCSTICKER001);
    - the estimate's sheet quantities are unrounded (0.015848 vs 0.016);
    - the estimate leaves the validity dates blank (Access 19900101–20791231).
- **Rule: don't load both for the same part.** MS-0359869 is already in the migration files. Loading the estimate's BOM on top could pair line numbers with different components if X3 updates by line.
  - The estimate files prove the converter reproduces Access.
  - To test the estimating import in X3, use the IMPORT test part (`estimating_IMPORT/` in the hand-over zip), which is new and in nothing else.

**18 Nov – master-data email SENT to Ethan (cc Marc), with `Run5_master_data_2026-11-18.zip` (James confirmed).**
- **The zip holds:**
  - customers 6,195 rows / 335; delivery addresses 6,195; suppliers 741;
  - products 20,124; costs 20,124; BOM lines 33,122; route operations 33,864;
  - Held_addresses_for_later.xlsx; WHAT_CHANGED;
  - `estimating_IMPORT/` (the test part to load);
  - `estimating_TIM_MS-0359869/` (Tim's original estimate + converted files: for comparison, **not to load**).
- **Not in it:** ZSDIITMSUP (offered); YA004BPSC bank (separate, confidential route).
- **The email laid out:**
  - the changes (address-fix bug, 26 held addresses, ACCCOD, placeholder supplier IDs, 32 + 35 new accounts);
  - a table of **everything provisional and who at SDI is confirming it**: SIRETs, 24 ACCCOD, expense accounts, intercompany / ledger accounts, BAL500 / PLS500, Jim's category accounts, product categories, zero costs, 2023 orders, TTI review;
  - the load order and a per-file sent / loaded / rejected report;
  - Ethan's 6 questions (region field code, country set-up, ACCCOD codes exist, **does a reimport update existing records** (the key one), bank file / XXXX, CAP500).
- **No individuals named:** expense accounts appear as a count.
- **James's follow-up to Ethan (18 Nov):** read it through before loading. Load Friday 20 Nov together, or Ethan runs test loads and feeds back. We're knowingly using placeholders to make imports work, as long as everyone knows and the users' answers keep coming.
- **SDI actions this week:**
  1. SIRET lookups (public register);
  2. one email to Claire with her questions;
  3. run `check_old_open_orders.sql` and chase Purchasing / Customer Service.
- **Follow-up SENT to Ethan (James confirmed):** read it through before loading; load together Fri 20 Nov, or Ethan test-loads and feeds back. Placeholders and provisional values are listed in section 4 of the email. Asked for per-file results and the six answers, above all whether a reload updates existing records.
- **Consequence:** the transaction extract (and Claire's same-moment aged reports) follows the master-data load, so it's Fri 20 Nov or later, not Thu 19 Nov.

**18 Nov – two emails DRAFTED, to send Fri 20 Nov (James).** The full text is in `scratchpad/drafts/DRAFTS_to_send_Fri_20Nov.md` (private: it names customers and staff, so not in git).
1. **To Claire (cc Charlotte): Finance decisions.**
   - ACCCOD: the 4 merged-account conflicts (provisional ID) and 21 customers not on her list (EU for euro accounts, else STD), listed by name and code.
   - Do staff expense accounts with open claims (18, ~£4,400) load as suppliers?
   - Confirm the accounts left out (2 intercompany, 5 ledger).
   - FR / ES suppliers: we look up the SIRETs unless Finance holds them; BAL500's tax rule; PLS500's GB VAT number.
   - Confirm Jim's category accounts (230100 / 600100 / 700100; 230500 / 600500 / 700500; 230000 / 600400 / 700400).
   - Timing of the same-moment aged reports (after the master-data load).
   - Her supplier email list (after `supplier_emails.sql`); her 29 Oct requests still open.
2. **To Jim (cc Marc, Ethan, Charlotte).**
   - The CAP500 £22,500 journal direction.
   - For the next load: X3 aged debtors / creditors as a summary by account plus the trial balance, at the same moment.
   - Confirm the X3 treatment of expense accounts (as suppliers) and of intercompany / ledger accounts (left out).
   - The sub-contract-routes answer by Friday. If `products_by_supplier_country.sql` has run by then, put the answer in.
- **Other emails still to deal with:**
  - MSP / Jack: the server restart (drafted 17 Nov; sent?);
  - Jim's sub-contract answer (needs the SQL);
  - Claire's supplier emails (needs `supplier_emails.sql`);
  - the 2023 orders chaser (needs `check_old_open_orders.sql`);
  - Live Orders: Neil's position and Q6–9 were due 18 Nov; chase 19 Nov;
  - Marc's validation of the guide screens (to draft);
  - Claire's year-end guide email (to draft);
  - the rebate due-date correction (waits on Nick Garrish);
  - training-site logins (wait on Acuity).

**18 Nov – James: add the product-supplier links (ZSDIITMSUP) and supplier bank details (YA004BPSC) to this set.** Both queries read `migration.XREF_SAGE_BPS`, which now holds 742 suppliers including the 35 new, so they need no change.
- `sql/product_suppliers_v4.sql` (read-only; grid 2) → `extract/product_suppliers.txt` → `rebuild/run.py ... --suppliers <run5 BPS>` builds ZSDIITMSUP.
- `sql/supplier_bank_details.sql` (read-only, CONFIDENTIAL) → `scripts/build_bpsc.py` → `bank_private/` only.
  - It goes to Ethan **separately, never in the general zip or in git**: a password-protected file with the password given by phone, or Acuity's secure share.
- Both go to Ethan as a follow-up to the 18 Nov master-data email.

**18 Nov – GOAL (James): "the BEST, MOST COMPREHENSIVE set of data, even if we fill gaps pending."** How we apply it:
1. **Every record that trades goes in.** No account, product, BOM, route, link or bank detail is left out for want of data.
2. **A gap the users must answer is filled with a placeholder that loads**, never left blank to fail. Each placeholder is:
   - **obvious** (it can't be mistaken for real data, e.g. SIREN `0000000nn`);
   - **flagged** (a tab in the file and a line in the hand-over email);
   - **owned** (who at SDI replaces it, by when);
   - **guarded** (the build refuses it for the dress rehearsal / go-live unless told otherwise).
3. **A gap only X3's set-up can close** (a region field code, a country's postcode rules) isn't faked. The record is held in its own file, ready to load the moment Ethan fixes it.
4. **Nothing is dropped silently:** every exclusion has a reason and an owner (the accounts left out on purpose, the held addresses).

**State of the 18 Nov set against this goal:**
- **Filled with flagged placeholders:**
  - the 11 FR / ES supplier VAT / SIRET numbers;
  - 24 + 1 provisional ACCCOD;
  - 18 expense accounts loaded as suppliers (Finance to confirm);
  - 1,164 products at cost 0 (158 stocked). 0 is the placeholder; SDI to price.
- **Held for X3's set-up:** 26 delivery addresses; DRE100 and UNI103 (their only address needs a region).
- **Being added now:** ZSDIITMSUP (product_suppliers_v4.sql) and YA004BPSC (supplier_bank_details.sql, confidential route).
- **Still to enrich:**
  - supplier remittance emails (Claire's list; `supplier_emails.sql`);
  - customer emails per purpose (statements / invoices / queries): her list's three email columns are empty on all 515 rows, so the source is Access plus Selina's invoice list, and the X3 fields are Ethan's;
  - 26 of 335 customers have no email on their default address.

**18 Nov – product-supplier links and supplier bank details built.**
- **ZSDIITMSUP** (`product_suppliers_v4.sql` → `run.py`): **14,987 pairs** (11,024 main, 3,963 alternatives); +260 / −19 against Run 4.
  - 4,139 held: product not in the product file (products not migrated).
  - The other files are identical to the morning's build (same extracts), so the rebuild is deterministic.
  - Added to the hand-over zip with the updated WHAT_CHANGED.
- **YA004BPSC** (`supplier_bank_details.sql`, 741 suppliers = the supplier file; `build_bpsc.py`, now with `SUPPLIERS` = the run's BPS .txt): **658 loaded** (626 on 3 Nov), 44 not paid by BACS (not loaded), **39 BACS suppliers with no bank details in Access** (on the Check tab, for Finance).
  - **Bank details are never placeholdered:** a wrong account could receive a payment.
  - Files: `bank_private/YA004BPSC_bank_details_MAPPED_2026-11-18.xlsx / .txt` (chmod 600). The raw query output was deleted from the uploads folder.
  - **NOT in the zip.** It goes to Ethan separately: James protects it with his own password (7-Zip, AES-256) and gives the password by phone.
- **James (18 Nov): no password on the bank file; it would only confuse.** It goes to Ethan as a plain attachment, addressed to Ethan only. It's still kept out of the hand-over zip and git, and the source stays in `bank_private/`.

**18 Nov – follow-up SENT to Ethan (James confirmed):** the updated zip (with ZSDIITMSUP, 14,987 pairs) replaces the earlier one. The supplier bank details went as a separate attachment, no password, Ethan only: 658 BACS suppliers; 44 not BACS; 39 BACS with no bank details, which Finance are following up.
- **Ethan now holds the full set:** customers, delivery addresses, suppliers, products, costs, BOMs, routes, product-supplier links, held addresses, WHAT_CHANGED, estimating IMPORT + Tim, and bank details.
- **Next:** the pre-load check (`scripts/preload_check.py`) on the hand-over set, before Friday's load.

**18 Nov – PRE-LOAD CHECK built and run on the hand-over set: 23 checks, 16 PASS, 0 FIX, 7 NOTE.** `scripts/preload_check.py <hand-over folder> <out.xlsx> [--bank <BPSC .txt>]`; result in `runs/2026-11-18/Preload_check_2026-11-18.xlsx`.
- **PASS (structural: these would be rejected or load wrong):**
  - one default address per customer;
  - ACCCOD is ID / EU / STD; tax rules set;
  - delivery addresses match customers address for address;
  - supplier codes unique; every FR supplier has a VAT with the right key and a SIRET that passes Luhn and matches the SIREN; ES VAT format;
  - bank: every row's supplier is in the supplier file, and BIDNUM = XXXX + 14 digits;
  - product codes unique; categories valid;
  - every cost, BOM parent / component, route product and product-supplier link points at a product (and supplier) in the files;
  - every route work centre is one we map to.
- **CALIBRATED against Run 4 (lesson: check against what X3 actually rejected, not a stricter idea of it).** The first run flagged 561 records, but the same patterns are on customers and suppliers X3 **loaded** in Run 4. They're now **NOTE\*** (data quality, worth tidying in Access, not a reason to stop):
  - 349 postcodes not in the country's usual format (306 GB, e.g. "FAO-", "LE5"; 33 DE holding GB postcodes: wrong country?);
  - 171 GB addresses with no postcode;
  - 26 default addresses with several emails in one field;
  - 3 GB supplier postcodes ("LANCS BB5");
  - 12 US / AU / AE / CA addresses with a region that X3 accepted (EGO100, AE, default address).
  - **So the six customers' Run 4 failures came from our unapplied fixes**, not regions in general. DRE100 and UNI103 are in the file and may load now.
- **NOTE (placeholders, 1,172):** 8 mocked FR / ES suppliers + 1,164 products at cost 0. The 3 mocked SIRET site numbers (GAL500, ICE500, BUR500) are on the supplier file's "Supplier ID fixes" tab. Plus the held-addresses file.
- **Run it on every hand-over from now on.** FIX must be 0 before a set goes to Ethan.

**End of 18 Nov. Next:**
- **Fri 20 Nov:** load with Ethan (or his test-load feedback); send the Claire and Jim drafts; then the transaction extract after `views_v2.sql` (`add_new_accounts_2026-11-18.sql` already run), with Claire's same-moment aged reports; three-way reconciliation.
- **Queries for James when convenient:** `supplier_emails.sql` (Claire's list), `check_old_open_orders.sql` (2023 orders), `products_by_supplier_country.sql` (Jim, Friday).
- **Waiting:** Ethan's 6 answers; Finance decisions; TTI (25 Nov); Neil / Q6–9 (chase 19 Nov).

**18 Nov (late) – Ethan's reply:** too much is still open with SDI users, so he will **push the imports through himself today, note the issues and relay them in one email**. Missing records go through on Fri 20 Nov.
- **His goal for go-live: Products, Customers, Suppliers, BOMs, Routes and Supplier Products fully ready, with "no excluded records and no import errors".**
- He asked for the **Supplier Banks import (YA004BPSC): it has never been tried.** That answers our question: it was not loaded in Run 3 or 4. It was attached to the follow-up; re-send it.
- **"No excluded records" needs agreeing:** some exclusions are scope by design, some are pending SDI. Counts from the 18 Nov build:
  - **Scope, out by design (not trading in 24 months, or not a trading account):**
    - 22,256 dormant products, with their 7,743 BOMs and 7,323 routes;
    - 4,139 product-supplier links on those products;
    - intercompany (2) and ledger (5) accounts;
    - 56 expense accounts with nothing open;
    - 44 suppliers not paid by BACS (no bank row, as the template asks).
  - **Pending, must be resolved for go-live:**
    - **129 products held:** two Access codes become the same X3 code under the code rule (e.g. "BOP METAL0006" and "BOPMETAL0006"). SDI must decide which keeps the code, and give the other one a new code.
    - 268 BOMs and 318 route operations on products held as bought-in (category decision);
    - 157 BOM lines with no quantity in Access; 9 BOM components not in the product file; 5 exact repeat lines;
    - 26 held delivery addresses (X3 country set-up, Ethan);
    - ISO100 (no address);
    - 39 BACS suppliers with no bank details (Finance).
- **Reply SENT to Ethan (James confirmed):** go ahead with today's test loads and one issues email; the supplier banks are on the earlier follow-up (no re-attachment); "no excluded records" agreed for everything that trades, with the scope / pending split above. **Next: Ethan's issues email.** Work it against the pending list. Anything failing outside that list is new.

**19 Nov – the session moved to a fresh machine overnight: the scratchpad is EMPTY.**
- **Lost:** every private working file: the hand-over set and zip, `run5_master/`, `runs/2026-11-18/` (extracts and outputs), `bank_private/`, `ar_ap_signoff/`, `finance_private/`, `drafts/` (the Friday emails to Claire and Jim), Claire's uploads, and the register builder (`register/`, `acuity_register/`).
- **Safe:**
  - everything in git (scripts, SQL, this runbook), which rebuilds every file from fresh extracts;
  - Ethan already holds the hand-over zip and the bank file.
- **Lesson:** the scratchpad is NOT durable. Private outputs James needs to keep (bank, Finance, drafts) must also be saved on SDI's side when produced. Anything rebuildable needs its inputs (the extract outputs) kept by James.

**19 Nov – Sue Rogers (Customer Services, 18 Nov 16:09): the new Sage codes for 7 Access customers, and are they all on the Sage test site?**
- **From git:**
  - CRC01 → **CRC100** (new 18 Nov; in Ethan's test load today);
  - CRL02 → **CUC100**, ISL03 → **INN101**, SSP02 → **SSP101** (new accounts of 27 Oct, loaded in Run 3 / 4).
- **HCL01, HCC01, GOO07:** original accounts matched by name, a list not kept in git. `sql/lookup_customer_codes.sql` (read-only) reads them from `migration.XREF_SAGE_BPC`.
- **Answered from SDILive (`lookup_customer_codes.sql`, 19 Nov; the first run failed with Msg 208 because SSMS was on `master`, so `USE SDILive` was added):**
  - CRC01 → CRC100 (new account, CRC Industries Europe BV; no ledger entries; in Ethan's load today);
  - CRL02 → CUC100 (new account, Cucina IFG);
  - GOO07 → GOO100 (matched by name, Goodfellow & Goodfellow);
  - HCC01 → HUT100 (name, Hutchison Catering);
  - HCL01 → HER100 (name, **Hertfordshire Catering** Ltd; Sue wrote "Hertfordshire College");
  - ISL03 → INN101 (new account, **Innovate Services** Ltd; Sue wrote "Impact Food Group". Cucina's Access name is "Cucina IFG", so check she means ISL03);
  - SSP02 → SSP101 (new account, SSP UK; note SSP100 is also SSP UK).
- **On the test site:** all except CRC100 were in the customer files loaded in Runs 3 / 4 (only the six address-rejected customers failed). CRC100 arrives with today's load.
- **Reply SENT to Sue (cc Selina; James confirmed, 19 Nov):** the 7 codes, all on the test site except CRC100 (in this week's load); SSP UK also has SSP100. The name differences weren't raised: Innovate Services is part of Impact Food Group (as "Cucina IFG"), and Hertfordshire Catering is her "Hertfordshire College". The codes come straight from the cross-reference.
- **Lesson:** when the code lookup is exact, a different trading name isn't a doubt. Only query a user when the code itself doesn't resolve.

**19 Nov – Live Orders: visual dashboard, data contract and integration plan (James: build the visualisation; automate imports / exports; what X3's UI offers; the SDI portal; an AI layer).** Jira SCRUM-329.
- **Data contract:** `build_live_orders.py` now also writes `SDI_Live_Orders_<date>.json` (schema `sdi.live_orders/1`), the board's data as one file. No calculation changed. It holds customer names: `runs/` only, never git.
- **`live_orders_dashboard.html` (new, self-contained, read-only):**
  - KPIs; works orders by due week × RAG; hours by week × shop (Metal / Joinery / Acrylics); hours by work centre;
  - bought-in material demand against supply (short = needed − stock − on PO − on WO);
  - filterable works orders with exploded BOMs.
  - **Data:** choose / drop the .json, or `?data=<url>`, or `window.LIVE_ORDERS_DATA`.
  - **Tested** in Chromium on synthetic data: light and dark mode, no errors, phone width fits.
- **`INTEGRATION_PLAN.md`:**
  - what the X3 UI allows without development (enquiry exports, Requester, export / import templates as **recurring batch-server tasks**, data dictionary, landing pages; REST / GraphQL / SOAP via a connected app, which needs Acuity);
  - stages 1–5: Access → X3 manual exports → scheduled exports → API → AI;
  - the portal (`GET /api/live-orders` + one tile; **built beside the portal, not in its files**, after the 14 Nov estimating break);
  - the AI layer: daily exceptions briefing, plain-English questions, draft POs / reschedules only via approved imports.
- **Self-serve list while Marc is silent (James's Super administrator login on the training site):**
  - read-only enquiries + exports, Requester, data dictionary, templates;
  - training site only, agreed first: the estimating IMPORT test load after Ethan's load, and checking whether Connected applications is visible (look, don't create);
  - Acuity only: production / TEST credentials, user fields, webhooks, Safe X3, licence / rate limits.
- **Email to Matt and Charlotte drafted (19 Nov)** on why SDI needs its own development access:
  - the Access SupplyChain dependency; the AI strategy; business knowledge over platform knowledge; speed and skill;
  - Acuity's non-response and the evidence of what we've built (estimating converter, Live Orders);
  - a proposed split (Acuity own the platform; SDI develop on its own data; TEST first, sign-off, audit);
  - asks: agreement, pressure on Neil (owner and date this week, TEST by 27 Nov), the contract position.
  - **James to send. Not yet confirmed.**

**19 Nov – X3 UI automation built: `sagex3/integration/x3_ui/` (James: automate filtering and exporting data sets through the X3 web UI, for Live Orders, BOMs, routes etc.).**
- **Why UI automation:** no API / batch-server access yet (SCRUM-329). Playwright drives the X3 web screens as a user would: open the function, fill the criteria, Search, Export, save the file to a dated folder.
- **`x3_ui.py`:**
  - `login`: James signs in once, incl. Sage ID / MFA; the session is saved in his profile, **never git**;
  - `record <FUNCTION>`: Playwright's inspector, to capture each screen's selectors once;
  - `export [names]`: runs the data sets, logs to `run_log.json`, takes a screenshot of any failed step and carries on;
  - `list`.
- **Read-only:** any step aimed at Save / Create / Delete / Post / Validate is refused; imports are not automated.
- **`datasets.json`:**
  - Live Orders: so_lines (CONSCSP), po_lines (CONSCPO), works_orders, wo_materials, wo_operations, stock (codes to confirm);
  - master data: products, boms, routes, customers, suppliers, via Exports templates exported to the client;
  - reports (off): CONSSMJ, CONSCSF, CONSCPS.
  - The X3 address pattern is to confirm on first login.
- **Tested 19 Nov against a mock screen in Chromium:** fill + relative dates, untick, search, wait, download saved, Save refused. **Not yet run against X3:** X3 isn't reachable from the cloud session, so it runs on James's PC.
- **Next:**
  1. James confirms the address pattern, captures so_lines and po_lines, runs them, and sends the files;
  2. write the X3 source adapter (X3 export layouts → the SOH / POH / SMR / WOR grids `build_live_orders.py` reads), so the board and dashboard run on X3 data;
  3. switch to the API when Acuity grant it.
- Can be scheduled daily with Windows Task Scheduler.

**19 Nov – SQL files NOT in git, lost with the old machine (`*.sql` is git-ignored unless force-added):**
- `sagex3/production/live_orders/live_orders.sql`: the Live Orders extract.
  - **Fallback:** `rebuild/sql/extract_transactions.sql` has the same grids (CHECK, WOR, SOH, POH, SMR) and the engine reads its output (README section 3).
  - **James to send his copy** (it was in `SDI_Live_Orders_python.zip`, 16 Nov) to commit.
- `partner_revenue.sql`, `_2`, `_3`, `quantity_rebates_sales.sql`: finance rebate queries. They were kept in the private finance folder, also lost. James may hold copies from running them. Re-create on request; **finance-only, never in git**.
- `xref_sage_codes.sql`: generated by design from `xref_sage_codes_TEMPLATE.sql` + `make_xref_inserts.py` (names stay out of git). Not a loss.
- **Rule:** every new non-private `.sql` is committed with `git add -f` in the same commit that first uses it. Check: `comm` of the `.sql` names in the runbook against `git ls-files "*.sql"`.


**20 Nov – Live Orders on X3 without Acuity: what happened with the browser route, and the API route built (James: "WE NEED THE ENTIRE SOLUTION TODAY"; "we are waiting for no one").**
- **The browser route (`x3_ui.py`) is blocked by the Sage ID check:**
  - a new browser is asked for Sage ID / MFA every time;
  - James's Sage Verify app (Pixel 9a) shows no code or prompt, while his everyday Edge is never asked.
- **`use-browser` (run X3 on a copy of the everyday Edge profile) failed:**
  - the copy needs Edge closed. I told James to run `Stop-Process -Name msedge`, which also closed this chat (it runs in Edge). **Mistake: never kill all Edge processes.**
  - Even when copied, Edge's sign-in cookies are tied to the original profile, so a copy isn't trusted. Dropped.
- **What James found as Super administrator on the training site (looked only, nothing created):**
  - Administration → Authentication → **Connected applications**: only "Sage Cloud Manager" (Sage's own, user cloudmanager: **leave alone**); "New connected application" is available;
  - Administration → Endpoints → **Sage X3 Services**: `x3-services_X3ERPV12` exists, so the GraphQL API is there.
- **Sage's documentation isn't readable from the cloud session:**
  - developer.sage.com blocks automated requests (Cloudflare), and the online help now redirects there;
  - the network allowlist was widened (developer.sage.com, online-help.sageerpx3.com, online-help.sagex3.com), but it didn't help.
  - Confirmed from public sources only: client ID + secret (shown once); an HS256 JWT signed with the secret (iss = client ID, iat / exp within the app's token validity, aud = the endpoint per a Sage community post); a Bearer header plus `x-xtrem-endpoint`; GraphQL at `/xtrem/api`; REST at `api1/x3/erp/<folder>/<class>?representation=<rep>.$query` with `$next` paging.
  - **So the client finds the exact URL / token form on the site itself (`probe`); nothing is assumed.**
- **Built and pushed (all read-only towards X3):**
  - `sagex3/integration/x3_api/x3_api.py` + README:
    - `setup` (secret typed hidden, saved in `%USERPROFILE%\.sdi\x3_api.json`, **never git / email**);
    - `probe` (tries 4 URLs × 3 audiences × with / without the endpoint header; saves the one X3 accepts; otherwise prints X3's answers, no secret);
    - `schema`, `draft` (writes `api_datasets.draft.json` from the schema, with sales / PO lines exploded);
    - `pull` (paged; writes `<name>.csv` / `.json` under `%USERPROFILE%\SDI_X3_exports\<date>`, same names as the screen exports);
    - `rest`, `query`. Mutations refused; GET only for REST.
  - `sagex3/production/live_orders/x3_source.py` + `x3_columns.json` (**force-added: `*.json` is git-ignored**). The X3 data sets (csv / xlsx / json) → the WOR / SOH / POH / SMR extract the engine reads:
    - open qty = ordered − delivered / received;
    - `dd/mm/yy` and ISO dates handled; stock status A only;
    - `--check` shows which X3 column fed each field. **The map is PROVISIONAL** until the first real pull.
  - `build_live_orders.py`: products can also come from an X3 products export (.csv / .json).
  - `run_x3.py`: pull (api / ui) → adapter → engine → `%USERPROFILE%\SDI_X3_runs\latest.json` + `status.json`. Keeps 60 runs; exit 0/1 for Task Scheduler.
  - `sdi-intelligence-backend/live_orders_routes.py`: `GET /api/live-orders/latest` and `/status` (X-SDI-Key), `/dashboard` (no data in it). Mounted with two lines in `app.py`: **James's change, when ready.**
  - `live_orders_dashboard.html`: opened as `/api/live-orders/dashboard#key=<key>`, it loads `/latest` with the key. The key after `#` never reaches the server and is removed from the address bar.
- **Tested 20 Nov against a mock X3** (checks the JWT signature / claims and the endpoint header; pages its data):
  - probe found the form, then schema, draft, pull with paging and line explode, and the mutation refused;
  - the adapter took a UI-style CSV (`;`, `dd/mm/yy`, "1,200") and API JSON, and dropped Q stock;
  - the engine built 5 WOs (RAG 1 / 2 / 2); the portal answered 401 without the key and 200 with it;
  - the dashboard loaded through the portal with no errors.
  - **Not yet tested against the real site.**
- **James's next steps (training site):**
  1. create the connected application (README §1: `SDI Live Orders read-only`, token 600 s, about 3 months);
  2. `setup`, `probe`, `schema`: send Claude the output (no secret in it);
  3. `draft` → `api_datasets.json` → `pull`;
  4. `x3_source.py --check`, then fix the column map;
  5. `run_x3.py`;
  6. mount the router, add the portal tile.
- **Rules learnt today:**
  - never kill all Edge processes;
  - a copied browser profile does not carry the Sage sign-in;
  - the connected application's **secret goes only into `setup`** (never chat, email, screenshots);
  - the API user should have enquiry-only rights before production;
  - "Sage Cloud Manager" is never touched.

**20 Nov – RECIPE: re-create the X3 API access after an environment clear-down (James: "we will lose these settings when they clear down the environment").**

Keep this up to date with every setting we choose. **Never write the secret here:** after a clear-down a new one is generated anyway.

- **Site / folder:** `https://sdi-displays-trn.uk.sagex3.com`, solution X3ERPV12, folder **SDIMIG**. James's role is Super administrator.
- **Already on the site (Sage's, never touch):**
  - Connected application "Sage Cloud Manager" (user cloudmanager);
  - Sage X3 Services endpoint `x3-services_X3ERPV12`. It has its own Sage client ID and an internal URL (`…svc.cluster.local:8240`), so it's reached through the public site.
- **Connected application** (Administration → Administration → Authentication → Connected applications → New):

  | Field | Value | Why |
  |---|---|---|
  | Name ✱ | `SDI Live Orders read-only` | |
  | Url ✱ | `http://localhost:8071` | descriptive only: the SDI Intelligence portal that calls X3 |
  | Active | ticked | |
  | Client ID | generated by X3 on Save | copied into `x3_api.py setup` (it isn't a secret, but it changes on re-creation) |
  | Tokens validity ✱ | `300` (seconds) | default; `setup` token lifetime 300 matches |
  | X3 Connector | **blank** | the "Sage X3 Connectors" list is empty on our site (20 Nov); not required |
  | Allowed user | **SDIJG** (James's own login; SDI logins are SDI + initials; found by filtering the Users pop-up on Gray) for training only | **before production: an enquiry-only user** |
  | Secret | shown once on Save → straight into `setup` | never chat / email / screenshot / git; "Regenerate secret" on the form if lost |

  The form also has a "Tokens currently valid" tab (Token ID, Issued at, Expires in, Subject), so the client sends a `jti` token ID.
- **On the PC** (`C:\SDI_X3\SDI_X3\integration\x3_api`):
  1. `python x3_api.py setup`. The answers:
     - site as above; folder SDIMIG; endpoint = the Administration → Endpoints row for folder SDIMIG (to record here once seen);
     - connector: Enter;
     - client ID from the form; X3 user = the Allowed user's login; secret pasted, hidden.
  2. Then `probe` → `schema` → `draft` → `api_datasets.json` → `pull`. Saved privately in `%USERPROFILE%\.sdi\x3_api.json`.
- **Endpoints (Administration → Administration → Endpoints, 20 Nov):** `syracuse`; **`X3ERPV12_SDIMIG`** (folder SDIMIG); `X3ERPV12_SEED`; `X3ERPV12_X3`; `X3ERPV12_ACUX3` ("We are SDI", folder ACUX3, the only one with Use Sage AI ticked: **leave alone**). The X3 Service and X3 Connector columns are blank on every row. **In `setup`, the endpoint is `X3ERPV12_SDIMIG`.**
- **SIGN-IN THAT WORKS (20 Nov, `claims` test on training): GraphQL `POST /xtrem/api` → `200 {"data":{"__typename":"RootQueryType"}}`.**
  - Header `Authorization: Bearer <JWT>` plus `x-xtrem-endpoint: X3ERPV12_SDIMIG`.
  - JWT HS256 signed with the secret. Claims:
    - `iss` = client ID;
    - `sub` = the allowed user (SDIJG): unknown or missing gives **Error 42**;
    - **`aud` present but EMPTY (`""`)**: the endpoint name or no aud gives **Error 45**;
    - `iat` / `exp` in **seconds**: milliseconds gives **Error 21**.
  - With the wrong endpoint name (`SDIMIG`), every JWT got *"Cannot read properties of null (reading 'info')"*.
  - **Seen:** once one token had worked, later tokens in the same run were let through even when expired or without `iss`. X3 seems to keep the sign-in open briefly. Not relied on.
  - REST `/api1/x3/erp/SDIMIG/...` with an endpoint-named aud gave Error 45; to re-test with the empty aud.
  - `x3_api.py` now defaults to the empty aud, and `probe` tries it first.
  - **CORRECTION (20 Nov, after the clone):** `probe` still got *"reading 'info'"* even with the empty aud. The only difference from the `claims` test that got in: **`probe` sent a `jti` (token ID)**, added after seeing the "Tokens currently valid" grid.
    - With a `jti`, X3 looks the token up in its own issued-token list and finds nothing. **`jti` removed. Never send one.**
    - So the *"info"* error came from the `jti`, not (only) the endpoint name. The endpoint `X3ERPV12_SDIMIG` and the empty aud are what the next check needs.
  - **First run from the clone (`C:\SDI_X3\repo`):** clone OK (3,610 objects); old copies moved to `C:\SDI_X3\_old`.
  - **Error 27 (`schema`, 20 Nov):** the token's whole life (`exp` − `iat`) was 330 s, more than the app's 300 s Tokens validity. The `claims` tokens that got in lived 270 s. **Fix: life = token validity − 30 s.** Error codes seen: 21 = timestamps in milliseconds; 27 = lifetime over the validity; 42 = unknown or missing `sub`; 45 = wrong or missing `aud`.
- **Lesson (20 Nov):** a copy command run from `PS C:\ClaudeVision>` put a stray `x3_api.py` in James's estimating folder. **Always `cd C:\SDI_X3\SDI_X3\integration\x3_api` first, and check the prompt before any copy.** Never put files in `C:\ClaudeVision`. The stray file is removed only after checking it's today's.
- **20 Nov – SIGNED IN AND THE SCHEMA READ.** `probe`: `GraphQL OK … /xtrem/api (aud=empty, endpoint header=yes)`. `schema`: **13,095 types**.
  - **Nodes for Live Orders (pinned in `x3_api.py` NODES):**
    - `x3Manufacturing.workOrder` and `.workOrderProductLine`, `.workOrderMaterialLine`, `.workOrderOperationLine`;
    - `x3StockData.stock`;
    - `x3Sales.salesOrderLine`;
    - `x3Purchasing.purchaseOrderLine`;
    - `x3MasterData.product`;
    - `x3ManufacturingData.manufacturingBomLine` and `.workCenter`;
    - `x3Manufacturing.routingOperation`.
  - **Also there:** stockJournal, allocation, workOrderSuggestion, purchaseOrderQuantityLine, salesDelivery, invoices, finance, etc.
  - **REST:** `/api1/x3/erp/SDIMIG/...` gives *"Endpoint not found: … dataset SDIMIG"*, so REST wants the endpoint name in the path. Not needed: GraphQL works.
  - **Next:** `draft` (writes `api_datasets.json` from the pinned nodes, Live Orders sets enabled), then `pull --limit 3` (a trial into `SDI_X3_samples`, prints **column names only**), then the column map.
- **20 Nov – first trial pull on training (`pull --limit 3`).**
  - **Field counts:** workOrder 67, workOrderProductLine 62, workOrderMaterialLine 67, workOrderOperationLine 109, stock 50, salesOrderLine 159, purchaseOrderLine 182, product 152, manufacturingBomLine 40, routingOperation 60, workCenter 34.
  - **Data:** **SO and PO lines came back (3 each); works orders, materials and stock gave 0 rows.** SDIMIG holds the migration's master data; open WOs and stock arrive at the go-live run.
  - **`x3_columns.json` mapped to the real names:**
    - **SO:** salesSite.code, salesOrder.id, soldToCustomer._id, orderDate, requestedDeliveryDate, shippingSite.code, lineNumber, product.code, productDescriptionInUserLanguage, salesUnit.code, quantityInSalesUnitOrdered − quantityInSalesUnitDelivered, grossPrice.
    - **PO:** purchaseSite.code, purchaseOrder.id, orderFromSupplier._id, orderDate, lineNumber, product.code, receiptSite.code, purchaseUnit.code, **remainingQuantityToReceiveInPurchaseUnit** (net, used alone), expectedReceiptDate, grossPrice, currency.code; **`isClosed` lines dropped**.
  - **Tested** on X3-shaped mock rows.
  - **WO / stock column names:** a trial against Sage's demo folder **SEED** (`pull --limit 3 --endpoint X3ERPV12_SEED`). `--endpoint` is refused without `--limit`, and the output goes to `SDI_X3_samples\<date>_<endpoint>`, never the exports. Read-only.
- **20 Nov – SO/PO mapping confirmed on the real sample** (`x3_source.py --check`): all fields found, 3/3 rows kept each. Only SO `CUSORDREF` and `CUR` are not on the line (they're header-level).
  - **SEED trial refused:** *"User does not exist for X3 user SDIJG"* (no X3 user for SDIJG in Sage's demo folder). **Not pursued:** creating a user there is an admin change.
  - **Instead, `x3_api.py columns`** prints the WO / stock column names from the saved schema (`api_datasets.json`), with no call to X3.
  - **Fixed:** `pull` crashed writing `api_log.json` when every data set failed (folder not created).
- **20 Nov – works orders and stock mapped** (names from `x3_api.py columns`, i.e. the training schema).
  - **WOR from `x3Manufacturing.workOrderProductLine`** (`wo_products`). It's used instead of the `workOrder` header when both exist. Fields:
    - works order: workOrder.number; product: product.code; version: majorProductVersion.code;
    - for: salesOrder, customer.code; status: workOrderStatus;
    - quantities: expectedQuantity, totalCompletedQuantity, actualRejectedQuantity;
    - dates: _createStamp, startDate, endDate.
  - **SMR from `x3StockData.stock`:** stockSite.code, product._id, quantityInStockUnit, lot, location.code, status.code (A only).
  - **Tested end to end** (adapter → engine) on X3-shaped mock rows: 1 WO, AMBER, as worked by hand.
  - **For later:** `workOrderMaterialLine` carries X3's own requiredQuantity / allocatedQuantity / shortageQuantity. Once WOs exist in X3, the board's material status can come from X3's allocations instead of its own sharing-out.
- **20 Nov – INCIDENT: the first full pull knocked over X3 Services on training.**
  - The SO request got *"socket hang up"*, then the PO request got *"connect ECONNREFUSED 10.62.127.172:8240"* (the internal X3 Services / GraphQL service).
  - **Cause (ours):** each request asked for **200 rows × 159–182 fields** with their linked records.
  - **Checks given to James:** the X3 screens (separate service; should be fine); `probe` again in 5 min; if still refused after ~15 min, tell Acuity (Ethan shares the site).
  - **Fix:**
    - **`LEAN` field lists**: only what the board uses, 4–17 fields per data set (`draft --all` gives every field, for exploring with `--limit` only);
    - **50 rows per page**, a 1 s pause between pages;
    - **back-off** on 5xx or connection errors (15 / 45 / 120 s), then that data set is given up.
  - **Rule:** never pull every field in bulk; trials only, with `--limit`.
- **Master data from X3:**
  - **products** (code, productCategory.code, localizedDescription1–3) and **BOMs** (parentProduct.code, componentProduct.code, linkQuantity; lines whose validity has ended are skipped) are now read from the API pull;
  - `run_x3.py` takes them from the same pull by default; both are in the default pull.
  - **Routings:** still the route load file, until real `routingOperation` rows show X3's time units (setupTime / runTime / rate / baseQuantity / managementUnit / runTimeType). A `pull routes --limit 3` trial will show them; routing data names no customers.
- **Results to fill in as we find them:**
  - the endpoint name;
  - the GraphQL path / audience / header `probe` accepted;
  - whether REST works with the same token;
  - the node paths `schema` shows for works orders, materials, operations, stock, SO / PO lines, products, BOMs and routes;
  - the column-map corrections.

  (`api_datasets.json` and `x3_columns.json` are committed, so they survive a clear-down.)
- **After a clear-down:**
  1. re-create the connected application from the table;
  2. `setup` with the new client ID and secret;
  3. `probe`.

  Nothing else changes.
- **20 Nov – first real run on the training site.**
  - The connected application was saved and the secret regenerated (no tokens existed). **Client ID recorded in James's private settings, not here** (it changes on re-creation).
  - `setup` answers: site / folder / endpoint / connector all defaults (`SDIMIG`, `x3-services_X3ERPV12`); user **SDIJG**; token 300.
  - **`probe` result:**
    - `/xtrem/api` and `/xtrem/graphql` **exist** (401); `/api` and `/graphql` don't (404); REST `/api1/x3/erp/SDIMIG/...` also 401.
    - Every 401 says *"Cannot read properties of null (reading 'info')"*, whatever the audience or header.
    - **Reading:** X3 looks the bearer token up in its own list of issued tokens (the connected application's "Tokens currently valid" grid, last column "Information") and finds nothing. Our self-signed JWT must first be **exchanged for an X3-issued access token**.
  - **Added `x3_api.py diagnose`.** It shows how X3 answers no sign-in / junk / wrong secret / unknown client / our JWT. It then tries the token-exchange addresses (`/auth/oauth2/token`, `/oauth2/token`, `/auth/token`, …) in four forms (JWT bearer assertion, client credentials as form / Basic / JSON). On success it saves `token_url` + `token_mode`, and every command then exchanges and caches the access token automatically.
  - Tokens and secrets are hidden in all output. Tested against a mock with an exchange.
- **Lessons for James's PowerShell steps:**
  - give **one command per box**: pasting whole instructions ran `edit` / `help`;
  - **"Enter" = accept the [bracketed] answer**;
  - a prompt can show a wrong answer from an earlier try: the typed answer replaces it;
  - right-click pastes in PowerShell, and nothing shows for the secret.

**20 Nov – Ian Knight's request (19 Nov): every part one customer has ordered over 3 years, and the ones they've stopped ordering.**
- **Query:** `sagex3/reports/customer_parts_history.sql` (read-only, SDILive, force-added).
  - The committed copy has the placeholder `XXXXX`; James's copy has the account code set (scratchpad). **The code and name are not in git.**
  - Grids:
    - **CHECK:** lines, parts, earliest / latest dates found;
    - **SUMMARY:** one row per part; first / last ordered; lines / qty in the 2 years before against the last 12 months; status STOPPED / NEW / Still ordering; STOPPED first;
    - **DETAIL:** every order line, sorted by part, description, date.
- **Source:** order lines from `COR_TBL` (as the rebate report), descriptions from `PMA_TBL` (TOP 1 per part).
  - Assumes `COR_CUSTOMER_CODE` / `COR_ORDER_STATUS` exist on `COR_TBL` as on `ASC_COR_TBL`. **If Msg 207, switch the FROM to `ASC_COR_TBL`.**
  - If CHECK's earliest date is well after 3 years ago, older lines may be elsewhere.
- **Status:** query sent to James. Reply to Ian drafted in chat (James to send). Results go to Ian only; never in git.
- **First run (20 Nov):** 1,445 order lines, 330 parts, earliest 24 Nov 2023 (the full 3 years); 119 STOPPED.
  - Many "stopped" parts were the same item re-coded and still ordered (prefix BOT- / SRS- / SRS02- added or dropped, ` OS` suffix).
  - **v2 summary:** a `core` code (customer prefix and OS / CO / CH suffix removed) gives the statuses RE-CODED (with `similar_code_still_ordered`), STOPPED, NEW, Still ordering, and Not a product (carriage, rework, installation, respray, etc.).
  - Checked on the run's codes: **102 truly stopped, 16 re-coded, 1 not a product.** v2 sent to James to re-run.
- **v2 run (20 Nov):** matches the check exactly: STOPPED 102, RE-CODED 16, Still ordering / NEW 202, Not a product 10 (= 330).
  - The largest "stopped" quantities are one-off June 2024 bulk orders (a fit-out), not lost repeat lines.
  - One negative line (a correction, 18 Nov).
  - The workbook (Summary + Detail tabs) is to be built by James from the SSMS grids. Email drafted; **not yet sent**.
- **Workbook built (20 Nov)** from the pasted v2 grids, taken from the session transcript so nothing was retyped. Checked: 330 / 1,445 rows.
  - **Tabs:** Read me (counts and definitions), Summary (colour-coded status, filters), Detail (adds qty outstanding).
  - **Status split:** STOPPED 102, RE-CODED 16, Still ordering 57, NEW 145, Not a product 10.
  - Scratchpad only, never git: it names the customer. Final email drafted in chat. **SENT to Ian by James (20 Nov). Done.**
- **20 Nov – `diagnose` on training (after copying the new `x3_api.py` from the zip view into the real folder).** The findings:
  - **No sign-in:** 401 Basic realm=Syracuse.
  - **Junk bearer:** *"Oauth2 Bearer authentication – No 'oauth2' or 'sageId2' in http query"*, so non-JWT bearers go to the OAuth2-server route.
  - **Any JWT** (wrong secret, unknown client ID, or ours): the same *"Cannot read properties of null (reading 'info')"*. So JWTs are taken as connected-app tokens, but **a lookup fails before the client or secret is checked**.
  - **Token-exchange URLs** (`/auth/oauth2/token`, `/oauth2/token`, `/auth/token`, `/xtrem/token`, …): none exist (404, "bad url", or a login redirect). There's no exchange: the self-signed JWT is sent directly.
  - **Leading suspect:** the endpoint name. We sent `SDIMIG` as `x-xtrem-endpoint` and `aud` (a guess). **Next:** James screenshots Administration → Endpoints (name + folder); then set `endpoint` and re-run `probe`.
  - Second suspect: the connected application's blank X3 Connector (the Sage X3 Connectors list was empty).
  - **Lesson:** the browser download went into the zip view in Explorer, not the real folder. Copy files into `C:\SDI_X3\SDI_X3\...` and check with `python x3_api.py -h`.

**RULE (James, 20 Nov): NO MORE ZIPS.** "It's horrible tech."
- **Why:** three zips, two "-old" folders, a download saved into a zip view, and `x3_api (1)` copies caused today's wrong-file and wrong-folder slips.
- **From now on:** James's PC has one linked copy of the project at **`C:\SDI_X3\repo`** (`git clone --branch claude/eloquent-babbage-o9etz3 --single-branch https://github.com/jbgray1874/claudevision.git repo`).
- **To update after Claude pushes:** `cd C:\SDI_X3\repo; git pull`.
- **Work folders:** `C:\SDI_X3\repo\sagex3\integration\x3_api`, `...\sagex3\production\live_orders`, and `C:\SDI_X3\repo\sdi-intelligence-backend` (portal files there are for reference; James's live portal is unchanged).
- **It never touches `C:\ClaudeVision`:** it's a separate folder and clone. The 14 Nov breakage was a checkout *inside* `C:\ClaudeVision`.
- **Old copies are moved, not deleted:** `C:\SDI_X3\_old` (SDI_X3, SDI_X3-old, SDI_X3-old2, the zips).
- **Unaffected:** settings (`%USERPROFILE%\.sdi\x3_api.json`, the X3 secret) and data (`SDI_X3_exports`, `SDI_X3_runs`) live outside the repo.
- **Claude:** push before saying "updated"; no zips; no file-by-file downloads for code. Private outputs (customer workbooks etc.) are still sent as files, never committed.

**20 Nov – Live Orders in the SDI Intelligence portal (James: "we will build in the SDI Intelligence portal").**
- **RULE (James):** no approach to Acuity about the API or the portal ("they have their own developers"). We build it ourselves.
  - **Production:** James will have admin on the live site too, so the connected application is set up there by us, with the same recipe (above).
  - Before go-live: an enquiry-only API user instead of SDIJG.
- **Installer:** `sdi-intelligence-backend/add_live_orders_to_portal.py`.
  - **Default:** a preview that changes nothing. `--apply` backs up (`.bak-<stamp>`) and then only adds:
    - the router and dashboard files next to `app.py`;
    - 3 lines in `app.py` after the HR router;
    - a "Live Orders" menu item (Overview group), its page (the dashboard in a frame, given the portal key after `#`) and its label;
    - `LIVE_ORDERS_RUNS=<full path>` in `.env` (the service runs as a system account, so `~` would be wrong).
  - Re-running does nothing.
  - **Live service folder:** `C:\ClaudeVision\sdi-intelligence-backend` (NSSM service SDIIntelligence). Restart the service after `--apply`.
- **Tested on a copy of the portal:**
  - preview / apply / re-run; the real `app.py` serves the page with the menu item;
  - `/api/live-orders/latest`: 401 without the key, 200 with it; dashboard 200; the HR endpoints still answer;
  - in a browser, clicking "Live Orders" shows the dashboard inside the portal, with no errors.
- **SECURITY (found while testing, not caused by this work):** `sdi-intelligence-backend/.env` **is committed to git** (on `main` and this branch; commit 7cad363 "Complete sync"). It holds the SDILive SQL login and the BrightHR client secret. The portal page also has the portal API key written into it.
  - **Recommended to James:** (1) change the SQL password and the BrightHR client secret, putting the new values in the live `.env` only; (2) stop tracking `.env`, done with care, because untracking it carelessly could delete the live `.env` on a later pull in `C:\ClaudeVision`. **Awaiting James.** Values are never written here.
- **Where the Live Orders requirements are recorded:**
  - section 20 (LO-00..05 analysis); 22.11 (board built, SCRUM-241 / 245–249); 22.13 (first live run);
  - 22.20 (Dave's sheet re-analysed: his "game changer" notes); 22.23 (Dave's 26 Oct request and the Monday copy-over); 22.26 (focus on X3);
  - `sagex3/production/live_orders/README.md` and `INTEGRATION_PLAN.md`; the docstring in `build_live_orders.py`.
  - The 12 questions to Rachael and Liz (13 Nov) were due today (Fri 20 Nov).

**20 Nov – Live Orders workbook, Production's folder, history and Regenerate (James: a spreadsheet "like Access's but super flash", editable; the portal sits on top of `K:\Operations\Reporting\LiveOrders`; every generation kept; regenerate from the portal; the whole history viewable).**
- **Requirements re-confirmed from James's 17 Nov email to Acuity.** The screens: 2a Live Orders, 2b Work-centre load, 2c WO Suggestions, 2e Exploded BOM; notes that stay with the WO; REV red against the GA drawing; print, Excel and refresh. Files received again (Dave's sheet, the 13 Nov board xlsx / html, the reconciliation workbook); kept outside git (they name customers).
- **`live_orders_xlsx.py` – the workbook:**
  - same tabs and column names as Dave's sheet, plus a Dashboard;
  - **Dashboard:** KPI tiles and native Excel charts (WOs by due week × status; hours by work centre); the chart figures sit on a hidden sheet; prints on one page;
  - **Live Orders:**
    - totals row on SUBTOTAL, so it follows the filter;
    - status colours by conditional formatting, so they follow edits;
    - overdue due dates red; customer date before due date shaded;
    - heat-mapped work-centre hours; balance data bars; Dave's weekly break lines;
    - ● M / J / A shop markers; part code → its Exploded BOM;
    - ✎ yellow editable columns (Comments, Prog, Tube req, material note);
    - detail columns fold away; A3 landscape, one page wide, headings repeated;
  - **Work-centre load:** heat map, totals, a stacked chart by week;
  - **WO Suggestions:** red rows for no BOM / no route; late starts red;
  - **Exploded BOMs:** foldable per WO; indented by level; short bought-in parts red; link back to Live Orders; cost totals.
  - `read_carry` finds the heading row (banner rows sit above it) and strips the ✎.
- **`run_x3.py`:**
  - **publishes every run as a new pair** `SDI_Live_Orders_<date>_<HHMM>.xlsx + .json` to `LIVE_ORDERS_SHARE` (default `\\sdi-dc01\shareddata$\Shared\Operations\Reporting\LiveOrders`, which is K:); **never overwrites: the folder is the history**;
  - carries notes from the **latest generated** workbook (by name, so opening an old one doesn't change which is carried);
  - `--pull api` pulls transactions every run and products / BOMs only if older than 24 h (`--master-hours`, `--full`).
- **Portal (`live_orders_routes.py`):** `/latest`, `/history`, `/run/{name}`, `/workbook/{name}`, `POST /regenerate` (one at a time, a background run, log in `regenerate.log`), `/regenerate` (status), `/status`.
  - File names are checked against a pattern, so only our own files can be served.
- **Dashboard page (in the portal):**
  - a **↻ Regenerate** button with progress;
  - a **Workbooks** history table: generated, counts, notes carried, View / Workbook ⬇ / Copy path (K: path);
  - **View** switches the page to that run;
  - **fixed:** the "hours by week and shop" chart was always empty (shop names sent as Metal / Joinery / Acrylics, compared with M / J / A).
- **Installer** now sets in `.env` (only the missing ones): `LIVE_ORDERS_RUNS / SHARE / SHARE_USER / HOME / ROUTES / PYTHON`, `X3_API_CONFIG`, `X3_EXPORT_DIR`. All are full paths: the service runs as a system account.
- **Tested (fake data):**
  - 300 WOs; round trip: Production typed notes → the next run carried 2 → the edited workbook untouched;
  - in a browser on a patched portal copy: Regenerate ×2 → 2 pairs saved, history shows both, View of the older run, no errors;
  - workbook rendered with LibreOffice and checked.
- **To check on the real set-up:**
  1. **the service account must be able to write** to `\\sdi-dc01\…\LiveOrders`. A Windows service reaches the network as the PC's computer account. If Regenerate fails with access denied, give that account write on the folder, or run the service as a domain user;
  2. the route file path (`LIVE_ORDERS_ROUTES`), until X3 routings are mapped (the routes.csv values are still awaited).

#### 20 Nov (late) – Live Orders page glammed up: eight views (James: "glam up the site … lots of views of the data")
- **`live_orders_dashboard.html` rewritten as tabs.** Same data file, same portal endpoints, still read-only (apart from Regenerate), no libraries, light and dark:
  | Tab | What it shows |
  |---|---|
  | **Overview** | Headline tiles (count up), red / amber / green ring, WOs by due week, hours by week × shop, busiest work centres, top 10 shortages, not-green WOs due in the next 14 days |
  | **Live Orders** | Production's grid: filters for status / shop / week (incl. overdue) / top level, search (part, WO, SO, account, description), Production's notes (Comments, Prog, Tube), click a row for the exploded BOM, Export CSV |
  | **Work-centre load** | Heat map: work centre × week, busiest first, filter by shop, totals |
  | **Shortages** | Every bought-in component (all BOM levels): short, needed, stock, on PO, next PO, on WO, WOs held up, first WO due. Purchasing's list, Export CSV |
  | **WO Suggestions** | Uncovered SO lines for made parts; no-BOM / no-route rows red; late starts red |
  | **Customers** | WOs per account by status, overdue, hours, next due; click an account to filter Live Orders |
  | **Trends** | Red / amber / green and hours across every saved generation (portal only; needs 2+) |
  | **Workbooks** | The history table (View / Workbook ⬇ / Copy path), portal only |
- **Data contract additions** (`build_live_orders.py`, schema unchanged `sdi.live_orders/1`, additive): per WO `pa` (parent), `dr` (drawing), `cat`, `n` (Production's notes carried from the workbook); per suggestion: start date, shops, SO qty, drawing.
- **Fixed:** the Live Orders shop filter never matched (shops are sent as words, the filter used M / J / A). Lesson, again: **compare shop families by first letter everywhere** (`charAt(0)`).
- **Fixed in dark mode:** text on the yellow tiles; charts redraw when the theme changes (their colours are read at draw time).
- **Tested (fake data, 300 WOs):** every tab standalone and in the portal (local FastAPI with the real routes file, 3 saved runs): Trends, Workbooks, View an older run → "viewing … back to latest", shop filter 150 Metal of 300, phone width (390 px) no sideways scroll, no script errors.
- **To get it on the portal:** `git pull` in `C:\SDI_X3\repo`, then run the installer with the real route file and `--apply` (it copies the new page and routes, backs up first), then restart SDIIntelligence.

#### 20 Nov (late) – Routings now come straight from Sage X3; installer applied on the portal PC
- **James applied the installer** (backups `*.bak-20261120-163620`). **Mistake:** the placeholder `C:\...\the file it found.txt` went in as `--routes-file`, so `.env` got `LIVE_ORDERS_ROUTES=C:\...\the file it found.txt`. The search had only found `MS-0359869_ZSDIROU2.txt` (an estimating import file, one GA) and estimating walkthroughs: **not** a route file for Live Orders.
  - **Lesson: never paste a command with a placeholder in it.** Give the exact command or none. Before `--apply`, read the preview line by line.
- **James's point: Live Orders comes from the database, not from estimating spreadsheets.** Agreed, and the route file is no longer needed: his `routes.csv` sample (x3Manufacturing.routingOperation) holds the same numbers the ZSDIROU2 load put into X3. Example: op 5, LABOUR, JLAB001, setup 0, run 60, proportional, base qty 1, timeFor1.
  - **`build_live_orders.read_x3_routes`:** minutes, as the load file. proportional → run ÷ baseQuantity per unit; managementUnit `rate` → 60 ÷ rate; fixed → counted once like a setup; alternateIndex 0 only; routing code 10 preferred.
  - **Tested:** the 600-operation test route file converted to the X3 shape → identical routes for all 200 parts, and the same 1,748.1 hours end to end.
  - **`run_x3.py`:** `--routes` is optional; default `routes.json` from the pull. Routes are master data, pulled once a day with products and BOMs (`MASTER = products, boms, routes`). `x3_api.py`: routes is a Live Orders data set.
  - **Portal (`live_orders_routes.py`):** Regenerate no longer needs `LIVE_ORDERS_ROUTES`; it is used only if the file exists.
  - **Installer:** comments out any `LIVE_ORDERS_ROUTES` line whose file isn't there ("file not found - X3 routings used"). So re-running it fixes James's `.env`. Tested on a portal copy.
- **Dave's 26 Oct email re-read** (Live Orders tab 1, WO Suggestions tab 2, BOM Report tab 3; "link this to SAGE as a live document, so all the manual work is taken away"). All three are built from X3, with notes carried so Rachael doesn't copy them each Monday. His sheet (uploaded again) stays out of git: it names customers.
- **Reconciliation status (asked by James):** reconciled on 16 Nov, but against **Access** (Dave's sheet vs the 4 Nov extract: part and qty 102/102, balance and SO 98/102, due 76/102, hours 297/334 lines). **Not yet reconciled: the X3 build against Dave's sheet.** The training company has no WOs or stock loaded (pull returned 0), so it can't be done until the WOs are in X3. Then: run `reconcile_dave.py` on the X3 build, with the same tabs.
- **James's ruling (20 Nov):** "The reconciliation against Access SupplyChain gives us the logic that we need for Sage; that's the only thing we need to know." **No separate X3-vs-Dave reconciliation is needed.** The X3 build uses the logic proven against Access (16 Nov). The open item above is closed.
- **Installer re-run on the portal PC** (preview read first, then `--apply`; backups `*.bak-20261120-164905`): new page and routes copied, the placeholder `LIVE_ORDERS_ROUTES` commented out, SDIIntelligence restarted. Next: **Regenerate** in the portal (the first run pulls routings for every product, so it is slower).

#### 20 Nov (late) – Live Orders in the portal: first look on James's PC, and where the portal really runs
- **The menu item and page appear, but the frame is empty.** `http://localhost:8071/api/live-orders/dashboard` returns FastAPI's own `{"detail":"Not Found"}`, so the **running** portal has no Live Orders routes (our endpoint's own 404 says "Dashboard page not found …"). The page HTML is read from disk on every request, so the menu shows; the routes need app.py to be re-imported.
  - Suspects: (a) an older portal process still holds port 8071, so the restarted service can't bind; (b) the service's `.venv` Python fails importing `live_orders_routes` (see `C:\ClaudeVision\output\logs\sdi_service_error.log`); (c) app.py on the PC differs from git (mount after `uvicorn.run`).
  - Checks: the error log tail; who listens on 8071 (process path and start time); `Select-String app.py -Pattern "live_orders|__main__"`.
  - **Lesson:** the portal frame shows a JSON error as white on white (Edge's JSON viewer in dark mode, frame background #fff). Open the frame's URL in its own tab to read it.
- **Network facts (James, 20 Nov):**
  - James's PC is 192.168.11.2 (VPN "Ethernet 4") / 192.168.0.227, **not 10.0.16.151**;
  - the hosts entry `sdi-intelligence.sdi.local → 10.0.16.151` (Intune script `SDI-Intelligence-HostsEntry.ps1`) **times out**, so nobody reaches the portal by that name today;
  - **SDI-APP01 (10.0.0.5) answers on port 8071**: something (probably a copy of the portal, as the old portal page lists "SDI Intelligence portal (:8071)" on SDI-APP01) already runs there.
- **Deploy plan (once confirmed):** on SDI-APP01: clone the repo to `C:\SDI_X3\repo`, run `add_live_orders_to_portal.py --target <the server's portal folder>` (preview, then `--apply`), copy the X3 settings file privately (never git / chat / email), give SDI-APP01's computer account write on the LiveOrders folder, restart the service there. Then change `$CorrectIP` in the Intune hosts script to 10.0.0.5, and stop the copy on James's PC so there's one Regenerate.
- **Diagnosed (James's checks):**
  - port 8071 on the PC is held by `C:\Users\james.gray\AppData\Local\Programs\Python\Python310\python.exe`, started **14:44**, before the installer (16:36) and `Restart-Service` (16:49). It is a hand-started portal, not the NSSM service (`.venv\Scripts\python.exe`), so the restart never replaced it, and the service can't bind 8071 while it runs;
  - `app.py` on the PC is ~1,120 lines (git has 167) and **does** have the Live Orders mount (lines 1083–1084, above `__main__` at 1121);
  - the NSSM log folder `C:\ClaudeVision\output\logs` doesn't exist, so the service has no log.
  - **Fix:** look at that process's command line, stop it, restart the service, confirm the listener is now the `.venv` Python.
  - **Lesson:** after any portal change, check *who* listens on 8071 and when it started (`Get-NetTCPConnection -LocalPort 8071 -State Listen` → `Get-Process`). `Restart-Service` alone proves nothing.
- **SDI-APP01 (10.0.0.5:8071) runs the portal:** an older copy, Dashboard and AI Services menu, no Live Orders. Deploying = updating that copy (installer with `--target` its folder). Its folder and RDP access are still to confirm.
- **Fixed on James's PC (17:24):** the hand-started copy (PID 30964, `Python310\python.exe C:\ClaudeVision\sdi-intelligence-backend\app.py`) was stopped and the service restarted. **The Live Orders page now loads in the portal** ("No Live Orders data yet – 404 – press Regenerate", which is correct before the first run).
  - On this PC the service runs `Python310\python.exe` (James's per-user install), not `.venv`: the NSSM set-up differs from `SDI-Intelligence-WindowsService.ps1`.
- **New: the header says "BACKEND DEGRADED".** `/api/health` reports degraded when a file root (UNC share) or the database can't be reached. The hand-started copy ran **as James**; the service runs as **LocalSystem**, which reaches the network as the PC's computer account. From home over the VPN that account can't reach the shares. **The same blocks Regenerate saving to `\\sdi-dc01\…\LiveOrders`.**
  - **Fix for the PC today:** in `services.msc`, set the service's Log On to James's own account (the password goes in the Windows dialog, never on a command line or in chat), then restart.
  - **On SDI-APP01:** a proper service account with read on the file roots and write on LiveOrders.
- **The server check was run in Command Prompt, not PowerShell** ("'Get-NetTCPConnection' is not recognized"). Type `powershell` first.
- **First Regenerate pressed on James's PC (20 Nov, evening).** That run reuses today's products and BOMs (pulled earlier today, under 24 h old) and pulls the transactions plus **routings for the first time** (every routing operation, 50 a page, 1 s pause).
- **Fixed after it started (applies from the next run, after `git pull`):**
  - `run_x3.py` streams the pull's lines (`run_streamed`, `python -u`, PYTHONUNBUFFERED), so the portal shows live progress instead of only "Generating…". Before, the output was captured and only appeared at the end;
  - the pull's limit is now 4 h (`--pull-hours`), not 60 min. Data sets already written stay in today's exports folder, so a stopped pull resumes on the next press;
  - `live_orders_routes.py` starts `run_x3.py` with `-u` (installer copy and restart needed);
  - `x3_api.py` no longer needs `api_datasets.json`: without it, it uses the Live Orders data sets in the code (NODES / LEAN). The file was only on James's PC (git-ignored); a fresh copy on the server now pulls without a `draft`.
- **Next:** refresh products / BOMs / routings overnight (Task Scheduler, `run_x3.py --full` or a master-only pull), so a daytime Regenerate only pulls orders and stock (minutes).
- **First Regenerate result:** "Last run failed: No --routes given and no routes.json in any pull". Routings **were** asked for, but nothing came back, and the reason was lost:
  - `x3_api.pull` caught only SystemExit per data set, so any other error (connection reset, an unexpected X3 reply) **crashed the whole pull**;
  - Python exits 1 on a crash, and `run_x3` treats exit 1 as "some data sets failed, carry on". So it built with the morning's products and BOMs, then stopped on the missing routings with a misleading message.
- **Fixed:**
  - `x3_api.pull` catches every error per data set ("<name>: FAILED - <Error>: <message>"), carries on with the rest, and logs an unknown data-set name instead of crashing;
  - `run_x3.pull_failures` reads that day's `api_log.json` (and a crash's last line). Failures go in `status.json` (`pull_failed`); a missing master file now says "No routes from Sage X3 - the pull said: …"; a build that succeeded on partly old data gets a `warning`;
  - the portal shows the warning, and up to 400 characters of an error.
  - Tested: a forced ConnectionResetError on routes → so_lines and products still pulled, exit 1, the failure reported in X3's words.
- **To find this run's actual reason:** `status.json` → `pull.out` (the pull's last 2,000 characters; no secrets).
- **Second Regenerate (17:37 restart, new code): progress now shows live on the page** ("stock: 0 rows", "… 500 rows so far").

#### 20 Nov (late) – Server: SDI-APP01 gets Live Orders (`sdi-intelligence-backend/deploy_live_orders_server.ps1`)
- SDI-APP01 (10.0.0.5:8071) already runs the portal (older copy, backend online). The script updates that copy; it is run **on the server**, PowerShell as administrator.
- **From James's PC first** (admin share; robocopy leaves out `.git` and every `.env`. The repo's committed `.env` holds secrets and must not travel):
  1. `robocopy C:\SDI_X3\repo \\10.0.0.5\c$\SDI_X3\repo /E /XD .git /XF .env /NFL /NDL /NP`
  2. `New-Item -ItemType Directory -Force \\10.0.0.5\c$\ProgramData\SDI`
  3. `Copy-Item "$env:USERPROFILE\.sdi\x3_api.json" \\10.0.0.5\c$\ProgramData\SDI\x3_api.json`. **The X3 secret goes PC → server directly, never by email, chat, git or screenshot.**
- **On the server:** `powershell -ExecutionPolicy Bypass -File C:\SDI_X3\repo\sdi-intelligence-backend\deploy_live_orders_server.ps1`
  - finds the portal from the port 8071 listener (folder from the `app.py` argument, its Python, its service via the process or its NSSM parent); `-Target` if it can't;
  - Python 3.10+ and openpyxl (installs openpyxl if missing);
  - locks the X3 settings file (Administrators, SYSTEM, the service account) by SID;
  - working folder `C:\ProgramData\SDI\LiveOrders` (runs, X3 exports);
  - installer preview → **asks** → `--apply` (backups) with `--x3-config / --runs / --exports / --share`;
  - restarts the service and waits until `/api/live-orders/dashboard` answers;
  - if the service runs as LocalSystem: a one-off SYSTEM scheduled task writes and deletes a test file in the LiveOrders share. **This proves SDI-APP01$ can save the workbooks**; if not, grant it Modify (share and folder) or use a domain service account.
- **Then:** point the Intune hosts script (`SDI-Intelligence-HostsEntry.ps1`, `$CorrectIP`) at 10.0.0.5, so `sdi-intelligence.sdi.local` reaches the server, and stop the copy on James's PC (one Regenerate, one history).
- Not testable here (no PowerShell in the build container): read through line by line, PowerShell 5.1 syntax only.
- **Third Regenerate: the real reason, shown on the page by the new reporting:** `routes: GraphQL 200: [{"message": "RoutingOperation.mainWorkCenter: Mandatory property", … "path": ["x3Manufacturing","routingOperation","query","edges",21,"node", …]`.
  - **Some routing operations in SDI Mig have no main work centre**, although X3 calls it mandatory (loaded past X3's validation).
  - X3 then refuses the **whole page** of 50 that holds such a record, so the routes data set failed.
  - **Migration data finding:** routing operations with a blank main work centre in X3ERPV12_SDIMIG. The count comes from the next pull (the note on the page). Check those lines in the ZSDIROU2 load file before the next load.
- **Fixed (`x3_api.pull_graphql`):** X3's error names the bad record's position (`edges`, 21). The pull takes the records before it, steps over it by its cursor (a query for `edges { cursor }` only), and carries on. If X3 sends the rest of the page with the record nulled, that's used directly.
  - Skipped records are **counted and reported**, never silent: "routes: N rows (skipped K record(s) X3 couldn't return: …)" in the pull, `notes` in `api_log.json`, and a **warning on the portal page** after a successful build.
  - `GqlError` (a SystemExit) keeps X3's error list and any partial data.
  - **Tested** against a simulated X3 (130 records, 4 bad: two next to each other and the very last), both ways X3 might answer (whole page refused / page with the record nulled): all 126 good records, 4 skipped and reported.

#### 20 Nov (evening) – "We have that logic? It's live orders and live data, not a historical report" (James)
- **Yes, and it is the same code.** `x3_source.py` turns X3's data into the shape of the Access extract; then the **same `build_live_orders.py`** that was reconciled to Access on 16 Nov works out the board. The X3 version has no logic of its own. Every Regenerate reads X3 at that moment (open WOs, stock, open SO and PO lines) and works it out from scratch. The saved workbooks are just a record of each generation; the portal always opens the newest.
- **Gap found and fixed while checking:** X3's work-order lines and sales-order lines **include closed ones**; Access's extract never did.
  - Without a filter, a short-closed works order would show as live with a balance, and a closed SO line with undelivered quantity would show as demand in WO Suggestions.
  - Fix: `drop_if_contains` in `x3_columns.json` (wo_products: lineStatus / workOrderStatus contains "closed"; so_lines: lineStatus contains "closed"), in `x3_source.py`. It matches the word, whatever X3's enum spelling.
  - Tested: closed WO lines, closed WOs and a closed SO line dropped; firm, planned, open and partly delivered kept. PO lines already dropped closed (`isClosed`).
  - **To confirm on real data:** the actual lineStatus / workOrderStatus values once WOs are loaded (SO lines can be checked now from `so_lines.json`). Also whether **planned** (not firm) works orders belong on Live Orders: kept for now.
- **The logic is now written out for Production:** `live_orders_logic.py` (12 rules: what / the rule / how Access and Production's sheet did it / where it comes from in X3 / the 16 Nov reconciliation score, plus the "live data" statement). It is shown in two places:
  - the workbook's new **How it works** tab (the flash workbook had lost the old plain writer's Read me);
  - the portal's **How it works** tab (data contract: `live`, `logic`).
  - One list, so the two can't disagree. The material-status row says honestly that the 16 Nov reconciliation listed Production's typed status beside the board's, but didn't score it (LO-01).
- Tested: workbook rebuilt (tabs: Dashboard, Live Orders, Work-centre load, WO Suggestions, Exploded BOMs, How it works, Checks), rendered with LibreOffice; the portal tab shows all 12 rows, no errors.

#### 20 Nov (evening) – Jira brought up to date with the Live Orders work (James: "we should be updating Sage X3 Jira tasks with all of this work")
- **RULE (James): every piece of Sage X3 work goes on its own Jira task(s), not only SCRUM-329.** Find the tasks it touches (`project = SCRUM AND text ~ "Live Orders" …`) and update each: status, plus a comment saying what's built, what's left, and how it differs from the task as written.
- **James: Production will test it fully; minor changes in behaviour are accommodated.**
- **Moved to In Progress:** SCRUM-241 (INT-X3-06 Live Orders), SCRUM-246 (LO-02 board), SCRUM-247 (LO-03 load), SCRUM-248 (LO-04 suggestions), SCRUM-249 (LO-05 exploded BOM). None closes before Production's test (each task's "Done when").
- **Comments:** SCRUM-241, 245 (LO-01: 5 points for the sit-down), 246, 247, 248, 249, 233 (Proto Live orders not built), 222, 165 (routing ops with no main work centre), 167 (what Live Orders needs from the WO and stock load), 195 (portal page), 329.
- **New sub-tasks under SCRUM-241:** SCRUM-332 (LO-06 server, SDI-APP01), SCRUM-333 (LO-07 refresh schedule), SCRUM-334 (LO-08 Production test).
- **Gap found while writing them:** **material cost** on the exploded BOM is blank in the X3 version. The X3 standard cost isn't pulled yet (`run_x3` passes no `--costs`). To add: a cost data set from X3 (SCRUM-249 / 222).
- **Honest wording kept on Jira:**
  - LO-04's suggestions are the board's own (Production's tab-2 logic), not X3 MRP output;
  - LO-03 is a built view, not X3's capacity inquiries;
  - the material status is the board's share-out (Access logic), not X3 allocations. Each is a decision for LO-01.
- **Fourth Regenerate: the pull got through (orders, stock, routings); the build failed with "No module named 'openpyxl'".** Live Orders runs with `LIVE_ORDERS_PYTHON`, which the installer set to the Python it was run with (`C:\Python314\python.exe`), and that Python had no openpyxl. **Fix:** `C:\Python314\python.exe -m pip install openpyxl`, in PowerShell as administrator, so it lands in the shared site-packages the service (LocalSystem) reads.
  - Now `run_x3` adds the exact pip command to a missing-module error, and the installer warns when its own Python has no openpyxl. The server script already checks the portal's Python.
  - **Before re-running:** today's `api_log.json` holds the routing records X3 couldn't return. The next run won't re-pull routings (they're fresh), and it overwrites `api_log.json`, so read it first (for SCRUM-165).

#### 20 Nov (evening) – Next after Live Orders (James): the estimating import in the portal, then load into X3
- **James:** a button on the portal to load an estimating spreadsheet, generate the input files for review in the portal, then **auto-load into Sage X3** ("we're putting together a new ERP platform essentially in the portal"). James has the details if needed.
- **What exists (stage 1, built 12 Nov, proved 13 / 16 Nov):** `sagex3/estimating/est_to_x3.py` (Dave's IMPORT layout) writes the X3 load files plus `_CHECKS.xlsx` (STOP / WARN / INFO by cell), and `est_app.py` is a small web page around it. README §5 is the portal-embedding plan.
- **"Is BOM + route all the load?" No:**
  1. **ZSDIITM, the product itself:** written when the parent is new (estimated parts usually are);
  2. **YA00408BOM**, the BOM;
  3. **ZSDIROU2**, the route.
  Then, still to add:
  - **any new component** (e.g. a new bought-in part): a product record, and a product-supplier (ZSDIITMSUP) to buy it. Today the converter STOPs when a component isn't in X3;
  - **the standard cost (YITC):** not loaded today (Acuity question B10), and wanted for Live Orders' material cost;
  - **the product-site record:** to confirm whether ZSDIITM / the category creates it.
  - Load order: product → (product-site) → BOM → route → cost.
- **Loading into X3 is a WRITE.** The API connection we have is deliberately read-only ("SDI Live Orders read-only"; mutations refused in `x3_api.py`). Loading needs:
  - a separate write-capable connected application / user (James is admin; no Acuity);
  - a way in: GraphQL create mutations if X3 exposes them for product / BOM / routing (check the schema), or X3's import function run from the batch server;
  - **SDI Mig / test first**; live only after sign-off;
  - create-only, never change an existing product, BOM or route without an explicit "replace" (Acuity B6);
  - a log of every load.
