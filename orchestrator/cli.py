"""Command-line interface for the literature research orchestrator."""

import argparse
import asyncio
import json
import subprocess
import sys
from pathlib import Path

try:
    from .graph import run_research, run_finalization
    from . import transport
    from .review_store import get_latest_review, read_review
except ImportError:  # executed directly as `python3 orchestrator/cli.py`
    from graph import run_research, run_finalization
    import transport
    from review_store import get_latest_review, read_review

DEFAULT_LOCAL_PROJECT_DIR = str(Path(__file__).resolve().parent.parent)


def load_config_file(path):
    if not path:
        return {}
    data = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Configuration file must contain a JSON object")
    return data


def override_from_args(config, args, mapping):
    for key, attribute in mapping.items():
        value = getattr(args, attribute, None)
        if value is not None:
            config[key] = value


def resolve_execution(config, args):
    execution = dict(config.get("execution") or {})
    override_from_args(
        execution,
        args,
        {"mode": "mode", "host": "host", "project_dir": "project_dir"},
    )

    mode = execution.get("mode", "local")
    if mode not in ("local", "ssh"):
        raise ValueError(f"Unsupported execution mode: {mode}")

    if mode == "ssh" and not execution.get("host"):
        raise ValueError("--host is required for SSH execution")

    project_dir = execution.get("project_dir")
    if not project_dir:
        if mode != "local":
            raise ValueError("--project-dir is required for SSH execution")
        project_dir = DEFAULT_LOCAL_PROJECT_DIR

    execution["mode"] = mode
    execution["project_dir"] = (
        str(Path(project_dir).expanduser().resolve())
        if mode == "local" else project_dir
    )
    return execution


def resolve_topic(config, args):
    topic = getattr(args, "topic", None) or config.get("topic")
    if not isinstance(topic, str) or not topic.strip():
        raise ValueError("A research topic is required (--topic)")
    return topic.strip()


def build_research_config(args):
    config = load_config_file(args.config)
    config["topic"] = resolve_topic(config, args)
    config["execution"] = resolve_execution(config, args)

    paper_directory = (
        args.paper_directory or config.get("paper_directory")
    )
    if not paper_directory:
        raise ValueError("--paper-directory is required to start research")
    paper_directory = Path(paper_directory).expanduser().resolve()
    if not paper_directory.is_dir():
        raise NotADirectoryError(f"Paper directory does not exist: {paper_directory}")
    config["paper_directory"] = str(paper_directory)

    max_workers = (
        args.max_workers
        if args.max_workers is not None
        else config.get("max_workers", 1)
    )
    try:
        max_workers = int(max_workers)
    except (TypeError, ValueError):
        raise ValueError("max_workers must be a positive integer")
    if max_workers < 1:
        raise ValueError("max_workers must be at least 1")
    config["max_workers"] = max_workers

    if args.output_dir or config.get("output_dir"):
        config["output_dir"] = args.output_dir or config.get("output_dir")

    return config


def build_finalization_config(args):
    config = load_config_file(args.config)
    config["topic"] = resolve_topic(config, args)
    config["execution"] = resolve_execution(config, args)
    if args.output_dir or config.get("output_dir"):
        config["output_dir"] = args.output_dir or config.get("output_dir")
    return config


def add_execution_arguments(parser):
    parser.add_argument("--config", help="JSON configuration file")
    parser.add_argument("--mode", choices=["local", "ssh"])
    parser.add_argument("--host", help="SSH host alias (SSH mode only)")
    parser.add_argument("--project-dir", help="Worker project directory")
    parser.add_argument("--output-dir", help="Directory for generated Markdown reviews")


