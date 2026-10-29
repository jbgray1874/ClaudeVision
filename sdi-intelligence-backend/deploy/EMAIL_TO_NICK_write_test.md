# Email to Nick — asking him to save one change

Send after `Deploy-AMCRM.ps1` has reported **DONE** and the service has
restarted. Adjust the app URL before sending.

---

**To:** Nick Garrish
**Subject:** AM CRM — the failed-save problem is fixed. Could you save one change?

---

Nick,

The problem you hit on 23 October — where you saved a change, the app told you
it had failed, and the value turned out to be in the tracker all along — is
fixed and on the server. Could you save one change for me and tell me what the
app says?

**Why it happened.** The change was saved. Every time. What was wrong was the
check we ran straight afterwards: you asked us to read the cell back and
confirm it had persisted, which was the right thing to ask for, and our first
version of that read was answered by a *different copy* of the workbook from
the one we had just written to. That copy had not caught up yet. So we read the
old value and reported a failure on a change that was safely in the file.

That was the worst possible way for us to get it wrong, because it gave you
every reason to believe writing was broken when it wasn't.

**What changed.** The write and the read-back now happen inside one Excel
session, so the two calls cannot be answered by different copies of the file.
And the rules are now explicit: the write's own success is what decides. The
read-back can add doubt on top of it, never overturn it — if that second read
can't be trusted, the change is reported as saved, with a line in the log,
rather than reported as failed.

**The other three things you asked us to confirm**, all still true and now each
covered by a test that fails if anyone breaks it:

- **One cell, never the whole file.** We write a single cell through the Excel
  range API. The workbook is never replaced or re-uploaded. (The whole-file
  replace you were offered was ChatGPT's own SharePoint connector, not ours —
  that is exactly what we avoided.)
- **The changed cell is read back** against the sheet.
- **A failure is traceable.** Any refusal reports the HTTP status, Microsoft's
  error code and the request ID, so "was it us or them" is answerable rather
  than an opinion.

One more: a calculated cell is never typed over. If a column holds a formula we
refuse the change rather than silently replace the calculation with a fixed
number — and if we can't tell whether it's calculated, we refuse. Better to
make you do it by hand than to flatten a formula nobody notices for a month.

**It is also considerably quicker.** Saving a change used to make eleven
separate calls to Microsoft, one after another, and a sentence like "change the
status, the next steps and the confidence" made thirty-six. Most of them were
waste — asking for things we already knew, and reading the whole sheet more
often than needed. That sentence now takes fourteen. You should notice it,
particularly on the phone.

Nothing was traded away for that speed. The one read we deliberately still do
in full, every time, is the one immediately before a write: it is what notices
if somebody else has edited that row while we were talking about it, and it
stops your change overwriting theirs.

**What I'd like you to do**, when you have two minutes:

1. Ask it something first — "what's due this week?" — so we can see a lookup.
2. Change one thing on a real record. Anything: a status, a next step, a date.
3. Listen to the read-back, say yes, and tell me **exactly what it says next**.
4. Then check the cell in the tracker.

What I'm looking for is the two of them agreeing: the app saying it saved, and
the tracker holding the new value. If it says anything else — or says it saved
and the cell disagrees — tell me and don't try again, because the log will have
the request ID and that is what I need.

If you'd rather change something harmless first, pick a NEXT STEPS cell and add
a word to the end.

Thanks for the 23 October report. It was precise enough to find a bug that
would have been very hard to see otherwise, and the four things you asked us to
confirm are now the four things the tests check on every change.

James

---

## Notes for James, not for sending

- Nick's write still needs `SDI_VOICECRM_WRITE=yes`, `SDI_VOICECRM_APPROVED_BY`
  filled in, and his email in `SDI_VOICECRM_WRITERS`. If any is missing he gets
  a polite refusal, not a save — worth checking before you send this.
- After he's done it, the lines I need are:

  ```powershell
  Select-String C:\ClaudeVision\output\logs\service_out.log `
    -Pattern "\[voicecrm.tracker\]|\[voicecrm.interpret\]" | Select-Object -Last 20
  ```

  `[voicecrm.tracker] write ... outcome=saved secs=…` is the write;
  `read ... sheet_reread=no secs=…` is a lookup that reused the last reading;
  `[voicecrm.interpret] ... secs=… first_say=…` is the model half.
- If `outcome=not_saved` appears, that is the honest failure path and it carries
  Microsoft's request ID — send me the whole line.
