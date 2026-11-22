import argparse
import json

from db import get_pending_papers


def main():
    parser = argparse.ArgumentParser(
        description="Research database command-line interface"
    )

    parser.add_argument(
        "command",
        choices=["pending"],
    )

    args = parser.parse_args()

    if args.command == "pending":
        papers = get_pending_papers()
        print(json.dumps(papers))


if __name__ == "__main__":
    main()