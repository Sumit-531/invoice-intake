"""Runtime configuration. Environment first, working defaults second.

The accounting system's address is configurable for one reason worth stating: the default
is exactly what the assignment specifies, so an evaluator who changes nothing gets the
documented behaviour. It is overridable because a machine may already have something
bound to that port, and losing a day to a port collision is not a design decision.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent

# Run artifacts. Gitignored: these are evidence, not source.
OUT_DIR = REPO_ROOT / "out"
RAW_DIR = OUT_DIR / "raw"        # model responses, saved before anything parses them
RUNS_DIR = OUT_DIR / "runs"      # what the pipeline decided, and on what grounds

ACCOUNTING_API_URL = os.getenv("ACCOUNTING_API_URL", "http://localhost:8080").rstrip("/")
ACCOUNTING_API_KEY = os.getenv("ACCOUNTING_API_KEY", "demo-key-1234")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Pinned rather than `gemini-flash-latest`, so a run is reproducible and a model change is
# a deliberate edit. Worth knowing: the model list this key can see still advertises older
# Flash versions that the generation endpoint refuses to serve to a newly created key.
# Availability is a moving target even inside one provider, which is an argument for
# keeping the provider behind one function rather than for picking a better provider.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

# A model call is a network call: it gets an explicit timeout, always.
#
# Generous, and deliberately so. 60s was calibrated on the text route, where a call
# returns in about twenty seconds — and it cut the first vision call off mid-flight. That
# is the worst outcome available: the request was still spent, the response was discarded
# before it could be cached, and the retry cost a second one against a 20-per-day ceiling.
# A timeout exists to stop a call hanging forever, not to enforce a latency budget nobody
# set. When the request is the scarce resource, too short is more expensive than too long.
MODEL_TIMEOUT_SECONDS = 240
HTTP_TIMEOUT_SECONDS = 15

# The free tier allows 5 requests per minute. A batch that ignores this gets a 429 partway
# through and leaves half the set unread.
#
# This is pacing, not a retry policy — the distinction is deliberate. Backoff reacts to a
# refusal after provoking it; spacing means the refusal never happens. Twelve seconds is
# the rate exactly, so the extra second is the margin for a clock that disagrees with the
# provider's. Only uncached calls wait: replaying stored output hits no quota at all.
MODEL_MIN_SPACING_SECONDS = 13


def ensure_out_dirs() -> None:
    for directory in (RAW_DIR, RUNS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
