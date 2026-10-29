# Email to Nick — asking him to save one change

Send after `Deploy-AMCRM.ps1` has reported **DONE** and the service has
restarted. Adjust the app URL before sending.

---

**To:** Nick Garrish
**Subject:** AM CRM — the failed-save problem is fixed. Two things: a quick test, and Sage

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

---

**Separately — feeding it from Sage.** I hear you want this joined up to Sage,
and I think that is the right instinct. Before anyone builds anything I'd
rather have your view on the shape of it, because there is a decision in here
that is yours and not ours.

Sage X3 will know the things the tracker can only guess at: what each client
has actually bought and when, whether a quote turned into an order, where a job
is on the floor, what was invoiced and whether it has been paid, and the margin
as finance posted it rather than as estimated. Your tracker knows the things
Sage will never know: what the next step is, who you are waiting on, how
confident you are, and the context behind the number.

So the useful question is not "should they talk to each other" — they should.
It is **which columns should stop being yours to type.**

If a figure comes from Sage, the app has to stop letting anyone edit it here,
or the two systems will quietly disagree and neither will be trustworthy. That
is a real trade and you are the person who should make it:

1. **What do you type today that you believe Sage already knows?** That is the
   list worth automating first — typing a number a system already holds is the
   waste that annoys most.
2. **Which of those would you be content to lose the ability to edit?** Anything
   Sage owns becomes read-only here. If there is a column where you need the
   last word even when Sage disagrees, say so now rather than later — that is a
   design decision, not a bug to raise afterwards.
3. **What would you want to be told rather than look up?** "This client hasn't
   ordered in four months", "that quote converted", "this one's invoice is 60
   days overdue" — alerts are where this gets genuinely useful, and they need
   Sage to exist.
4. **Anything you'd want to push the other way**, from the tracker into Sage?
   I'd expect the answer to be very little, and I'd want a good reason before we
   wrote anything into the ERP from here.

**Timing, honestly.** X3 is still being loaded and tested area by area —
estimating first, then customer services and finance. Nothing for sales exists
to read yet, so this is a "what should it look like" conversation, not something
I can deliver this month. But the answers shape what we build next, and getting
them before the data arrives is much better than after.

Your tracker's columns are a good place to start the conversation — CLIENT, JOB,
STATUS, NEXT STEPS, KEY DATES, BUDGET COST, CONFIDENCE, MARGIN. If you went
down that list and marked each one *mine*, *Sage's*, or *both*, that alone would
tell us most of what we need.

Thanks for the 23 October report. It was precise enough to find a bug that
would have been very hard to see otherwise, and the four things you asked us to
confirm are now the four things the tests check on every change.

James

---

## Notes for James, not for sending

**Do not send this until both checks below pass.** The fix lives in
`voicecrm_excel.py` on the server. Until that file is copied and the service
restarted, Nick is running the code that told him a saved change had failed —
and asking him to test it would get the old answer and cost his confidence
twice.

**1. Is the code actually on the server?** Every response carries the running
commit, so this needs no server login:

```powershell
(Invoke-WebRequest http://10.0.0.5:8000/api/health -UseBasicParsing).Headers["X-SDI-Commit"]
```

It must read `7deb273f` or later. `45d0fd6d` means the deploy has not run.
`.\sdi-intelligence-backend\deploy\Deploy-AMCRM.ps1 -Check` says the same thing
from the laptop and copies nothing.

**2. Are writes switched on?** They are a separate `.env` setting from the fix,
and if any is missing Nick gets a polite refusal rather than a save — which
looks exactly like the bug coming back.

```powershell
Invoke-RestMethod http://10.0.0.5:8000/api/voicecrm/status
```

`writes_enabled` true, `approved_by` filled in, and his email in the writers
list. If not: `SDI_VOICECRM_WRITE=yes`, `SDI_VOICECRM_APPROVED_BY=<name>`,
`SDI_VOICECRM_WRITERS=<his email>,<yours>`. `.env` is read once at startup, so
a change there needs a restart.

**After he has saved something**, the lines to send me. Ask NSSM where the log
is rather than assuming a path — there are three different names for it in the
repo's own scripts, and I guessed the wrong one once already:

```powershell
$log = & C:\Tools\nssm.exe get SDIIntelligence AppStdout
Select-String $log -Pattern "\[voicecrm.tracker\]|\[voicecrm.interpret\]" |
  Select-Object -Last 20
```

- `[voicecrm.tracker] write … outcome=saved secs=…` — the write itself
- `[voicecrm.tracker] read … sheet_reread=no secs=…` — a lookup that reused the
  last reading rather than re-reading the sheet
- `[voicecrm.interpret] … secs=… first_say=…` — the model half

If `outcome=not_saved` appears, that is the honest failure path and it carries
Microsoft's request ID. Send the whole line and tell Nick not to retry.

**On the Sage section.** It asks him to classify his own columns rather than
asking "what do you want from Sage?", because the open version of that question
gets "everything, joined up" and the useful version gets a list. The point it
is really making is the one he will not have thought about: a column Sage owns
has to become read-only in the app, and if he needs the last word on something
even when Sage disagrees, that has to be said before it is built rather than
raised as a complaint afterwards.

It also says plainly that nothing for sales exists in X3 to read yet, so he is
not left expecting it this month. Worth checking that against where Acuity
actually are before you send — if customer services testing has slipped, soften
the timing line rather than let him find out from somebody else.

There is nothing in the AM CRM app today that touches Sage, and this email does
not promise otherwise. It asks for the shape.
