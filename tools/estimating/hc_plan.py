"""Hotel Chocolat: one estimate per product, planned from what the drawings say.

plan  : reads the pack and the estimating service's run list (GET only), writes a readable
        plan and a JSON plan. Submits nothing and writes nothing to the share.
review: reads THAT JSON plan, each product's finished run and its workbook, and writes the review
        packs (one workbook per pack, a tab per product), the master price schedule and the signage
        schedule to the output folder. Reads workbooks only: nothing is re-priced, submitted or
        written to the share.
queue : reads THAT JSON plan, re-checks every product's source fingerprint, skips products
        already estimated (unless rerun), and submits the rest in plan order. A product with a
        run queued or running is never submitted again, rerun or not. since=<YYYY-MM-DD HH:MM>
        makes a result queued before that time not count as estimated (a release since). A
        submit that does not answer is checked against the run list before it is called
        anything: a slow answer is not a refusal.
        FAIL CLOSED: both services must answer with their whole history (fewer runs than the
        list limit) or nothing more is submitted. A live run of the same plan fingerprint OR
        the same drawing number blocks a submit. release=<file> (written by the release step
        once the build is verified LOADED) makes a finished run count as done only when its
        own log shows that build, or, where its log names no build, when it was queued after
        the verified release. Every attempt is journalled beside the plan, and an earlier
        UNSURE submit is reconciled against the complete lists before anything is sent again.
        Exit code 0 only when nothing was held, refused or left uncertain.

Folders are weak evidence in this pack. A file belongs to a product when a drawing of that
product names it (the BOM references, followed through the whole pack), or when it sits in
the product's folder with nothing showing it belongs elsewhere. A file can serve several
products. A file leaves a product only on positive evidence: it is another product's top
drawing and nothing in this product names it, or its sheet lives only in another product
that names it. Every file in the pack is accounted for at the end.
"""
import sys, os, re, json, hashlib, pathlib, urllib.request, urllib.error, collections, datetime, time, subprocess

# PATHS OVER 260 CHARACTERS (26 Nov 2026). Three shelving folders sit 260-261 characters deep on
# the share; PowerShell lists them, Windows' classic file calls do not, and the plan silently came
# out 32 products of 35. Every read goes through the long-path form; every path shown or submitted
# is the ordinary one.
def long_path(p):
    s = str(p)
    if os.name != 'nt' or s.startswith('\\\\?\\'):
        return s
    if s.startswith('\\\\'):
        return '\\\\?\\UNC\\' + s[2:]
    return '\\\\?\\' + os.path.abspath(s)

def short_path(p):
    s = str(p)
    if s.startswith('\\\\?\\UNC\\'):
        return '\\\\' + s[8:]
    if s.startswith('\\\\?\\'):
        return s[4:]
    return s

TOO_LONG = 260

mode = sys.argv[1]
if mode == 'plan':
    try:
        import pymupdf as fitz
    except ImportError:
        import fitz  # Only plan mode reads PDFs; queue mode verifies stored fingerprints.
    pack_root, out_dir = pathlib.Path(long_path(sys.argv[2])), pathlib.Path(sys.argv[3])
    _rest = sys.argv[4:]
    _only = next((a for a in _rest if not a.startswith('expect=')), '')
    only = set(a.strip().upper().replace('.', '').replace('-', '') for a in _only.split(',') if a.strip())
    # How many files the share holds by another reader's count (PowerShell's), to hold this one to.
    expected = next((int(a[7:]) for a in _rest if a.startswith('expect=') and a[7:].isdigit()), None)
elif mode == 'review':
    plan_file, out_dir = pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])
    books_dir = next((a[6:] for a in sys.argv[4:] if a.startswith('books=') and a[6:]), '')
else:
    plan_file, rerun = pathlib.Path(sys.argv[2]), (len(sys.argv) > 3 and sys.argv[3] == 'rerun')
    _since = next((a[6:].strip() for a in sys.argv[4:] if a.startswith('since=')), '')
    since = datetime.datetime.strptime(_since, '%Y-%m-%d %H:%M').timestamp() if _since else 0.0
    _release = next((a[8:].strip() for a in sys.argv[4:] if a.startswith('release=') and a[8:].strip()), '')
    scope_helper = next((a[13:] for a in sys.argv[4:] if a.startswith('scope_helper=')), '')
    release_build = ''
    if _release:
        _rec = json.loads(pathlib.Path(_release).read_text(encoding='utf-8-sig'))
        release_build = str(_rec.get('build') or '')[:7]
        since = float(_rec.get('loaded_verified_at') or 0)
        if len(release_build) < 7 or not since:
            raise SystemExit('NOT QUEUED: the release record names no verified build and load time.')

SERVICES = tuple(os.environ.get('HC_SERVICES', 'http://localhost:8071,http://localhost:8072').split(','))
KEY = os.environ.get('HC_KEY', '')
NAME_REF = re.compile(r'nc1-([a-ln-z])(\d{5})', re.I)
DXF_REF = re.compile(r'(?<![A-Z0-9])([A-LN-Z])[.\-](\d{5})(?![0-9])', re.I)
TEXT_REF = re.compile(r'(?<![A-Z0-9])([A-LN-Z])[.\-]?(\d{5})(?![0-9])', re.I)
DRAWING_EXT = ('.pdf', '.dxf', '.dwg')
PACKS = [
    ('1 Perimeter panels and infills', r'wall panel|infill panel'),
    ('2 Perimeter shelving', r'shelf|shelving'),
    ('3 Perimeter battens, end caps and accessories', r'batten|lighting rip|end capping|\brsb\b|hook'),
    ('4 Storage cupboards', r'cupboard'),
    ('5 Cash desks', r'cash desk'),
    ('6 Wall of Chocolate layouts', r'wall of chocolate'),
    ('7 Social tables and midfloor', r'social table|midfloor unit'),
    ('8 Plinths and column planter', r'plinth|planter|ballast'),
]

def get_json(url):
    req = urllib.request.Request(url, headers={'X-SDI-Key': KEY} if KEY else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode('utf-8'))

LIMIT = int(os.environ.get('HC_RUN_LIMIT') or 500)
FINISHED = ('done', 'error', 'failed', 'cancelled', 'canceled', 'stopped', 'abandoned', 'complete', 'completed')
BY_DRAWING = {}

def dkey(value):
    return re.sub(r'[^A-Z0-9]', '', str(value or '').upper())

