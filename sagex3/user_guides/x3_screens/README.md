# Sage X3 screens guide (Customer Services, Finance)

How the users' Access reports are replaced by Sage X3 standard screens, with screenshots from the training site.

- **`screens.json`** is the tracker: every screen to capture (search name, code, path, which report it replaces, for whom), with its status and screenshots. James sends screenshots from the training site five at a time; each batch is logged here.
- **`shots/`** holds the screenshots. Names start with the order and the X3 function code.
- **`build_guide.py`** builds the Word guide for Debbie from the tracker and screenshots:
  `python build_guide.py Sage_X3_guide_Debbie_Customer_Services_DRAFT.docx`

**Process:** James captures the selection screen and the results screen → the tracker is updated → the guide is rebuilt → Marc (Acuity) validates → the guide goes to Debbie, who fills in the "What to check" tables.

The guide itself is not kept in git; rebuild it.
