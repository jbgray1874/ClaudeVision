"""Read-only, request-scoped library discovery. No saved index or service calls.

Visit the containers above numbered jobs, loose library files in those containers,
and the requested drawing's own numbered job. Never walk unrelated jobs. A miss
there is NOT proof that no copy exists inside an unrelated numbered job.
"""
import os
import re
from pathlib import Path


class LiveLibraryLookup:
    def __init__(self, areas, include_archives=False):
        self.areas = [(label, Path(root)) for label, root in areas if root is not None]
        self.include_archives = include_archives
        self.evidence = []
        self._rows = {}
        self._selected = {}
        self._walked = {}
        self.unreadable = []

    # ONE BOUNDED WALK PER AREA, NOT ONE PER DRAWING (20 Nov 2026). GA17 calls for four drawings
    # of four other jobs; each was a fresh walk of every non-job folder of the whole Design area,
    # to 16 levels, over the VPN. Now each area's containers are walked once per batch, to
    # CONTAINER_DEPTH levels of non-job folders, noting every numbered job folder and every loose
    # drawing file on the way; a drawing then lists only its own job's folders.
    CONTAINER_DEPTH = int(os.getenv('SDI_PACK_LIBRARY_DEPTH') or 3)

    def _containers(self, root):
        import pack_resolver as pr
        key = str(root)
        if key in self._walked:
            return self._walked[key]
        jobs, loose = [], []
        stack = [(Path(root), 0)]
        while stack:
            folder, depth = stack.pop()
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        path = Path(entry.path)
                        if pr._archive_path(path) and not self.include_archives:
                            continue
                        if entry.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction()):
                            raise pr.PackCheckStalled(f'library search cannot verify linked path: {path}')
                        if entry.is_dir(follow_symlinks=False):
                            if re.match(r'\d{3,}', entry.name):
                                jobs.append(path)
                            elif depth + 1 <= self.CONTAINER_DEPTH:
                                stack.append((path, depth + 1))
                        elif entry.is_file(follow_symlinks=False) and path.suffix.lower() in pr.DRAWING_EXT:
                            stat = entry.stat(follow_symlinks=False)
                            loose.append((path, stat.st_size, stat.st_mtime))
            except OSError as exc:
                # ONE UNREADABLE FOLDER IS NOT AN UNREADABLE AREA (21 Nov 2026). Row 139 was held
                # because a service's temporary folder deep in the Design area
                # (".ArchiveServiceTemp...", PermissionError) could not be listed. A folder below
                # the area's root is skipped and recorded, so a drawing missed there is never
                # taken as proof it does not exist; an unreadable root still stops the check.
                if folder == Path(root):
                    raise pr.PackCheckStalled(f'library area could not be read ({folder}: {type(exc).__name__})') from exc
                self.unreadable.append(f'{folder} ({type(exc).__name__})')
        self._walked[key] = (jobs, loose)
        return jobs, loose

    def _scan(self, root, job):
        import pack_resolver as pr
        jobs, loose = pr._within(f'live library search: the folders of {root}',
                                 lambda: self._containers(root), pr.folder_seconds() * 3)
        files = [f for f in loose if pr.job_number(pr.drawing_id(f[0].name)) == job]
        for folder in jobs:
            if not re.match(rf'{re.escape(job)}(?!\d)', folder.name):
                continue
            for sub, rows, archive in pr._within(f'live library search: listing {folder}',
                                                 lambda f=folder: pr.rows_now(f)):
                if archive and not self.include_archives:
                    continue
                files.extend(rows)
        return files

    def __call__(self, drawing):
        import pack_resolver as pr
        key = drawing.upper()
        if key in self._selected:
            return self._selected[key][0]
        job = pr.job_number(drawing)
        if not job:
            return []
        for label, root in self.areas:
            cache_key = (str(root), job)
            if cache_key not in self._rows:
                self._rows[cache_key] = self._scan(root, job)
            rows = self._rows[cache_key]
            hits = [f for f in rows if pr._same(pr.drawing_id(f[0].name), drawing)]
            sheet_ids = pr.sheets_of(drawing, [pr.drawing_id(f[0].name) for f in rows])
            sheets = [f for f in rows if pr.drawing_id(f[0].name) in sheet_ids]
            self.evidence.append({'drawing': drawing, 'area': label, 'root': str(root),
                                  'scope': 'own numbered job plus non-job library containers; unrelated jobs excluded',
                                  'archives_included': self.include_archives,
                                  'files': [str(f[0]) for f in hits],
                                  'sheet_files': [str(f[0]) for f in sheets],
                                  'unreadable_folders': list(self.unreadable)})
            # Design wins as a set; do not mix a Prototype PDF with Design CAD.
            if hits or sheets:
                self._selected[key] = (hits, sheets)
                return hits
        self._selected[key] = ([], [])
        return []

    def sheet_files(self, drawing):
        # Only sheets from an already selected area, not a new search for every
        # member of the main job. Called immediately after external lookup.
        return self._selected.get(drawing.upper(), ([], []))[1]


def library_areas(design_only=False):
    """Separate live roots, not index configuration. Never includes Production."""
    design = os.getenv('SDI_PACK_LIBRARY_DESIGN_ROOT') or r'\\sdi-dc01\CAD\Design'
    prototype = os.getenv('SDI_PACK_LIBRARY_PROTOTYPE_ROOT') or r'\\sdi-dc01\CAD\Prototype'
    areas = [('Design', Path(design))]
    if not design_only:
        areas.append(('Prototype', Path(prototype)))
    return areas
