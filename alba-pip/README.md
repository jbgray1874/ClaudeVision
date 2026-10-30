# Alba PIP — demo site

The nine prospect-demo screens, built to the approved designs, plus the design system that
produced them.

## The nine URLs

Each screen is its own page, numbered in **demo-script order**. Serve this directory from any
static host and the URLs are:

| # | URL | Screen | Built from |
|---|-----|--------|------------|
| 1 | `/01-portfolio-command-centre.html`   | Portfolio Command Centre           | `Alba screen1.png` |
| 2 | `/02-revenue-performance.html`        | NovaTech Revenue Performance       | `Alba screen7.png` |
| 3 | `/03-revenue-risk-investigation.html` | Revenue Risk Investigation         | `Alba screen 5.png` |
| 4 | `/04-revenue-protection-plan.html`    | Revenue Protection Plan            | `Alba screen8.png` |
| 5 | `/05-exception-report.html`           | Portfolio Performance Exception Report | `Alba screen9.png` |
| 6 | `/06-opportunity-radar.html`          | Opportunity Radar                  | `Alba screen2.png` |
| 7 | `/07-customer-expansion.html`         | Customer Expansion                 | `Alba screen3.png` |
| 8 | `/08-commercial-action-plan.html`     | Commercial Action Plan             | `Alba screen4.png` |
| 9 | `/09-growth-opportunity-brief.html`   | Growth Opportunity Brief           | `Alba screen6.png` |

`/index.html` lists all nine and is the demo runner.

> **The screenshot filenames are not in script order.** Only `screen1.png` matches its script
> number. The URLs follow the **script**, because that is the order the demo is delivered in. The
> "built from" column exists so the two can always be reconciled.

Arrow keys move between screens during the demo; `Esc` returns to the index.

## Running it locally

```bash
cd alba-pip
python3 -m http.server 8080
# → http://localhost:8080
```

No build step, no dependencies, no server-side code.

## The design system

`assets/alba.css` is the single source of truth for the whole site. Every colour, radius and type
face is a CSS custom property declared once at the top; change a token there and every screen
follows. Nothing below the token block hard-codes a colour.

| Token | Value | Used for |
|-------|-------|----------|
| `--bg` | `#0a0a0b` | page ground |
| `--surface` | `#121214` | panels |
| `--line` | `#26262b` | panel borders |
| `--accent` | `#e8a33d` | brand, primary action, active nav |
| `--ok` | `#4ec97f` | healthy, recovery, upside |
| `--bad` | `#e8544f` | critical, risk, decline |
| `--warn` | `#e8a33d` | attention — deliberately the same as `--accent` |
| `--paper` | `#f7f4ec` | the report documents |

Two typefaces do the work: **Inter** for the application, **Spectral** for the report documents.
The contrast is the point — the dark UI is a working tool, the cream serif page is a document you
would put in front of an investment committee. Both have full fallback stacks, so the site does not
break if webfonts are blocked.

### Component classes

`.kpi` · `.panel` · `.pill` · `.sig` (evidence row) · `.deltas` (before → after metric list) ·
`.bridge` (recovery path) · `.timeline` · `.sheet` (the cream document) · `.rank` · `.who` (owner
chip) · `.provenance` (the footer strip of source chips).

The `.provenance` strip appears on most panels by design: every screen states what it was
calculated from and when it was refreshed, which is the demo's core claim — the AI is not a black
box.

## Shared chrome

`assets/alba.js` injects the top bar and the icon rail into every screen, so the nine cannot drift
apart. A screen declares only its content plus three attributes on `<body>`:

```html
<body data-section="portfolio" data-rail="0" data-screen="1">
```

- `data-section` — which top-nav item is active
- `data-rail` — which rail icon is active (0-based)
- `data-screen` — its number in the demo script, which drives the keyboard pager

## Porting the look to the rest of the site

Copy `assets/alba.css` and use the tokens. The palette, the component classes and the chrome are
independent of any framework — they are plain CSS and one small vanilla-JS file, so they carry into
a static site, a templated backend or a component framework without translation.
