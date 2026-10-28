"""The service's own config, whatever the name `config` happens to be bound to.

TWO MODULES ARE CALLED config. The engine's (src/config.py: rates, densities, vocabularies) and
this service's (sdi-intelligence-backend/config.py: the key, the shares, the staging root). Both
are imported bare, so whichever directory reached sys.path first owns the name for the whole
process. In the service it is always this one. In the test suite the engine's is cached first
(tests/conftest.py), so a backend module imported there bound the ENGINE's config and reached for
config.API_KEY or config.FILE_ROOTS on a module that has neither: six portal tests failed alone
and passed in the full suite only because an earlier test had happened to set API_KEY on the
engine's module. Order decided the result, which is the worst kind of test.

So each backend module asks here. A `config` that is this service's own file, or a stub a test
installed under the name (it has no file), is used as it is. A config loaded from any OTHER file
is the engine's, and this service's own config.py is loaded by path, once, beside it.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Optional

_OWN_NAME = "sdi_service_config"


def the_service_config(bound: Optional[ModuleType] = None) -> ModuleType:
    """This service's config: `bound` (what `import config` gave) when it is ours, else ours
    loaded by path. Cached under its own name, so every backend module shares one object."""
    ours = Path(__file__).with_name("config.py").resolve()
    if bound is not None:
        where = getattr(bound, "__file__", None)
        if not where:
            return bound                                  # a stub a test put under the name
        try:
            if Path(where).resolve() == ours:
                return bound
        except OSError:
            return bound
    cached = sys.modules.get(_OWN_NAME)
    if cached is not None:
        return cached
    spec = importlib.util.spec_from_file_location(_OWN_NAME, ours)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_OWN_NAME] = mod
    spec.loader.exec_module(mod)                                     # type: ignore[union-attr]
    return mod
