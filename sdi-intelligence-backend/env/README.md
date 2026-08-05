# Configuration layers

Three files, and which one a value belongs in is decided by **what the value is**,
not by which machine it is on.

| Layer | File | Committed? | Holds |
|---|---|---|---|
| 1 | `env/common.env` | **yes** | Settings identical everywhere: UNC share roots, served file types, the estimating output root. |
| 2 | `env/<profile>.env` | **yes** | Settings that differ by machine but are not secret: port, allowed origins. |
| 3 | `.env` | **never** | Secrets, and any local override: API key, database password, BrightHR client secret. |

Anything set in the real environment beats all three. Later layers beat earlier
ones, so `.env` wins over a profile, which wins over `common`.

## Choosing a profile

`SDI_PROFILE=server` picks `env/server.env`. With nothing set, the machine's own
hostname is tried — `env/desktop-gfaap80.env`, lowercased — and if that does not
exist, no profile is loaded and only `common.env` and `.env` apply.

The service prints which files it loaded at start-up. That is deliberate: an
evening was lost to a port set in one PowerShell window and not another, and a
configuration that will not say where a value came from is a configuration that
will eventually be argued with.

## Why `.env` is not committed

It was, and that was two problems in one file. It carried live SQL Server and
BrightHR credentials into the repository, and it meant a `git merge` on a second
machine would overwrite that machine's own settings with the first machine's.
A single file cannot be both "the same everywhere" and "different per machine".
