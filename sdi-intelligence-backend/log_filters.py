"""What does not go in the access log.

Its own module, and not a few lines inside app.py, for one reason: app.py cannot
be imported without FastAPI, python-dotenv and the rest of the service, so a
filter living there could not be tested. A thing that decides what an operator
DOES NOT SEE is the last thing that should be taken on trust.
"""

from __future__ import annotations

import logging


class QuietPolling(logging.Filter):
    """Keep the runner's heartbeat out of the access log.

    A runner polls for work every five seconds. That is 720 lines an hour of
    "POST /api/estimate/runner/claim 200 OK" per runner, and the console becomes
    a place where nothing can be found — which is how several stray runners went
    unnoticed on a laptop until the log was a solid wall of them.

    ONLY THE QUIET CASE IS HIDDEN. On these endpoints a 200 means "asked, told
    nothing"; that is the only line suppressed. A poll that is rejected, one that
    fails, a job being queued, a run completing, anybody browsing — all still
    print. Hiding a failure to save a line would be a worse log than a noisy one.

    Set SDI_LOG_POLLING=1 to watch the polling itself.
    """

    NOISE = ("/api/estimate/runner/claim", "/api/estimate/runners")

    def filter(self, record: logging.LogRecord) -> bool:
        # uvicorn.access formats with (client, method, path, http_version, status).
        # Anything that is not that shape is not ours to judge, and is kept.
        try:
            path, status = record.args[2], int(record.args[4])
        except (TypeError, IndexError, ValueError, KeyError):
            return True
        return not (status == 200 and any(path.startswith(n) for n in self.NOISE))