def build_parser():
    parser = argparse.ArgumentParser(
        description="LangGraph literature research orchestrator"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="Start continuous paper research")
    start.add_argument("--topic")
    start.add_argument("--paper-directory")
    start.add_argument("--max-workers", type=int)
    start.add_argument("--poll-interval", type=float, default=2.0)
    start.add_argument("--recursion-limit", type=int, default=10000)
    start.add_argument(
        "--background", action="store_true",
        help="Detach research and return immediately (for agent-driven runs)",
    )
    start.add_argument(
        "--log-file", help="Log file for --background (default: output/research.log)"
    )
    add_execution_arguments(start)

    status = subparsers.add_parser("status", help="Show investigation and review status")
    status.add_argument(
        "--papers", action="store_true",
        help="Include per-paper status and finding counts",
    )
    add_execution_arguments(status)

    stop = subparsers.add_parser("stop", help="Request graceful research shutdown")
    add_execution_arguments(stop)

    finalize = subparsers.add_parser(
        "finalize", help="Generate the literature review from completed research"
    )
    finalize.add_argument("--topic")
    add_execution_arguments(finalize)

    review = subparsers.add_parser("review", help="Retrieve the latest Markdown review")
    review.add_argument("--output-dir")
    review.add_argument(
        "--content", action="store_true", help="Print the Markdown instead of the path"
    )

    return parser


def emit(payload):
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def child_start_arguments(argv):
    """Strip coordinator-only flags before re-launching a detached start."""
    cleaned = []
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--background":
            index += 1
        elif argument == "--log-file":
            index += 2
        elif argument.startswith("--log-file="):
            index += 1
        else:
            cleaned.append(argument)
            index += 1
    return cleaned


def main(argv=None):
    parser = build_parser()
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(argv)

    try:
        if args.command == "start":
            config = build_research_config(args)

            if args.background:
                log_path = Path(
                    args.log_file
                    or (Path(DEFAULT_LOCAL_PROJECT_DIR) / "output" / "research.log")
                ).expanduser().resolve()
                log_path.parent.mkdir(parents=True, exist_ok=True)

                command = [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    *child_start_arguments(raw_argv),
                ]
                with log_path.open("ab") as log_file:
                    process = subprocess.Popen(
                        command,
                        stdin=subprocess.DEVNULL,
                        stdout=log_file,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )

                emit({
                    "started": True,
                    "pid": process.pid,
                    "log": str(log_path),
                    "status": "running",
                })
                return 0

            result = asyncio.run(
                run_research(
                    config,
                    poll_interval=args.poll_interval,
                    recursion_limit=args.recursion_limit,
                )
            )
            findings = result.get("findings", [])
            emit({
                "status": result.get("status"),
                "research_results": findings,
                "processed": sum(1 for item in findings if item.get("processed")),
                "failed": sum(1 for item in findings if not item.get("processed")),
            })

        elif args.command == "status":
            config = load_config_file(args.config)
            execution = resolve_execution(config, args)
            result = {
                "status": asyncio.run(transport.get_investigation_status(execution)),
                "papers": asyncio.run(transport.get_research_stats(execution)),
                "latest_review": get_latest_review(args.output_dir),
            }
            if args.papers:
                result["paper_details"] = asyncio.run(transport.get_papers(execution))
            emit(result)

        elif args.command == "stop":
            config = load_config_file(args.config)
            execution = resolve_execution(config, args)
            emit(asyncio.run(transport.request_investigation_stop(execution)))

        elif args.command == "finalize":
            config = build_finalization_config(args)
            result = asyncio.run(run_finalization(config))
            emit({
                "success": bool(result.get("review_generated")),
                "review_path": result.get("review_path"),
                "worker_review_path": result.get("worker_review_path"),
                "eligible_papers": len(result.get("eligible_research", [])),
                "skipped_papers": len(result.get("skipped_research", [])),
                "error": result.get("review_error") or None,
            })

        elif args.command == "review":
            path = get_latest_review(args.output_dir)
            if not path:
                emit({"found": False, "path": None})
                return 1
            if args.content:
                print(read_review(path))
            else:
                emit({"found": True, "path": path})

    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        emit({"success": False, "error": str(error)})
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
