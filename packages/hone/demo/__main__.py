"""Build the prepared demo state into a folder to inspect it.

    uv run python -m hone.demo build --out /tmp/hone-demo [--date 2026-11-11]

The service builds the same state on its own in demo mode (HONE_DEMO=1), so
the booth never needs this command.
"""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

from ..settings import load_settings
from .build import run


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m hone.demo", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="write data/, project/ and manifest.json for one day")
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--date", type=dt.date.fromisoformat, default=dt.datetime.now().astimezone().date(),
                       help="the booth day, the prepared history ends on the working day before it")
    args = parser.parse_args()
    run(args.out.resolve(), load_settings(), args.date)


if __name__ == "__main__":
    main()