def existing_runs(strict=None):
    """Every Hotel Chocolat run either service still knows, keyed by source fingerprint; every
    run of any client by drawing number in BY_DRAWING. In queue mode the history must be whole:
    a service that does not answer, or answers with a full page, stops the queue."""
    strict = (mode == 'queue') if strict is None else strict
    found = {}
    answered = 0
    gaps = []
    BY_DRAWING.clear()
    for s in SERVICES:
        try:
            runs = get_json(s + '/api/estimate?limit=%d' % LIMIT).get('runs', [])
            answered += 1
        except Exception as e:
            gaps.append('%s did not answer (%s)' % (s, type(e).__name__))
            continue
        if len(runs) >= LIMIT:
            gaps.append('%s returned %d runs, its limit, so older runs may be missing' % (s, len(runs)))
        for r in runs:
            d = dkey(r.get('drawing_number'))
            if d:
                lst = BY_DRAWING.setdefault(d, [])
                prior = next((e for e in lst if e.get('run_id') == r.get('run_id')), None)
                if prior is None:
                    lst.append(dict(r))
                elif str(prior.get('status')).lower() != str(r.get('status')).lower():
                    # THE SAME RUN, TWO STATUSES: reconciled to live if either service says live.
                    prior['status_conflict'] = sorted({str(prior.get('status')), str(r.get('status'))})
                    if str(r.get('status')).lower() not in FINISHED:
                        prior['status'] = r.get('status')
            m = re.search(r'\[hc:([0-9a-f]{12})\]', str(r.get('job_title') or ''))
            if m and str(r.get('client') or '').lower().startswith('hotel'):
                lst = found.setdefault(m.group(1), [])
                prior = next((e for e in lst if e['run_id'] == r.get('run_id')), None)
                if prior is None:
                    # Review needs the actual price, deliverables and output folder, not
                    # just the three fields queue deduplication happened to consume.
                    lst.append(dict(r))
                elif str(prior.get('status')).lower() != str(r.get('status')).lower():
                    prior['status_conflict'] = sorted({str(prior.get('status')), str(r.get('status'))})
                    if str(r.get('status')).lower() not in FINISHED:
                        prior['status'] = r.get('status')
    if strict and gaps:
        raise SystemExit('NOT QUEUED: the run history is incomplete, so a duplicate cannot be ruled out: '
                         + '; '.join(gaps) + '. Nothing further was submitted.')
    if not answered and (mode == 'queue' or (mode == 'review' and not books_dir)):
        raise SystemExit('NOT PROCESSED: neither service run list is reachable. No submission or review export was made.')
    return found

def ref_of(p):
    m = NAME_REF.search(p.name)
    return (m.group(1).upper() + m.group(2)) if m else None

def dotted(r):
    return '%s.%s' % (r[0], r[1:])

