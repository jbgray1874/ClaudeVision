# Email to Nick — asking him to save one change

Send after the service has been restarted and `Check-AMCRM-Live.ps1` shows
section 4b green. Notes for James at the bottom.

Short on purpose. Nick needs to do two things, and an email that explains the
bug in full is an email he reads later.

---

**To:** Nick Garrish
**Subject:** AM CRM — saving is fixed. One quick test, and a Sage question

---

Nick,

The 23 October problem is fixed and live. Your change **was** saved, every
time — what was wrong was our check straight afterwards, which read the cell
back from a copy of the workbook that hadn't caught up and reported a failure
on something safely in the file. The write and the read-back now happen in one
Excel session, so they can't disagree. It's also a good deal quicker,
especially on the phone.

**Could you save one change when you get two minutes?** Ask it something
first, then change one thing — a status, a next step, a date — say yes to the
read-back, and tell me **exactly what it says next**. Then check the cell in
the tracker. If the app and the tracker disagree, don't retry: tell me, and
the log will have what I need.

**On Sage** — I hear you want this joined up, and I agree. One thing to settle
first: anything Sage owns has to become **read-only** here, or the two will
quietly disagree and neither can be trusted. So if you went down your columns
— CLIENT, JOB, STATUS, NEXT STEPS, KEY DATES, BUDGET COST, CONFIDENCE, MARGIN
— and marked each *mine*, *Sage's*, or *both*, that would tell us most of what
we need. Worth saying now if there's one where you'd want the last word even
when Sage disagrees.

Fair warning on timing: X3 is still loading area by area and nothing for sales
exists to read yet, so this is a "what should it look like" conversation rather
than something I can deliver this month.

Thanks for the original report — it was precise enough to find a bug that
would have been very hard to see otherwise.

James

---

## Notes for James, not for sending

**Do not send until both of these pass.** The fix is in `voicecrm_excel.py` on
the server. Until the service has been restarted, Nick is running the old code
in memory — he would get the old answer and lose confidence twice.

```powershell
cd C:\ClaudeVision
.\sdi-intelligence-backend\deploy\Check-AMCRM-Live.ps1 -Restart
```

1. **Section 4b green** — "the service started after the files were written".
2. **Section 5 green** — `SDI_VOICECRM_WRITE`, `APPROVED_BY` and `WRITERS` set.
   Any one missing is a polite refusal, which looks exactly like the old bug.

**Check the X3 timing line** against where Acuity actually are before sending.
If customer services testing has slipped, soften it rather than let Nick hear
it from somebody else.

**What was cut, and why it can go.** The four things he asked us to confirm on
23 October are all done and tested — one cell not the whole file, the cell read
back, delegated permissions, status and request ID on failure — but he knows
what he asked for, and listing it back reads as justifying ourselves. Same for
the round-trip numbers (11 down to 5 per change, 36 down to 14 for a
three-part sentence): worth having if he asks, not worth his reading time
unprompted.

**The point of the Sage paragraph** is the read-only trade, not the
integration. The open question — "what would you want from Sage?" — returns
"everything, joined up". Asking him to classify his own columns returns a list.
And a column Sage owns that the app still lets him edit is the same class of
problem as the write bug he just reported, which is why it is worth raising
with him rather than deciding for him.

**After he has saved something**, re-run the script without `-Restart`; section
6 prints the lines to send me:

- `[voicecrm.tracker] write … outcome=saved secs=…` — the write
- `[voicecrm.tracker] read … sheet_reread=no secs=…` — a lookup that reused
  the last reading rather than re-reading the sheet
- `outcome=not_saved` — the honest failure path; it carries Microsoft's
  request ID, so send the whole line
