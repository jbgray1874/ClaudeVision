# Giving people access with one Entra group instead of a list

Adding somebody to an SDI app used to mean two jobs in two places: assign them
to the app in Entra, **and** paste their object ID into a setting on the server
and restart it. Two places, every person, every app — and a 36-character id
typed by hand into a file that is not in version control.

This does both with one group. After it, adding a person to the group is the
whole job: no server, no `.env`, no restart.

Do it once per app. The worked example is estimating; TTI Despatch and the
systems console are the same with their own group and setting.

**Where each step happens is stated.** Azure's menu names move about; the
values are what matter.

---

## Before you start

Have ready:

- a tenant admin sign-in for **portal.azure.com**
- access to the server's `.env`:
  `\\10.0.0.5\c$\ClaudeVision\sdi-intelligence-backend\.env`
  (editable from the laptop over UNC with the VPN on)

---

## 1. Make the group — *Entra admin centre*

**Entra ID → Groups → All groups → New group**

| Field | Value | Why |
|---|---|---|
| Group type | **Security** | Not Microsoft 365 — this grants access, it is not a mailbox |
| Group name | `SDI Estimators` | |
| Group description | *"Access to SDI Intelligence estimating — portal sign-in and starting runs from outside the office."* | In a year somebody will wonder what it is for |
| **Entra roles can be assigned to the group** | **OFF** | See below. Set at creation and **cannot be changed after** |
| Membership type | **Assigned** | Not Dynamic |
| Roles | *No roles selected* | Nothing to do with this |
| Owners | **yourself, and whoever covers for you** | An owner manages membership **without being a Global Admin** — this is what makes adding somebody a one-click job later |
| Members | the estimators | |

> ### Leave "Microsoft Entra roles can be assigned to the group" OFF
>
> It is on by default on some tenants and it is the wrong setting here. It
> makes the group *role-assignable*, which is for granting Entra admin roles
> (Global Administrator and the like), and it has two consequences:
>
> * membership becomes **protected** — only a Privileged Role Administrator
>   may add or remove people, which defeats the point of using a group at all;
> * **it cannot be changed after the group is created.** Getting it wrong means
>   deleting the group and starting again.
>
> It also forces Membership type to Assigned and greys the field out, which is
> the visible clue that it is on.

**Create**, then open the group and copy its **Object Id** — a long
`xxxxxxxx-xxxx-…` value. That one string is used twice below and nowhere else.

> ### Add your ORDINARY account, not the admin one
>
> You will be signed in to Entra as `cadmin-…` to do this, which is correct for
> creating the group. The member you add for yourself must be the account you
> sign in to the portal with — `James.Gray@wearesdi.com`, object id
> `5acf6b37-147f-4468-bdb1-ecc3da1f1076`. They are different accounts with
> different object IDs, and the admin one signing into the portal will not
> match. This is the trap the refusal messages warn about by name.

> **Already have a group?** Use it. Any security group works, including one
> synced from on-premises AD. Just take its Object Id.

---

## 2. Let the group sign in to the portal — *Entra admin centre*

**Entra ID → Enterprise applications → SDI Intelligence Portal →
Users and groups → Add user/group**

Under **Users and groups**, pick the **group** — not the people. Assign.

This is the half that lets them reach the portal at all. If the application's
**Properties → Assignment required** is *No*, anyone in the tenant can already
sign in and this step changes nothing; leave it as it is either way.

---

## 3. Make Entra actually send the group — *Entra admin centre*

**This is the step that is easy to miss and silently undoes the rest.** Until
it is done, every sign-in carries `"groups": []`, a group id in a setting
matches nobody, and it looks exactly like "that person is not in the group".

**Entra ID → App registrations → SDI Intelligence → Token configuration →
Add groups claim**

| Choose | Value |
|---|---|
| Which groups | **Security groups** |
| Customise token properties — ID | **Group ID** |
| Customise token properties — Access | **Group ID** |

Tick **ID** and **Access**. Both: the web app reads the ID token, the ChatGPT
connectors read the access token.

