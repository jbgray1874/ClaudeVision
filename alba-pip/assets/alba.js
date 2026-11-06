/* ============================================================================
   ALBA PIP — shared chrome.
   Every screen declares only its content. The top bar, the icon rail and the
   demo pager are injected here so the nine screens cannot drift apart.

   A screen sets, on <body>:
     data-section = portfolio | intelligence | actions | reports   (active nav)
     data-rail    = index of the active rail icon (0-based)
     data-screen  = its number in the DEMO SCRIPT order, 1-9
   ========================================================================== */
(function () {
  "use strict";

  var NAV = [
    { id: "portfolio",    label: "Portfolio",    href: "01-portfolio-command-centre.html" },
    { id: "intelligence", label: "Intelligence", href: "06-opportunity-radar.html" },
    { id: "actions",      label: "Actions",      href: "08-commercial-action-plan.html" },
    { id: "reports",      label: "Reports",      href: "05-exception-report.html" }
  ];

  var RAIL = ["▦", "◫", "◎", "◍", "▤", "◔", "▩", "⚙", "?"];

  /* Demo-script order. NOTE: this is NOT the order of the source screenshot
     filenames — screen1.png is script 1, but screen7.png is script 2, and so
     on. The script order is the one that matters, so it is the one used for
     the URLs and for the pager. */
  var SCREENS = [
    { n: 1, slug: "01-portfolio-command-centre",  name: "Portfolio Command Centre" },
    { n: 2, slug: "02-revenue-performance",       name: "NovaTech Revenue Performance" },
    { n: 3, slug: "03-revenue-risk-investigation",name: "Revenue Risk Investigation" },
    { n: 4, slug: "04-revenue-protection-plan",   name: "Revenue Protection Plan" },
    { n: 5, slug: "05-exception-report",          name: "Portfolio Performance Exception Report" },
    { n: 6, slug: "06-opportunity-radar",         name: "Opportunity Radar" },
    { n: 7, slug: "07-customer-expansion",        name: "Customer Expansion" },
    { n: 8, slug: "08-commercial-action-plan",    name: "Commercial Action Plan" },
    { n: 9, slug: "09-growth-opportunity-brief",  name: "Growth Opportunity Brief" }
  ];

  function el(tag, cls, html) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (html != null) n.innerHTML = html;
    return n;
  }

  function topbar(section) {
    var bar = el("div", "topbar");

    var logo = el("div", "logo");
    logo.appendChild(el("div", "mark", "AP"));
    logo.appendChild(el("div", "name", "ALBA PIP"));
    bar.appendChild(logo);

    var nav = el("nav", "nav");
    NAV.forEach(function (item) {
      var a = el("a", item.id === section ? "on" : "", item.label);
      a.href = item.href;
      nav.appendChild(a);
    });
    bar.appendChild(nav);

    var fund = el("div", "fund");
    fund.appendChild(el("span", "", "Northstar Growth Fund III"));
    fund.appendChild(el("span", "chev", "▼"));
    bar.appendChild(fund);

    bar.appendChild(el("div", "avatar", "GM"));
    return bar;
  }

  function rail(active) {
    var r = el("aside", "rail");
    RAIL.forEach(function (glyph, i) {
      r.appendChild(el("i", i === active ? "on" : "", glyph));
    });
    r.appendChild(el("div", "spacer"));
    var back = el("i", "", "›");
    back.title = "All screens";
    back.onclick = function () { location.href = "index.html"; };
    r.appendChild(back);
    return r;
  }

  /* Prev / next through the nine screens, so the demo can be driven from the
     keyboard rather than from the address bar. */
  function pager(current) {
    var idx = current - 1;
    var prev = SCREENS[idx - 1];
    var next = SCREENS[idx + 1];

    document.addEventListener("keydown", function (e) {
      if (e.target && /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
      if (e.key === "ArrowRight" && next) location.href = next.slug + ".html";
      if (e.key === "ArrowLeft" && prev) location.href = prev.slug + ".html";
      if (e.key === "Escape") location.href = "index.html";
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var body = document.body;
    if (body.hasAttribute("data-runner")) return;   /* the index page has no chrome */

    var section = body.getAttribute("data-section") || "portfolio";
    var railIdx = parseInt(body.getAttribute("data-rail") || "0", 10);
    var screen  = parseInt(body.getAttribute("data-screen") || "0", 10);

    var content = el("main", "main");
    while (body.firstChild) content.appendChild(body.firstChild);

    var shell = el("div", "shell");
    shell.appendChild(rail(railIdx));
    shell.appendChild(content);

    body.appendChild(topbar(section));
    body.appendChild(shell);

    if (screen) pager(screen);
  });

  window.ALBA_SCREENS = SCREENS;
})();
