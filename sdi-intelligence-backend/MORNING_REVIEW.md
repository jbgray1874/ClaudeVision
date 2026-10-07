# AM CRM morning review: setup

Every weekday at 07:50 the server reads Nick's sandbox tracker and emails a review to Nick and James. It is laid out like the ChatGPT review Nick sent on 6 October:

- the counts
- what moved since the last review
- the five records most worth a decision today

It is **read-only** and never writes to the tracker.

## How it decides

The rules are in `morning_review.py`. All counts and the top-five choice come from code, so they are exact and can be checked. Claude only writes the "Issue" and "Decision needed" sentences from those facts. If Claude is unavailable, plain wording is sent instead.

| Line in the email | Rule (active NG records only) |
|---|---|
| Active NG records | AM Owner = NG, not invoiced (Yes or N/A), not lost, cancelled or closed |
| Completion/invoice or PO/status conflicts | Status or Next Steps says completed or delivered but Invoiced isn't Yes; Ordered with no PO; Awaiting PO with a PO recorded |
| Overdue actions | KEY DATES FOR NEXT STEPS is before today |
| Ordered projects past their end date | Commercial Status Ordered and END is before today |
| Missing/invalid core-data issues | Budget, PM, next action date, end date or status is blank or unreadable |
| Contact-review triggers | Last Client Contact Date is blank or more than 14 days ago (`SDI_REVIEW_CONTACT_DAYS`) |
| Due within seven days | Next action date falls in the next 7 days (`SDI_REVIEW_DUE_DAYS`) |
| Up from / down from, New movement | Compared with the last review that was **sent** |
| Today's five questions | Highest score: conflicts > ordered past end > overdue days > contact > missing data, weighted by budget |

## You can use it today, from the app

In the app there is a **Morning review** panel with two buttons:

- **Show today's review** builds it now, using your own sign-in.
- **Email it now** sends it. This is for Nick and James only, and needs `SDI_REVIEW_TO`.

## The 07:50 schedule (one-off setup)

At 07:50 nobody is signed in, so the server needs its own read access to **the sandbox site only**.

### 1. Entra: give the app read access to the sandbox site

1. Go to **Entra admin centre → App registrations → SDI Intelligence Portal → API permissions → Add a permission**.
2. Choose **Microsoft Graph → Application permissions → Sites.Selected → Add**.
3. Click **Grant admin consent for SDI Displays**.

   Sites.Selected on its own opens **nothing**. Each site has to be granted separately, which is the next step.

4. Open **Graph Explorer** (https://developer.microsoft.com/graph/graph-explorer) and sign in as an admin.
5. Under **Modify permissions**, consent to `Sites.FullControl.All`. This is needed only to grant the access below.
6. Find the sandbox site's id. Use the path from `SDI_VOICECRM_SITE` in the server's `.env`:

   ```
   GET https://graph.microsoft.com/v1.0/sites/<value of SDI_VOICECRM_SITE>
   ```

   Copy the `"id"` from the response.

7. Grant the app **read** access to that site only:

   ```
   POST https://graph.microsoft.com/v1.0/sites/<id>/permissions
   {
     "roles": ["read"],
     "grantedToIdentities": [{ "application": {
       "id": "9cb2810e-9aad-4904-ba1a-506ce9efa322",
       "displayName": "SDI Intelligence Portal" } }]
   }
   ```

   The response should be `201 Created`.

### 2. Server: install openpyxl and set who gets it

Run on SDI-App01:

```powershell
cd C:\ClaudeVision\sdi-intelligence-backend
.\.venv\Scripts\python.exe -m pip install "openpyxl>=3.1,<4.0"
Add-Content .env "`nSDI_REVIEW_TO=nick.garrish@wearesdi.com,james.gray@wearesdi.com"
Select-String -Path .env -Pattern '^SMTP_HOST=|^SMTP_FROM=|^SDI_REVIEW_TO='
```

`SMTP_HOST` and `SMTP_FROM` must both show a value. These are the same mail settings the estimate emails use.

### 3. Test, then schedule

```powershell
.\.venv\Scripts\python.exe morning_review.py          # preview only, nothing sent
.\.venv\Scripts\python.exe morning_review.py --send   # sends one now
.\deploy\install_morning_review_task.ps1              # weekdays 07:50 from now on
```

If the preview says **No app-only Graph token** or **401/403**, step 1 isn't finished.