> **Leave the format as Group ID.** The other options emit
> `sAMAccountName` or `NetBIOSDomain\sAMAccountName` — names, not object IDs —
> and the settings below are matched on object ID, so names match nothing.

**Save.**

---

## 4. Name the group in the setting — *the server's `.env`*

Edit `\\10.0.0.5\c$\ClaudeVision\sdi-intelligence-backend\.env` and set the
group's Object Id from step 1:

```ini
SDI_ESTIMATOR_OIDS=<the group's Object Id>
```

The same settings take a group id, a person's object ID, or a mix — so an
existing list of people keeps working and can be replaced whenever suits:

| App | Setting | What it governs |
|---|---|---|
| Estimating, from outside | `SDI_ESTIMATOR_OIDS` | **Starting a run.** Looking is open to anyone signed in. |
| Estimating, looking | `SDI_ESTIMATOR_VIEWERS` | Leave **empty** unless you want to narrow who may look. |
| TTI Despatch (web and ChatGPT) | `SDI_TTI_OIDS` | The whole app |
| Systems console | `SDI_OPS_OIDS` | The whole app (with `SDI_OPS_ENABLED=yes`) |

`.env` is read **once, at startup**.

---

## 5. Restart — *the laptop, VPN on*

```powershell
cd C:\ClaudeVision
.\sdi-intelligence-backend\deploy\Check-AMCRM-Live.ps1 -Restart
```

---

## 6. Check it worked — *any browser, signed in*

Open:

```
https://sdiintelligence-sdidisplays.msappproxy.net/api/me
```

**Sign out and back in first** — an old session carries an old token, and the
groups claim only appears in a new one.

You should see the group id in `groups`:

```json
{"signed_in":true,"name":"James Gray","email":"James.Gray@wearesdi.com",
 "oid":"5acf6b37-…","groups":["<the group's Object Id>"],"kind":"user"}
```

**If `groups` is still `[]`,** step 3 has not taken effect. Sign out fully,
close the browser, and sign in again. If it is still empty, re-check the
Token configuration: the claim has to be on the **SDI Intelligence** app
registration — the one whose Application (client) ID is `SDI_CLIENT_ID` in the
server's `.env` — and not on a different registration with a similar name.

---

### One thing to check while you are in there

The portal has its own optional sign-in gate, `SDI_ALLOWED_GROUPS`, separate
from everything above. **If it is set in `.env`**, somebody must be in one of
*those* groups before they can sign in at all — being in `SDI Estimators`
would not help, and the refusal comes from the sign-in rather than the app.

If it is empty (the default), any tenant user who is assigned to the
application can sign in, and step 2 is the only gate. Either way, the simplest
arrangement is to use the same group in both places.

---

## From then on

**Entra ID → Groups → SDI Estimators → Members → Add members.**

That is the whole job. Nothing on the server changes, nothing is deployed, and
nothing is restarted.

---

## If somebody is refused

The apps say which of four walls was hit, because they need four different
things done:

| What it says | What to do |
|---|---|
| *"… is empty, so nobody can use this yet"* | The setting has nothing in it. Step 4. |
| *"This needs a signed-in person"* | Something is calling with a key or a service account, not an account. |
| *"this sign-in carried no group at all"* | **Step 3 has not taken effect.** Sign out and in; then re-check the token configuration. |
| *"not on the list and nor is any group it belongs to"* | They are genuinely not in the group — **or they are signed in as the wrong account.** An admin account is a different account from the ordinary one, with a different object ID. `/api/me` says which they are using. |

No refusal ever prints what is *in* a setting. That would hand a stranger the
object IDs of everybody who is allowed.

---

## Two things worth knowing

**Everything fails closed.** An empty setting admits nobody, never everybody.
If `.env` is lost, overwritten or corrupted, the apps refuse rather than open —
which is the right way round for a file that is hand-edited over a share and
is not in version control.

**Entra drops the claim for a user in more than about 200 groups.** That
person would be refused rather than let through. It is rare, it is the safe
way round, and `auth.py` has carried the same limit since the portal's own
`SDI_ALLOWED_GROUPS` was written.
