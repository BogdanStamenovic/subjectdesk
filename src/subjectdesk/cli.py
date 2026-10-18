"""Command-line interface for Subjectdesk.

Stdout contains requested status data only. Progress and errors go to stderr.
Exit codes: 0 success, 1 operation failed, 2 usage error or user aborted.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections.abc import Callable, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from typing import NoReturn

from . import __version__
from .core import MODELS, SubjectdeskError, discover, init, jobs, process_one, retry, scan_stable


class _UsageError(Exception):
    pass


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _UsageError(message)


def _build_parser() -> argparse.ArgumentParser:
    parser = _ArgumentParser(prog="subjectdesk", description="Research assignments in subject folders")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="print detailed progress")
    parser.add_argument("-q", "--quiet", action="store_true", help="suppress non-error progress")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("init", "initialize a workspace"),
        ("once", "scan and process all queued assignments once"),
        ("watch", "watch continuously for new assignments"),
        ("status", "list assignments and their status"),
        ("retry", "requeue a failed or interrupted assignment"),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS)
        command.add_argument("-q", "--quiet", action="store_true", default=argparse.SUPPRESS)
        command.add_argument("root", type=Path, help="workspace containing subject folders")
        if name in {"once", "watch"}:
            command.add_argument("--model", choices=sorted(MODELS), default="haiku")
            command.add_argument("--key-file", type=Path, help="file containing Anthropic API key")
        if name == "watch":
            command.add_argument("--poll-seconds", type=float, default=1.0)
            command.add_argument("--max-workers", type=int, default=2)
        if name == "retry":
            command.add_argument("job_id")
    return parser


def _load_key(path: Path | None) -> None:
    if path is None:
        return
    try:
        value = path.expanduser().read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise SubjectdeskError(f"cannot read key file: {exc}") from exc
    if not value:
        raise SubjectdeskError("key file is empty")
    os.environ["ANTHROPIC_API_KEY"] = value


def _run_queued(root: Path, log: Callable[[str], None]) -> int:
    failures = 0
    while True:
        job_id = process_one(root)
        if job_id is None:
            break
        row = next(row for row in jobs(root) if row["id"] == job_id)
        if row["status"] == "failed":
            failures += 1
            print(f"subjectdesk: {job_id}: {row['error']}", file=sys.stderr)
        else:
            log(f"completed {job_id}: {row['output_dir']}")
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except _UsageError as exc:
        print(f"subjectdesk: error: {exc}", file=sys.stderr)
        return 2

    def log(message: str) -> None:
        if not args.quiet:
            print(message, file=sys.stderr)

    root = args.root.expanduser().resolve()
    try:
        if args.command == "init":
            init(root)
            log(f"initialized {root}")
            return 0
        if args.command == "status":
            for row in jobs(root):
                print(f"{row['id']}\t{row['status']}\t{row['subject']}\t{row['source']}")
                if args.verbose and row["error"]:
                    print(f"  error: {row['error']}")
            return 0
        if args.command == "retry":
            retry(root, args.job_id)
            log(f"requeued {args.job_id}")
            return 0
        _load_key(args.key_file)
        if args.command == "once":
            added = discover(root, args.model)
            if args.verbose:
                log(f"discovered {len(added)} assignment(s)")
            failures = _run_queued(root, log)
            return 1 if failures else 0
        if args.poll_seconds <= 0:
            raise SubjectdeskError("--poll-seconds must be greater than zero")
        if args.max_workers < 1:
            raise SubjectdeskError("--max-workers must be at least one")
        seen: dict[str, tuple[int, int]] = {}
        log(f"watching {root}")
        with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
            active: set[Future[str | None]] = set()
            while True:
                added = scan_stable(root, seen, args.model)
                if args.verbose and added:
                    log(f"discovered {len(added)} assignment(s)")
                for future in tuple(active):
                    if not future.done():
                        continue
                    active.remove(future)
                    job_id = future.result()
                    if job_id is None:
                        continue
                    row = next(row for row in jobs(root) if row["id"] == job_id)
                    if row["status"] == "failed":
                        print(f"subjectdesk: {job_id}: {row['error']}", file=sys.stderr)
                    else:
                        log(f"completed {job_id}: {row['output_dir']}")
                queued = sum(row["status"] == "queued" for row in jobs(root))
                for _ in range(min(queued, args.max_workers - len(active))):
                    active.add(pool.submit(process_one, root))
                time.sleep(args.poll_seconds)
    except KeyboardInterrupt:
        return 0
    except SubjectdeskError as exc:
        print(f"subjectdesk: error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