def sha1(p):
    h = hashlib.sha1()
    with open(long_path(p), 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()

def fingerprint(root, title, files):
    h = hashlib.sha256((root + '|' + title).encode('utf-8'))
    for f in sorted(files, key=lambda x: (x['ref'] or '', x['name'], x['sha1'])):
        h.update(('%s|%s|%d\n' % (f['name'], f['sha1'], f['size'])).encode('utf-8'))
    return h.hexdigest()[:12]

def pack_of(title):
    for name, rx in PACKS:
        if re.search(rx, title, re.I):
            return name
    return 'UNASSIGNED PACK'

def clean_title(name):
    return re.sub(r'^\s*\d+[A-Z]?\.\s*', '', name).strip()

if mode == 'plan':
    stamp = datetime.datetime.now().strftime('%Y-%m-%d %H%M')
    every = sorted(p for p in pack_root.rglob('*') if p.is_file())
    drawing_root = pack_root / 'Drawing'
    rel = lambda p: str(p.relative_to(pack_root))
    def category(p):
        r = rel(p).lower()
        if 'brief to supplier' in r:
            return 'brief'
        if 'signage' in r:
            return 'signage'
        if p.suffix.lower() in DRAWING_EXT and ref_of(p):
            return 'drawing'
        return 'context'
    info = {p: {'path': short_path(p), 'name': p.name, 'rel': rel(p), 'ref': ref_of(p), 'size': p.stat().st_size,
                'category': category(p)} for p in every}
    for p, i in info.items():
        i['sha1'] = sha1(p) if i['size'] else ''
    by_ref = collections.defaultdict(list)
    for p, i in info.items():
        if i['category'] == 'drawing':
            by_ref[i['ref']].append(p)

    text_cache = {}
    page_text = {}
    def mentions_of_file(p):
        if p not in text_cache:
            found = set()
            if p.suffix.lower() == '.pdf' and info[p]['size']:
                try:
                    with fitz.open(short_path(p) if len(short_path(p)) < TOO_LONG else str(p)) as doc:
                        page_text[p] = '\n'.join(pg.get_text() for pg in doc)
                    for m in TEXT_REF.finditer(page_text[p]):
                        found.add(m.group(1).upper() + m.group(2))
                except Exception:
                    pass
            # A DRAWING WHOSE PDF HAS NO TEXT LAYER STILL NAMES ITS PARTS IN ITS DXF (26 Nov 2026).
            # B.34493's PDF is outlines only; its DXF's parts list names A.34494 and D.34496, the
            # ballast plate it takes four of. A DXF's handles are hex, so here the separator is
            # required: B.34493, never B34493.
            elif p.suffix.lower() == '.dxf' and info[p]['size']:
                try:
                    with open(long_path(p), 'rb') as fh:
                        raw = fh.read().decode('latin-1')
                    for m in DXF_REF.finditer(raw):
                        found.add(m.group(1).upper() + m.group(2))
                except Exception:
                    pass
            text_cache[p] = found
        return text_cache[p]
    # A shelf's assembly lists its members by stock number, not drawing number.
    # Read each PDF once, then join ONLY a unique own-part code from its title.
    stock_claims = collections.defaultdict(set)
    for p in every:
        if info[p]['category'] == 'drawing' and p.suffix.lower() == '.pdf':
            mentions_of_file(p)
            head = page_text.get(p, '').split('ITEM NO.')[0]
            codes = set(re.findall(r'(?i)(?:FINISHED\s+)?PART\s+NO\.?\s*[:\-\s]*(\d{7,8})(?!\d)', head))
            if len(codes) == 1:
                stock_claims[next(iter(codes))].add(info[p]['ref'])
    for p, text in page_text.items():
        for stock in set(re.findall(r'(?<!\d)\d{7,8}(?!\d)', text)):
            refs = stock_claims.get(stock, set())
            if len(refs) == 1:
                text_cache[p].update(refs)
    def mentions_of_ref(r):
        out = set()
        for p in by_ref.get(r, []):
            out |= mentions_of_file(p)
        return (out & set(by_ref)) - {r}

    # 1. Candidate products from the folders (a working list), with shared libraries.
    def has_drawings(d):
        return any(info.get(f, {}).get('category') == 'drawing' for f in d.iterdir() if f.is_file())
    folders, libraries, layouts = [], set(), []
    for d in sorted(x for x in drawing_root.rglob('*') if x.is_dir()):
        if 'signage' in str(d).lower():
            continue
        own = [f for f in d.iterdir() if f.is_file()]
        if not own:
            continue
        subs = [s for s in d.iterdir() if s.is_dir() and has_drawings(s)]
        if subs and has_drawings(d):
            libraries.add(d)
            continue
        if not has_drawings(d):
            layouts.append(d)
            continue
        folders.append(d)

    # 2. Each candidate's top drawing: named by none of its folder's other drawings.
    products = []
    for d in folders:
        own_refs = sorted({info[f]['ref'] for f in d.iterdir() if f.is_file() and info.get(f, {}).get('ref')})
        named = set()
        for r in own_refs:
            named |= mentions_of_ref(r)
        tops = [r for r in own_refs if r not in named]
        described = {info[f]['ref'] for f in d.iterdir() if f.is_file() and info.get(f, {}).get('ref') and '_' in f.stem}
        def elsewhere(r):
            # Filed in another candidate product's folder too: a shared or foreign sheet.
            return any(f.parent != d and f.parent in folders for f in by_ref.get(r, []))
        def score(r):
            # Unique to this folder, then names the most of its neighbours, then has a
            # described file name ("nc1-b33519_3 Person Cash Desk"), then the lowest number.
            return (not elsewhere(r), len(mentions_of_ref(r) & set(own_refs)), r in described, -int(r[1:]))
        warn = []
        pool = tops or own_refs
        root = max(pool, key=score)
        if len(tops) != 1:
            warn.append('top drawing chosen as %s from %s (%s): unique to this folder and naming the most of its drawings'
                        % (dotted(root), ', '.join(dotted(t) for t in pool),
                           'none unnamed' if not tops else 'several unnamed'))
        title = clean_title(d.name)
        if d.parent in libraries:
            title = clean_title(d.parent.name) + ' - ' + title
        products.append({'folder': d, 'root': root, 'title': title, 'warnings': warn})
    roots = {p['root']: p for p in products}

    # 3. Each product's drawings: its folder plus everything its drawings name, through the pack.
    for prod in products:
        tree, todo = set(), [prod['root']]
        while todo:
            r = todo.pop()
            if r in tree:
                continue
            tree.add(r)
            for m in mentions_of_ref(r):
                if m in roots and m != prod['root']:
                    prod['warnings'].append('its drawings name %s, the top drawing of %s: included as a component; check it is not also priced on its own' % (dotted(m), roots[m]['title']))
                todo.append(m)
        prod['tree'] = tree
        missing = set()
        for r in tree:
            for p in by_ref.get(r, []):
                missing |= {m for m in mentions_of_file(p) if m not in by_ref}
        if missing:
            prod['missing'] = sorted(missing)
            prod['warnings'].append('named by its drawings but not in the pack: %s (priced by allowance; ask Design)'
                                    % ', '.join(dotted(m) for m in sorted(missing)))
    dup_roots = collections.Counter(p['root'] for p in products)
    for prod in products:
        if dup_roots[prod['root']] > 1:
            prod['warnings'].append('ANOTHER PRODUCT HAS THE SAME TOP DRAWING %s: check the plan before queueing' % dotted(prod['root']))
    pdf_homes = collections.defaultdict(set)
    for prod in products:
        for f in prod['folder'].iterdir():
            if f.is_file() and info.get(f, {}).get('ref') and f.suffix.lower() == '.pdf':
                pdf_homes[info[f]['ref']].add(prod['root'])
    transfers = []
    for prod in products:
        d = prod['folder']
        chosen, notes = {}, []
        local = [f for f in d.iterdir() if f.is_file()]
        if d.parent in libraries:
            local += [f for f in d.parent.iterdir() if f.is_file()]
        for f in local:
            i = info.get(f)
            if not i or i['category'] not in ('drawing', 'context'):
                continue
            r = i['ref']
            if r and r not in prod['tree']:
                if r in roots and roots[r] is not prod:
                    transfers.append('%s: %s left out - it is the top drawing of %s and no drawing of %s names it'
                                     % (prod['title'], f.name, roots[r]['title'], prod['title']))
                    continue
                owners = [o for o in products if o is not prod and r in o['tree']]
                if owners and f.suffix.lower() != '.pdf' and prod['root'] not in pdf_homes.get(r, set()):
                    transfers.append('%s: %s moved to %s, whose drawings name it'
                                     % (prod['title'], f.name, ', '.join(o['title'] for o in owners)))
                    continue
                if not owners:
                    notes.append('%s is in its folder but no drawing names it: kept here' % f.name)
            chosen[f] = i
        for r in prod['tree']:
            for f in by_ref.get(r, []):
                if f not in chosen and not any(info[c]['ref'] == r and info[c]['sha1'] == info[f]['sha1']
                                               and c.suffix.lower() == f.suffix.lower() for c in chosen):
                    chosen[f] = info[f]
        files, empties, seen = [], [], set()
        for f, i in sorted(chosen.items(), key=lambda kv: kv[1]['rel']):
            if not i['size']:
                empties.append(i['name'])
                continue
            key = (i['ref'] or i['name'], f.suffix.lower(), i['sha1'])
            if key in seen:
                continue
            seen.add(key)
            files.append(i)
        prod['files'], prod['empties'] = files, empties
        deep = [i['name'] for i in files if len(i['path']) >= TOO_LONG]
        if deep:
            prod['warnings'].append('path of %d character(s) or more, which the engine may not open: %s '
                                    '(shorten the folder names)' % (TOO_LONG, ', '.join(deep)))
        if empties:
            prod['warnings'].append('%d empty file(s) supplied, not readable: %s' % (len(empties), ', '.join(empties)))
        prod['warnings'] += notes

    # 4. A product with nothing readable is priced from its brief and its family, not dropped.
    for prod in products:
        prod['brief'] = None
        if not prod['files']:
            fam = [o['title'] for o in products if o is not prod and pack_of(o['title']) == pack_of(prod['title'])]
            own_refs = sorted({info[f]['ref'] for f in info if info[f]['ref'] and f.parent == prod['folder']
                               and f.name in prod['empties']})
            elsewhere = []
            for r in own_refs:
                good = sorted({f.parent.name for f in by_ref.get(r, []) if info[f]['size']})
                if good:
                    elsewhere.append('%s (readable in: %s)' % (dotted(r), '; '.join(good)))
            prod['brief'] = ('Hotel Chocolat %s (drawing %s). Every drawing supplied for this product is empty (%s), so '
                             'it is priced as an allowance: the same construction, materials and finish as its family '
                             '(%s), scaled to the size in its name.%s State every assumption.'
                             % (prod['title'], dotted(prod['root']), ', '.join(dotted(r) for r in own_refs) or 'none named',
                                '; '.join(fam),
                                (' The same drawing numbers are readable elsewhere in the pack: %s.' % '; '.join(elsewhere))
                                if elsewhere else ''))
            if elsewhere:
                prod['warnings'].append('readable copies elsewhere: ' + '; '.join(elsewhere))
            prod['warnings'].append('no readable drawings: priced from a brief by analogy with its family (allowance)')

    already = existing_runs()
    plan = []
    for prod in sorted(products, key=lambda p: -len(p['files'])):
        fp = fingerprint(prod['root'], prod['title'], prod['files'])
        ex = already.get(fp, [])
        plan.append({'drawing': dotted(prod['root']), 'title': prod['title'], 'pack': pack_of(prod['title']),
                     'fingerprint': fp, 'files': [{k: i[k] for k in ('path', 'name', 'ref', 'size', 'sha1')} for i in prod['files']],
                     'empty_files': prod['empties'], 'brief': prod['brief'], 'warnings': prod['warnings'],
                     'existing_runs': ex, 'selected': (not only) or prod['root'] in only})

    # 5. Accounting: every file in the pack, in exactly one bucket.
    used = collections.Counter()
    for item in plan:
        for i in item['files']:
            used[i['path']] += 1
    buckets = collections.OrderedDict((k, []) for k in ('in one product', 'shared by several products', 'empty (warned)',
                                                       'signage (separate signage schedule)', 'brief / reference (not product)',
                                                       'context / layout (not priced)', 'drawing not used by any product'))
    empty_paths = {i['path'] for i in info.values() if i['size'] == 0}
    for p, i in info.items():
        if i['category'] == 'signage':
            buckets['signage (separate signage schedule)'].append(i['rel'])
        elif i['category'] == 'brief':
            buckets['brief / reference (not product)'].append(i['rel'])
        elif i['path'] in empty_paths:
            buckets['empty (warned)'].append(i['rel'])
        elif used[i['path']] > 1:
            buckets['shared by several products'].append(i['rel'])
        elif used[i['path']] == 1:
            buckets['in one product'].append(i['rel'])
        elif i['category'] == 'context':
            buckets['context / layout (not priced)'].append(i['rel'])
        else:
            dup = any(info[q]['sha1'] == i['sha1'] and used[info[q]['path']] for q in by_ref.get(i['ref'], []))
            (buckets['in one product'] if dup else buckets['drawing not used by any product']).append(i['rel'] + (' (identical copy of a file in use)' if dup else ''))

    lines = ['Hotel Chocolat estimate plan, %s' % stamp, 'Pack: %s' % short_path(pack_root), '']
    if expected is not None and expected != len(every):
        lines += ['!!! THE SHARE HOLDS %d FILES AND THIS PLAN READ %d. Files are missing from this plan: do not '
                  'queue it. Send this plan to be checked.' % (expected, len(every)), '']
    lines += [
             '%d products, %d selected for this run' % (len(plan), sum(1 for p in plan if p['selected'])), '']
    for n, item in enumerate(plan, 1):
        state = ('ALREADY RUN ' + ', '.join('%s (%s)' % (e['run_id'], e['status']) for e in item['existing_runs'])) if item['existing_runs'] else ''
        lines.append('%2d. %-8s %-50s %-3d files  [%s] %s%s' % (n, item['drawing'], item['title'][:50], len(item['files']),
                     item['pack'][:1], 'BRIEF ' if item['brief'] else '', state))
        for w in item['warnings']:
            lines.append('        ! ' + w)
    if transfers:
        lines += ['', 'Files left out of or moved between products (with the evidence):'] + ['  ' + t for t in transfers]
    lines += ['', 'Packs:'] + ['  %s: %d' % (name, sum(1 for p in plan if p['pack'] == name)) for name, _ in PACKS]
    if any(p['pack'] == 'UNASSIGNED PACK' for p in plan):
        lines.append('  UNASSIGNED PACK: %d' % sum(1 for p in plan if p['pack'] == 'UNASSIGNED PACK'))
    lines += ['', 'Every file in the pack (%d):' % len(info)]
    for k, v in buckets.items():
        lines.append('  %-40s %d' % (k, len(v)))
    lines.append('  %-40s %d' % ('accounted for', sum(len(v) for v in buckets.values())))
    for k in ('drawing not used by any product', 'context / layout (not priced)', 'empty (warned)'):
        if buckets[k]:
            lines += ['', k + ':'] + ['  ' + x for x in buckets[k]]
    out_dir.mkdir(parents=True, exist_ok=True)
    base = out_dir / ('Hotel Chocolat plan ' + stamp)
    json_path = base.with_suffix('.json')
    json_path.write_text(json.dumps({'created': stamp, 'pack_root': short_path(pack_root),
                                     'files_read': len(every), 'files_expected': expected, 'products': plan,
                                     'accounting': {k: v for k, v in buckets.items()}}, indent=1), encoding='utf-8')
    base.with_suffix('.txt').write_text('\n'.join(lines), encoding='utf-8')
    print('\n'.join(lines))
    print('\nPlan saved: %s\nJSON plan:  %s' % (base.with_suffix('.txt'), json_path))
    print('Nothing was submitted.')
elif mode == 'queue':
    data = json.loads(plan_file.read_text(encoding='utf-8'))
    def check_preservation():
        scope = data.get('preservation_scope')
        if not scope:
            return None  # Existing unscoped plans retain their existing behaviour.
        if not scope_helper or not pathlib.Path(scope_helper).is_file():
            raise SystemExit('NOT QUEUED: the scoped plan requires its preservation checker.')
        checked = subprocess.run([sys.executable, '-I', scope_helper, 'check', '--scope', scope,
                                  '--plan', str(plan_file)], capture_output=True, text=True)
        if checked.returncode:
            raise SystemExit('NOT QUEUED: original-result preservation check failed. ' +
                             checked.stdout.strip() + ' ' + checked.stderr.strip())
        if not release_build:
            raise SystemExit('NOT QUEUED: a scoped correction requires a verified release record.')
        expected = {str(x.get('runner') or x.get('runner_id') or x.get('id') or '')
                    for x in _rec.get('runners', [])}
        if not expected or '' in expected:
            raise SystemExit('NOT QUEUED: release record must identify every expected runner.')
        seen = set()
        try:
            for service in SERVICES:
                health = get_json(service + '/api/health')
                if not str(health.get('commit') or '').startswith(release_build):
                    raise ValueError('a service is not on the verified release')
                grid = get_json(service + '/api/estimate/runners')
                if not isinstance(grid.get('runners'), list):
                    raise ValueError('a runner list is missing')
                for runner in grid['runners']:
                    if runner.get('online') is not True:
                        continue
                    identity = str(runner.get('runner_id') or runner.get('id') or '')
                    build = str(runner.get('build') or '')
                    if (identity not in expected or not build.startswith(release_build)
                            or '+local edits' in build or runner.get('conflict')
                            or runner.get('process_count') != 1):
                        raise ValueError('an online runner has an unexpected identity, build or process state')
                    seen.add(identity)
            if seen != expected:
                raise ValueError('an expected runner is not online')
        except Exception as exc:
            raise SystemExit('NOT QUEUED: loaded-build verification failed: ' + str(exc))
        return json.loads(pathlib.Path(scope).read_text(encoding='utf-8-sig'))
    preserved = check_preservation()
    if data.get('files_expected') is not None and data['files_expected'] != data.get('files_read'):
        print('NOT QUEUED: this plan read %s of the %s files on the share, so products may be missing. '
              'Plan again; nothing was submitted.' % (data.get('files_read'), data['files_expected']))
        sys.exit(2)
    # Keep the original journal when the selected plan is frozen into a new folder.
    # Moving the plan must not hide an earlier uncertain submission.
    JOURNAL = pathlib.Path(preserved['historical_submission_journal']) if preserved else \
        plan_file.parent / 'Hotel Chocolat submissions.jsonl'
    UNSURE_WAIT_MIN = float(os.environ.get('HC_UNSURE_WAIT_MIN') if os.environ.get('HC_UNSURE_WAIT_MIN') is not None else 30)

    def journal(item, asked, result, run_id):
        with JOURNAL.open('a', encoding='utf-8') as f:
            f.write(json.dumps({'asked': asked, 'fingerprint': item['fingerprint'], 'drawing': item['drawing'],
                                'result': result, 'run_id': run_id}) + '\n')

    def journal_entries(fingerprint):
        if not JOURNAL.exists():
            return []
        out = []
        for line in JOURNAL.read_text(encoding='utf-8').splitlines():
            try:
                j = json.loads(line)
            except ValueError:
                continue
            if j.get('fingerprint') == fingerprint and j.get('result') == 'unsure':
                out.append(j)
        return out

    def run_build(run):
        m = re.search(r'\[build\] engine source: ([0-9a-f]{7,40})( \+local edits)?',
                      '\n'.join(str(x) for x in (run.get('log') or [])))
        return (m.group(1), bool(m.group(2))) if m else (None, None)

    if release_build:
        print('Release record: build %s verified loaded at %s' % (release_build, time.strftime('%d %b %H:%M', time.localtime(since))))
    already = existing_runs()
    done = sent = held = unsure = 0
    _digests = {}
    def digest(path):
        # One read per file per queue: the Wall of Chocolate products share 150 files.
        if path not in _digests:
            _digests[path] = sha1(path)
        return _digests[path]
    for item in data['products']:
        if not item['selected']:
            continue
        label = '%s  %s' % (item['drawing'], item['title'])
        if item['files']:
            print('checking %d file(s) of %s against the plan...' % (len(item['files']), label), flush=True)
        changed = [f['name'] for f in item['files'] if not os.path.exists(long_path(f['path']))
                   or os.path.getsize(long_path(f['path'])) != f['size'] or digest(f['path']) != f['sha1']]
        if changed:
            print('HELD    %s: files changed since the plan (%s); plan again' % (label, ', '.join(changed[:5])))
            held += 1
            continue
        check_preservation()
        # THE LIST AS IT IS NOW, not as it was when this queue started: a second queue window
        # started meanwhile, or a person on the Wall, may have submitted this product since.
        already = existing_runs()
        runs = list(already.get(item['fingerprint'], []))
        ids = {e.get('run_id') for e in runs}
        runs += [e for e in BY_DRAWING.get(dkey(item['drawing']), []) if e.get('run_id') not in ids]
        flying = [e for e in runs if str(e.get('status')).lower() not in FINISHED]
        if flying:
            print('IN FLIGHT %s: %s; not submitted again' % (label, ', '.join(
                '%s (%s%s)' % (e['run_id'], e['status'], ', status differs between services' if e.get('status_conflict') else '')
                for e in flying)))
            done += 1
            continue
        # AN EARLIER UNSURE SUBMIT IS RECONCILED FIRST, against the complete lists just read.
        waiting = False
        for j in journal_entries(item['fingerprint']):
            if any(float(e.get('queued_at') or 0) >= j['asked'] - 60 for e in runs):
                continue
            age_min = (time.time() - j['asked']) / 60
            if age_min < UNSURE_WAIT_MIN:
                print('HELD    %s: an earlier uncertain submit at %s is not on either complete run list yet; '
                      'queue again after %s' % (label, time.strftime('%H:%M', time.localtime(j['asked'])),
                                                time.strftime('%H:%M', time.localtime(j['asked'] + UNSURE_WAIT_MIN * 60))))
                waiting = True
                break
            print('NOTE    %s: the uncertain submit at %s never appeared on either complete run list in %d min; '
                  'it was not created' % (label, time.strftime('%H:%M', time.localtime(j['asked'])), age_min))
        if waiting:
            held += 1
            continue
        if release_build:
            live = []
            for e in runs:
                status = str(e.get('status')).lower()
                built, dirty = run_build(e)
                queued = float(e.get('queued_at') or 0)
                when = time.strftime('%d %b %H:%M', time.localtime(queued)) if queued else 'unknown time'
                if status not in ('done', 'complete', 'completed'):
                    verdict = 'does not count (%s)' % status
                elif built:
                    ok = built.startswith(release_build) and not dirty
                    verdict = ('counts: its log shows build %s' % built) if ok else \
                              ('does not count: its log shows build %s%s, not %s' % (built, ' +local edits' if dirty else '', release_build))
                    if ok:
                        live.append(e)
                elif queued >= since:
                    verdict = 'counts: no build in its log, queued %s after the verified release' % when
                    live.append(e)
                else:
                    verdict = 'does not count: no build in its log, queued before the verified release'
                print('  existing %s %s (%s, queued %s): %s' % (item['drawing'], e.get('run_id'), status, when, verdict))
        else:
            live = [e for e in runs if str(e.get('status')).lower() not in ('failed', 'error', 'stopped', 'cancelled')
                    and float(e.get('queued_at') or 0) >= since]
        if live and not rerun:
            print('SKIPPED %s: already run %s' % (label, ', '.join('%s (%s)' % (e['run_id'], e['status']) for e in live)))
            done += 1
            continue
        body = {'client': 'Hotel Chocolat', 'drawing_number': item['drawing'], 'units': 1,
                'job_title': '%s [hc:%s]' % (item['title'], item['fingerprint']),
                'files': [f['path'] for f in item['files']]}
        if item.get('brief'):
            body['enquiry_brief'] = item['brief']
            if not item['files']:
                body['method'] = 'llm'
        req = urllib.request.Request(SERVICES[0] + '/api/estimate', data=json.dumps(body).encode('utf-8'), method='POST',
                                     headers=dict({'Content-Type': 'application/json; charset=utf-8'}, **({'X-SDI-Key': KEY} if KEY else {})))
        asked = time.time()
        try:
            with urllib.request.urlopen(req, timeout=float(os.environ.get('HC_SUBMIT_TIMEOUT') or 600)) as r:
                run_id = json.loads(r.read().decode('utf-8')).get('run_id')
            print('QUEUED  %s  run %s' % (label, run_id), flush=True)
            journal(item, asked, 'queued', run_id)
            sent += 1
        except urllib.error.HTTPError as e:
            detail = e.read().decode('utf-8', 'replace') or str(e)
            print('REFUSED %s: %s' % (label, detail[:300]), flush=True)
            journal(item, asked, 'refused', None)
            held += 1
        except Exception as e:
            # NO ANSWER IS NOT NO. On 26 Nov a submit timed out and the run was there, running.
            found = []
            for _ in range(int(os.environ.get('HC_CONFIRM_TRIES') or 12)):
                found = [x for x in existing_runs().get(item['fingerprint'], [])
                         if float(x.get('queued_at') or 0) >= asked - 60]
                if found:
                    break
                time.sleep(float(os.environ.get('HC_CONFIRM_SLEEP') or 10))
            if found:
                print('QUEUED  %s  run %s (the service answered slowly; the run is on the list)'
                      % (label, found[0]['run_id']), flush=True)
                journal(item, asked, 'queued', found[0]['run_id'])
                sent += 1
            else:
                print('UNSURE  %s: %s, and no run for it is on the list yet. Queueing again reconciles it '
                      'first and holds the product until it appears or %d min pass.' % (label, e, UNSURE_WAIT_MIN), flush=True)
                journal(item, asked, 'unsure', None)
                unsure += 1
    check_preservation()
    print('%d queued, %d already run or in flight, %d held or refused, %d unsure' % (sent, done, held, unsure))
    if held or unsure:
        print('NOT ALL SUBMITTED CLEANLY: see the HELD / REFUSED / UNSURE lines above.')
        sys.exit(3)

else:
    # -- REVIEW: eight packs and one schedule, instead of 35 workbooks --
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    data = json.loads(plan_file.read_text(encoding='utf-8'))
    stamp = datetime.datetime.now().strftime('%Y-%m-%d %H%M')
    runs = existing_runs()

    def compact(ref):
        return re.sub(r'[^A-Z0-9]', '', str(ref or '').upper())

    def finished_run(fp):
        """The newest run of this product that finished with a workbook."""
        done = [r for r in runs.get(fp, []) if str(r.get('status')).lower() in ('done', 'complete', 'completed')]
        return max(done, key=lambda r: float(r.get('queued_at') or 0)) if done else None

    shelf = {}
    if books_dir:
        for b in pathlib.Path(long_path(books_dir)).rglob('*.xlsx'):
            if b.name.startswith('~$'):
                continue
            try:
                wb = openpyxl.load_workbook(str(b), data_only=True, read_only=True)
                drg = wb['Estimate']['D5'].value if 'Estimate' in wb.sheetnames else None
                wb.close()
            except Exception:
                continue
            if drg:
                key = compact(drg)
                if key not in shelf or b.stat().st_mtime > shelf[key].stat().st_mtime:
                    shelf[key] = b

    def cell_after(ws, label, width=40):
        """The first value to the right of the cell whose text starts with label."""
        for row in ws.iter_rows(max_col=width):
            for i, c in enumerate(row):
                if isinstance(c.value, str) and c.value.strip().startswith(label):
                    for d in row[i + 1:]:
                        if d.value not in (None, ''):
                            return d.value
        return None

    def read_book(path):
        wb = openpyxl.load_workbook(long_path(path), data_only=True)
        est = wb['Estimate'] if 'Estimate' in wb.sheetnames else None
        out = {'unit': None, 'material': None, 'labour': None, 'status': '', 'confirm': [], 'inputs': [],
               'summary': ''}
        if est is not None:
            out['drawing'] = est['D5'].value
            out['unit'] = cell_after(est, 'Total Unit Cost Price')
            out['material'] = cell_after(est, 'Total Material Cost')
            out['labour'] = cell_after(est, 'Total Labour Cost')
            out['status'] = str(est['H6'].value or '')
            taking = False
            for row in est.iter_rows(values_only=True):
                text = [str(v) for v in row if v not in (None, '')]
                if not text:
                    continue
                if text[0].startswith('OUTSTANDING ESTIMATOR INPUTS'):
                    taking = True
                    continue
                if taking and re.match(r'^\d+\.\s', text[0]):
                    out['inputs'].append(' | '.join(text))
        if 'AI Explanation' in wb.sheetnames:
            ai = wb['AI Explanation']
            rows = list(ai.iter_rows(values_only=True))
            head = next((i for i, r in enumerate(rows)
                         if r and str(r[0] or '').strip() == '#' and 'Kind' in [str(v) for v in r]), None)
            if head is not None:
                cols = [str(v or '') for v in rows[head]]
                for r in rows[head + 1:]:
                    if not r or r[0] in (None, '') or not str(r[0]).strip().isdigit():
                        break
                    out['confirm'].append({cols[k]: r[k] for k in range(len(cols)) if cols[k]})
            for r in rows:
                if r and str(r[0] or '').startswith('- What does a unit cost'):
                    out['summary'] = str(r[0])[2:]
                    break
        wb.close()
        return out

    def money(v):
        try:
            return round(float(v), 2)
        except (TypeError, ValueError):
            return None

    products = []

    def estimate_workbook(run, drawing):
        """Find the main, timestamped estimate; output_path is usually a directory."""
        if not run:
            return None
        candidates = []
        for deliverable in run.get('deliverables') or []:
            if not isinstance(deliverable, dict):
                continue
            path = deliverable.get('path')
            if path and re.search(r'_\d{8}_\d{6}\.xlsx$', str(path), re.I):
                candidates.append(path)
        output = run.get('output_path')
        if output and os.path.isfile(long_path(output)):
            candidates.append(output)
        elif output and os.path.isdir(long_path(output)):
            matches = [short_path(p) for p in pathlib.Path(long_path(output)).glob('*.xlsx')
                       if re.search(r'_\d{8}_\d{6}\.xlsx$', p.name)
                       and compact(re.sub(r'_\d{8}_\d{6}\.xlsx$', '', p.name, flags=re.I)) == compact(drawing)]
            # Do not take an arbitrary workbook from a mixed or multi-version folder.
            if len(matches) == 1:
                candidates += matches
        for path in dict.fromkeys(candidates):
            if os.path.isfile(long_path(path)):
                return path
        return None

    for item in data['products']:
        run = finished_run(item['fingerprint'])
        book, why = None, ''
        book = estimate_workbook(run, item['drawing'])
        if not book and compact(item['drawing']) in shelf:
            book = short_path(shelf[compact(item['drawing'])])
        live = [r for r in runs.get(item['fingerprint'], []) if str(r.get('status')).lower() in ('queued', 'running')]
        if not book:
            why = ('still %s' % live[0]['status']) if live else ('no finished run' if not run else 'workbook not found')
        facts = {}
        if book:
            try:
                facts = read_book(book)
                if facts.get('drawing') and compact(facts['drawing']) != compact(item['drawing']):
                    raise ValueError('workbook drawing does not match this product')
            except Exception as e:
                why = 'workbook unreadable: %s' % e
                book = None
                facts = {'unit': None, 'material': None, 'labour': None, 'status': '',
                         'confirm': [], 'inputs': [], 'summary': ''}
        if run and run.get('price_validated') is True and facts.get('unit') is None:
            for k, how in (('engine_price_gbp', 'the run record (engine price)'), ('llm_price_gbp', 'the run record (brief price)')):
                if run.get(k) not in (None, ''):
                    facts['unit'] = run[k]
                    facts['status'] = (facts.get('status') or '') + ' Price read from %s; its workbook gave none.' % how
                    break
        if run:
            quality = (run.get('quality') or {}).get('label') or (run.get('quality') or {}).get('state')
            if quality:
                facts['status'] = str(quality) + '. ' + (facts.get('status') or '')
        if why:
            facts['status'] = (facts.get('status') or '') + ' ' + why
        warn = [w for w in item.get('warnings', []) if 'no drawing names it: kept here' not in w]
        missing = [w.split(':', 1)[1].split('(')[0].strip() for w in warn if w.startswith('named by its drawings but not in the pack')]
        products.append({'item': item, 'run': run, 'book': book, 'why': why, 'facts': facts, 'warn': warn,
                         'missing': missing, 'basis': 'allowance from brief' if item.get('brief') else 'drawings'})

    hdr_font, hdr_fill = Font(bold=True, color='FFFFFF'), PatternFill('solid', fgColor='4F4F4F')
    def table(ws, top, headers, rows, widths=None):
        for j, h in enumerate(headers, 1):
            c = ws.cell(row=top, column=j, value=h)
            c.font, c.fill = hdr_font, hdr_fill
        for i, r in enumerate(rows, top + 1):
            for j, v in enumerate(r, 1):
                c = ws.cell(row=i, column=j, value=v)
                c.alignment = Alignment(wrap_text=True, vertical='top')
        for j, w in enumerate(widths or [], 1):
            ws.column_dimensions[get_column_letter(j)].width = w
        return top + len(rows) + 1

    def at_stake(p):
        total = 0.0
        for c in p['facts'].get('confirm', []):
            m = re.search(r'[\d,]+\.\d+', str(c.get('\u00a3 at stake') or ''))
            total += float(m.group(0).replace(',', '')) if m else 0.0
        return round(total, 2)

    out_dir.mkdir(parents=True, exist_ok=True)
    # 1. The master price schedule.
    master = openpyxl.Workbook()
    ws = master.active
    ws.title = 'Price schedule'
    ws['A1'] = 'Hotel Chocolat: master price schedule, %s' % stamp
    ws['A1'].font = Font(bold=True, size=14)
    ws['A2'] = ('Engine estimates for review, not quotations. Each price is the finished run\'s own unit cost; '
                'every assumption and open point is in its review pack.')
    rows = []
    for p in sorted(products, key=lambda p: (p['item']['pack'], p['item']['drawing'])):
        f = p['facts']
        rows.append([p['item']['pack'], p['item']['drawing'], p['item']['title'], money(f.get('unit')),
                     money(f.get('material')), money(f.get('labour')), p['basis'],
                     (f.get('status') or p['why'] or '')[:200], len(f.get('confirm', [])), at_stake(p) or None,
                     '; '.join(p['missing']) or None,
                     ', '.join(sorted({x['ref'] for x in p['item']['files'] if x.get('ref')})[:40]) or None,
                     (p['run'] or {}).get('run_id'), p['book']])
    end = table(ws, 4, ['Pack', 'Drawing', 'Product', 'Unit price \u00a3', 'Material \u00a3', 'Labour \u00a3', 'Basis', 'Status',
                        'Items to confirm', '\u00a3 at stake', 'Drawings named but not in the pack',
                        'Source drawings', 'Run', 'Workbook'], rows,
                [30, 10, 44, 12, 11, 11, 18, 50, 10, 11, 24, 40, 14, 60])
    priced = [r for r in rows if r[3] is not None]
    ws.cell(row=end + 1, column=3, value='%d of %d products priced' % (len(priced), len(rows))).font = Font(bold=True)
    ws.freeze_panes = 'A5'

    sig = master.create_sheet('Signage')
    sig['A1'] = 'Signage and graphics: a separate schedule, grouped by folder. Not estimated by the engine.'
    sig['A1'].font = Font(bold=True)
    signage = data.get('accounting', {}).get('signage (separate signage schedule)', [])
    table(sig, 3, ['Group', 'File', 'Price \u00a3', 'Supplier / basis', 'Notes'],
          [[str(pathlib.PureWindowsPath(r).parent.name), pathlib.PureWindowsPath(r).name, None, None, None]
           for r in sorted(signage)], [40, 60, 10, 30, 40])
    ctx = master.create_sheet('Context')
    ctx['A1'] = 'Context and layout drawings: roll-ups of the products above, not costed themselves.'
    ctx['A1'].font = Font(bold=True)
    table(ctx, 3, ['File'], [[r] for r in data.get('accounting', {}).get('context / layout (not priced)', [])], [120])
    waiting = [p for p in products if money(p['facts'].get('unit')) is None]
    if waiting:
        wt = master.create_sheet('Not yet priced')
        table(wt, 1, ['Pack', 'Drawing', 'Product', 'Why'],
              [[p['item']['pack'], p['item']['drawing'], p['item']['title'], p['why']] for p in waiting],
              [30, 10, 50, 40])
    master_path = out_dir / ('Hotel Chocolat master price schedule %s.xlsx' % stamp)
    master.save(str(master_path))

    # 2. One review pack per pack, a tab per product.
    written = [master_path]
    for pack in sorted({p['item']['pack'] for p in products}):
        members = sorted((p for p in products if p['item']['pack'] == pack), key=lambda p: p['item']['drawing'])
        wb = openpyxl.Workbook()
        sm = wb.active
        sm.title = 'Summary'
        sm['A1'] = 'Hotel Chocolat review pack: %s (%s)' % (pack, stamp)
        sm['A1'].font = Font(bold=True, size=14)
        table(sm, 3, ['Drawing', 'Product', 'Unit price \u00a3', 'Basis', 'Items to confirm', '\u00a3 at stake', 'Status'],
              [[p['item']['drawing'], p['item']['title'], money(p['facts'].get('unit')), p['basis'],
                len(p['facts'].get('confirm', [])), at_stake(p) or None,
                (p['facts'].get('status') or p['why'] or '')[:200]] for p in members],
              [10, 50, 12, 18, 10, 11, 70])
        used_names = {'Summary'}
        for p in members:
            name = re.sub(r'[\[\]:*?/\\]', '', '%s %s' % (p['item']['drawing'], p['item']['title']))[:31]
            while name in used_names:
                name = name[:28] + '~%d' % len(used_names)
            used_names.add(name)
            t = wb.create_sheet(name)
            f = p['facts']
            t['A1'] = '%s  %s' % (p['item']['drawing'], p['item']['title'])
            t['A1'].font = Font(bold=True, size=13)
            facts = [('Unit price \u00a3', money(f.get('unit'))), ('Material \u00a3', money(f.get('material'))),
                     ('Labour \u00a3', money(f.get('labour'))), ('Basis', p['basis']),
                     ('What a unit costs', f.get('summary') or None),
                     ('Status', f.get('status') or p['why'] or None), ('Run', (p['run'] or {}).get('run_id')),
                     ('Workbook', p['book'])]
            for i, (k, v) in enumerate(facts, 3):
                t.cell(row=i, column=1, value=k).font = Font(bold=True)
                t.cell(row=i, column=2, value=v).alignment = Alignment(wrap_text=True, vertical='top')
            if p['book']:
                t.cell(row=10, column=2).hyperlink = p['book']
            row = 13
            t.cell(row=row - 1, column=1, value='FOR THE ESTIMATOR TO CONFIRM').font = Font(bold=True)
            conf = f.get('confirm', [])
            heads = ['#', 'Kind', 'Decision', 'Part', 'Current assumption', 'Action', '\u00a3 at stake']
            row = table(t, row, heads, [[c.get(h) for h in heads] for c in conf] or [['', 'none listed']],
                        [26, 18, 60, 14, 40, 40, 11]) + 1
            t.cell(row=row, column=1, value='OUTSTANDING ESTIMATOR INPUTS').font = Font(bold=True)
            row = table(t, row + 1, ['Input'], [[x] for x in f.get('inputs', [])] or [['none listed']]) + 1
            t.cell(row=row, column=1, value='FROM THE PLAN (the drawing pack itself)').font = Font(bold=True)
            row = table(t, row + 1, ['Note'], [[w] for w in p['warn']] or [['nothing to note']]) + 1
            if p['item'].get('brief'):
                t.cell(row=row, column=1, value='BRIEF (no readable drawings)').font = Font(bold=True)
                t.cell(row=row + 1, column=1, value=p['item']['brief']).alignment = Alignment(wrap_text=True)
                row += 3
            t.cell(row=row, column=1, value='SOURCE FILES').font = Font(bold=True)
            table(t, row + 1, ['File', 'Drawing'], [[x['name'], x.get('ref')] for x in p['item']['files']])
        path = out_dir / ('Hotel Chocolat review pack %s %s.xlsx' % (pack, stamp))
        wb.save(str(path))
        written.append(path)
    print('%d products: %d priced, %d not yet (%d priced from the run record, workbook not read)'
          % (len(products), len(products) - len(waiting), len(waiting),
             sum(1 for p in products if not p['book'] and p['facts'].get('unit') is not None)))
    for w in written:
        print('Written: %s' % w)
    print('Nothing was submitted or re-priced.')
