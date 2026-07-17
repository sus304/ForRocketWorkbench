"""`wb` command-line client (design §4.3, Phase 10).

Thin argparse front end over service.client.ServiceClient. Connects to WB_SERVICE_URL
(default localhost) with WB_API_TOKEN. Usage:

    wb submit <project_dir> <mode> [--model M] [--max-thread]
    wb status <job_id>
    wb list [--status STATUS]
    wb cancel <job_id>
    wb pull <job_id> <dest> [--full]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from service.client import ServiceClient

_MODES = ["trajectory", "area", "montecarlo", "sensitivity"]
_DEFAULT_URL = "http://127.0.0.1:8760"


def _client_from_env() -> ServiceClient:
    return ServiceClient(os.environ.get("WB_SERVICE_URL", _DEFAULT_URL),
                         os.environ.get("WB_API_TOKEN", ""))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="wb", description="ForRocket Workbench compute-service client")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("submit", help="submit a job")
    s.add_argument("project_dir")
    s.add_argument("mode", choices=_MODES)
    s.add_argument("--model", default="")
    s.add_argument("--max-thread", action="store_true")

    st = sub.add_parser("status", help="show one job")
    st.add_argument("job_id", type=int)

    ls = sub.add_parser("list", help="list jobs")
    ls.add_argument("--status", default=None)

    c = sub.add_parser("cancel", help="cancel a job")
    c.add_argument("job_id", type=int)

    pl = sub.add_parser("pull", help="download a job result")
    pl.add_argument("job_id", type=int)
    pl.add_argument("dest")
    pl.add_argument("--full", action="store_true")
    return p


def main(argv=None, client: ServiceClient = None) -> int:
    args = build_parser().parse_args(argv)
    client = client or _client_from_env()

    if args.cmd == "submit":
        _emit(client.submit(args.project_dir, args.mode, args.model, args.max_thread))
    elif args.cmd == "status":
        _emit(client.status(args.job_id))
    elif args.cmd == "list":
        _emit(client.list_jobs(args.status))
    elif args.cmd == "cancel":
        _emit(client.cancel(args.job_id))
    elif args.cmd == "pull":
        dest = client.pull(args.job_id, args.dest, args.full)
        _emit({"pulled_to": str(dest)})
    return 0


def _emit(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
