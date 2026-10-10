# Tracker connector: two-day proof (made-up data)

Lets ChatGPT's or Claude's own voice mode talk to a tracker through our rules
(read-back, plain yes, version check, save once, journal). Made-up records in
memory only: no SharePoint, Graph, Entra or real data. See the docstring in
`tracker_connector.py`.

It also shows three cards inside the conversation (`cards.py`): **Records**,
**Read-back** with Yes / No buttons (which then shows what was saved), and
**Recent activity**. Tapping Yes calls our server directly, no AI judgement.

## 1. Put it on Azure (about 10 minutes, laptop, PowerShell)

Needs the Azure CLI (`winget install Microsoft.AzureCLI`, then reopen PowerShell).

```powershell
az login
cd C:\ClaudeVision\sdi-intelligence-backend\proof_connector
$key = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
$app = "sdi-tracker-proof"          # must be unique across Azure; add digits if taken
az webapp up --name $app --resource-group rg-sdi-intelligence --location uksouth `
  --runtime "PYTHON:3.12" --sku B1 --plan sdi-tracker-proof-plan
az webapp config appsettings set --name $app --resource-group rg-sdi-intelligence `
  --settings PROOF_KEY=$key WEBSITES_PORT=8000
az webapp config set --name $app --resource-group rg-sdi-intelligence `
  --startup-file "python tracker_connector.py"
"Connector: https://$app.azurewebsites.net/$key/mcp"
"Journal:   https://$app.azurewebsites.net/$key/journal"
```

Keep the two addresses private: the key in them is the only lock.
B1 costs pennies an hour. Delete it when the proof is over (step 4).

## 2. Connect it

- **ChatGPT** (web, signed in to the account you'll test with): Settings → Apps
  (or Plugins) → Advanced → turn on **Developer mode** → Create. Name *SDI
  Tracker (proof)*, the Connector address above, authentication **None**.
  Business workspaces: an admin turns on Developer mode first.
- **Claude** (claude.ai): Settings → Connectors → Add custom connector → the
  Connector address. Then on the connector's page set **confirm_changes** to
  *Always allow* (a tap to approve is no use in the car).

Both then appear in the phone apps. Start a voice conversation and ask it to
use *SDI Tracker*.

## 3. Test script (in the car, phone in a holder)

Open the Journal address on a laptop or second phone to watch what happens.

1. "What's due this week?"
2. "What's going on with Castellano?" (an awkward name)
3. "Which jobs are overdue?"
4. "Mark the Castellano window unit as job completed." → read-back → "yes"
5. "Northway Bank: confidence 80 percent and next step call them Friday." → "yes"
6. Ask for a change, then say "no, don't do it". Nothing should be saved.
7. Talk over a long answer. Does it stop and listen?
8. Ask something off-topic, then go back to the tracker.

9. At a desk, typed: "show me my records", then ask for a change and tap
   **Yes — save** on the card. Then "show recent activity".

For each, note: did it understand, how long the pause was, did it read back
before saving, did it wait for your yes, and did the cards appear (in voice
mode as well as typed chat?). The real tracker would add about
1–2 s per lookup or save for Microsoft Graph.

## 4. Remove it

```powershell
az webapp delete --name $app --resource-group rg-sdi-intelligence
az appservice plan delete --name sdi-tracker-proof-plan --resource-group rg-sdi-intelligence --yes
```
Then remove the connector in ChatGPT / Claude settings.
