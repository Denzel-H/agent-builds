import argparse
import json

try:
    from .db import (
        get_pending_papers,
        get_completed_papers,
        get_paper_stats,
        get_papers,
        get_investigation_status,
        set_investigation_status,
        request_stop,
        finish_investigation,
        add_paper,
        paper_exists,
    )
except ImportError:  # executed directly as `python3 worker/database/cli.py`
    from db import (
        get_pending_papers,
        get_completed_papers,
        get_paper_stats,
        get_papers,
        get_investigation_status,
        set_investigation_status,
        request_stop,
        finish_investigation,
        add_paper,
        paper_exists,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Research database command-line interface"
    )
    parser.add_argument(
        "command",
        choices=[
            "pending", "completed", "stats", "papers", "status", "start",
            "stop", "finish", "add", "exists",
        ],
    )
    parser.add_argument("--filename")

    args = parser.parse_args()

    if args.command == "pending":
        print(json.dumps(get_pending_papers()))

    elif args.command == "completed":
        print(json.dumps(get_completed_papers()))

    elif args.command == "stats":
        print(json.dumps(get_paper_stats()))

    elif args.command == "papers":
        print(json.dumps(get_papers()))

    elif args.command == "status":
        print(json.dumps({
            "status": get_investigation_status()
        }))

    elif args.command == "start":
        set_investigation_status("running")
        print(json.dumps({"status": "running"}))

    elif args.command == "stop":
        accepted = request_stop()
        print(json.dumps({
            "stop_requested": accepted,
            "status": get_investigation_status(),
        }))
    elif args.command == "finish":
        finished = finish_investigation()

        print(json.dumps({
            "finished": finished,
            "status": get_investigation_status(),
        }))
    elif args.command == "add":
        if not args.filename:
            parser.error("--filename is required for the add command")

        paper_id = add_paper(args.filename)

        print(json.dumps({
            "paper_id": paper_id,
            "filename": args.filename,
        }))
    elif args.command == "exists":
        if not args.filename:
            parser.error("--filename is required for the exists command")

        print(json.dumps({
            "exists": paper_exists(args.filename)
        }))

if __name__ == "__main__":
    main()