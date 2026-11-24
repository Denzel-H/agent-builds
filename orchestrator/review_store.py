"""Local, durable storage for generated literature reviews on the orchestrator."""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


def resolve_output_dir(output_dir=None):
    configured = output_dir or os.environ.get("REVIEW_OUTPUT_DIR")
    return Path(configured or DEFAULT_OUTPUT_DIR).expanduser().resolve()


def render_review(topic, review, records, generated_at):
    def quote(value):
        return json.dumps(str(value), ensure_ascii=False)

    lines = [
        "---",
        f"topic: {quote(topic)}",
        f"generated_at: {quote(generated_at)}",
        f"source_count: {len(records)}",
        "sources:",
    ]
    for record in records:
        lines.append(
            f"  - {quote(record.get('filename', 'unknown'))} "
            f"(paper {record.get('id')})"
        )
    lines += ["---", "", review, ""]
    return "\n".join(lines)


def save_review(topic, review, records, output_dir=None):
    """Save a UTF-8 Markdown review with collision-safe naming."""
    if not review or not review.strip():
        raise ValueError("Cannot save an empty literature review")

    directory = resolve_output_dir(output_dir)
    directory.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    generated_at = now.isoformat()
    filename = (
        f"review-{now:%Y%m%dT%H%M%SZ}-{uuid4().hex[:8]}.md"
    )
    path = directory / filename
    path.write_text(
        render_review(topic, review, records, generated_at),
        encoding="utf-8",
    )
    return str(path)


def get_latest_review(output_dir=None):
    directory = resolve_output_dir(output_dir)
    if not directory.is_dir():
        return None

    reviews = sorted(
        directory.glob("review-*.md"),
        key=lambda path: (path.stat().st_mtime, path.name),
        reverse=True,
    )
    return str(reviews[0]) if reviews else None


def read_review(path):
    return Path(path).read_text(encoding="utf-8")
