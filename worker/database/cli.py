import argparse
import json

from db import (
    get_pending_papers,
    get_investigation_status,
    set_investigation_status,
    request_stop,
    finish_investigation,
)


def main():
    parser = argparse.ArgumentParser(
        description="Research database command-line interface"
    )
    parser.add_argument(
        "command",
        choices=["pending", "status", "start", "stop", "finish"],
    )

    args = parser.parse_args()

    if args.command == "pending":
        print(json.dumps(get_pending_papers()))

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


if __name__ == "__main__":
    main()