# Email to Andy — what the AM CRM app is and how to use it

Written to be read by somebody who has not seen it. Notes for James at the
bottom, including the two things to check before sending.

---

**To:** Andy
**Subject:** SDI Intelligence AM CRM — the app built with Nick Garrish

---

Andy,

Here is the account-management app I have built with Nick Garrish. It reads
the account and project tracker you already use, answers questions about it
out loud, and changes cells when told to — by speaking or typing, at a desk,
on a phone, or hands-free in the car. It is also available inside ChatGPT, so
it works in voice mode and on CarPlay.

It is running as a **sandbox pilot** against a copy of the tracker, not the
live one. Everyone can ask it things; today only Nick and I can change
anything.

## Where it is

| | |
|---|---|
| **The app** | https://sdiintelligence-sdidisplays.msappproxy.net/app — sign in with your usual SDI Microsoft account, then **Open SDI Intelligence AM CRM →** |
| **User guide** | https://sdiintelligence-sdidisplays.msappproxy.net/app/guide-am-crm.html |
| **In ChatGPT** | the connector is called **SDI Tracker CRM** |

No VPN. It works over mobile data or any Wi-Fi. On a phone, use **Add to Home
Screen** from the browser menu — it then opens like an app and keeps its
microphone permission.

## Asking it things

Tap **Tap to talk** and speak normally, or type. Things worth asking:

- *"What's due this week?"*
- *"What's overdue?"*
- *"Tell me about Barbour."*
- *"What's my biggest job by value?"*
- *"What am I waiting on?"*

Two details that matter in practice. It matches client names **by sound as
well as spelling**, because speech recognition mangles them — "barber" finds
Barbour, "the perfume shop" finds TPS. And it reads dates back **in words**
— "the fourteenth of November", not 11/14/2026 — because a date read as
numbers is easy to mishear.

## Changing something

Say it in a normal sentence, and you can make several changes at once:

> *"Set Barbour's status to live and the next step to chase the PO, due Friday."*

Then three things happen, always in this order:

1. **It reads the change back.** *"Two changes. Barbour: Status from Quoted to
   Live. Barbour: NEXT STEPS from Awaiting sign-off to Chase the PO. Shall I
   save them?"*
2. **You answer.** "Yes", "yep", "go ahead", "save it" all save.
3. **It saves, and tells you what it saved.**

**Only a plain yes saves.** Anything with a doubt in it does not: *"yes but
change the date too"* cancels and starts again, deliberately. If it cannot
tell, it says *"I need a clear yes or no"* rather than guessing.

To add to a cell instead of replacing it, say *"add 'spoke to Dave' to the
next steps"* — it sends the old text plus the new words.

## In ChatGPT

Pick **SDI Tracker CRM**, or just ask in voice mode. The same four things are
available — look up, propose, confirm, recent activity — and changes made this
way appear in the app's Recent activity alongside the rest.

- *"Using SDI Tracker CRM, what's overdue on my accounts?"*
- *"Ask SDI Tracker CRM for everything on TPS."*
- *"Set the Barbour status to Live — read it back before saving."*
- *"What have I changed in the last day?"*

Each person connects **their own** Microsoft account through a "Connect SDI
Tracker?" page; nobody relies on anyone else's connection. The ChatGPT route
needs a ChatGPT Business seat, which Nick has.

In the car, use ChatGPT's own CarPlay app. In the app itself there is a
**🚗 Drive** mode: bigger screen, the microphone reopens by itself after each
answer, and you confirm by saying yes or no rather than tapping. Set it going
before you move off and treat it like a phone call — if it needs your eyes, it
needs you parked.

## Your morning briefing

A short email arrives on weekday mornings at 07:50 with what is due, what has
slipped and what is worth chasing. Its **Listen** link opens the app and reads
the same thing aloud. You can also ask for it any time — **▶ Listen to my
briefing**.

## Why it is safe to let it write

This is the part I would want to be asked about, so I will put it plainly.

- **It only ever sees your own rows** — the ones where you are the owner.
  Other people's are neither shown nor changeable.
- **It reads the tracker as you**, through your own Microsoft sign-in with
  SDI's MFA, so SharePoint's own permissions apply as well as ours.
- **A save is one cell**, written by Excel Online itself, so formulas
  recalculate and co-authoring sees it as if a person typed it. The app never
  uploads or replaces the workbook — that is the rule that protects everything
  else, because a whole-file upload bypasses every check below.
- **Nothing is written without a read-back and a yes.**
- **It checks the row has not moved first.** If somebody edited it while you
  were talking, the save is abandoned and you are told so. That is what stops
  your change quietly overwriting theirs.
- **It refuses the owner column** (that would hand a record away) and
  **refuses any calculated cell** — margin, for instance. If it cannot tell
  whether a cell holds a formula, it still refuses: better to make you do it
  by hand than flatten a calculation nobody notices for a month.
- **Every proposal, save, cancellation and refusal is journalled** with who
  and when, so there is always a record of what it did.

## What it is built on, briefly

A Python service on **SDI-App01** — our own server — published to phones
through Microsoft Entra Application Proxy, so nothing on the server is exposed
directly to the internet. Speech and the reply voice use Azure AI Speech;
understanding what was said uses Anthropic's Claude. The tracker is read and
written through the Microsoft Graph Excel API.

**No new licences.** The only running costs are Claude API usage and a ChatGPT
Business seat per person for that route; Azure Speech is on the free tier.

## What is not built yet

- **Per-person queues.** It serves one owner today (AM Owner = NG). Ian's PM
  queue is the main outstanding build item, with his access to set up and test.
- **An immutable Project ID.** Rows have no permanent identity, so a row is
  found by its position plus a fingerprint. That is safe — a mismatch refuses
  the save rather than writing to the wrong place — but it is not ideal, and
  I would add a Project ID column before this goes beyond the pilot.
- **Separate dated columns** for production complete, delivered to stock,
  delivered to customer and invoice date. Today those live inside Status and
  notes, which means the three stages cannot be told apart reliably.

Happy to walk you through it on a call, or sit with you for ten minutes and
let you talk to it — that tends to land better than any description of it.

James

---

## Notes for James — before sending

1. **Check Andy's surname and preferred address** — this is addressed to
   "Andy" alone because I do not have it. Fix the To: line.
2. **The links need him to be able to sign in.** He must be assigned to the
   portal's enterprise application, or he gets a sign-in loop rather than the
   app. Worth testing with him on the call rather than letting him find out.
3. **He cannot change anything** until added to the writers list, and the app
   will tell him so plainly ("Updates in this pilot are limited to named
   people"). Decide whether to mention that before he tries it.
4. **The Barbour and TPS examples are real client names.** Fine internally;
   swap them if this is ever forwarded outside.
5. **This says sandbox, not live.** Keep that in — it is the sentence that
   stops a figure from here being quoted as fact.
