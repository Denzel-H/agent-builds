"""Generate a literature review from completed research records.

The research payload is supplied on stdin so large datasets never have to be
passed as command arguments. OpenCode is launched noninteractively using the
existing ``literature-writer`` agent definition in ``.opencode/agents``.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

DEFAULT_MODEL = os.environ.get("OPENCODE_MODEL", "openai/gpt-6-luna")
MIN_REVIEW_LENGTH = 200


def load_payload(stream):
    raw = stream.read()
    if not raw or not raw.strip():
        raise ValueError("No research payload was supplied on stdin")

    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Research payload must be a JSON object")

    topic = payload.get("topic")
    if not isinstance(topic, str) or not topic.strip():
        raise ValueError("Research payload requires a non-empty topic")

    research = payload.get("research")
    if not isinstance(research, list):
        raise ValueError("Research payload requires a research list")

    return topic.strip(), research


def select_eligible_research(records):
    """Keep completed papers with genuine findings; report the rest."""
    eligible = []
    skipped = []

    for record in records:
        label = record.get("filename", "unknown") if isinstance(record, dict) else "unknown"

        if not isinstance(record, dict):
            skipped.append({"filename": label, "reason": "Invalid research record"})
            continue

        if record.get("findings_error"):
            skipped.append({
                "filename": label,
                "reason": record["findings_error"],
            })
            continue

        findings = record.get("findings")
        if not isinstance(findings, list) or not findings:
            skipped.append({
                "filename": label,
                "reason": "No relevant findings",
            })
            continue

        citation = record.get("citation")
        if not isinstance(citation, str) or not citation.strip():
            citation = ""

        eligible.append({
            "id": record.get("id"),
            "filename": label,
            "citation": citation,
            "findings": findings,
            "citation_incomplete": not bool(citation),
        })

    return eligible, skipped


def strip_code_fence(text):
    text = text.strip()
    if not text.startswith("```"):
        return text

    lines = text.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def validate_review(text):
    review = strip_code_fence(text)

    if len(review) < MIN_REVIEW_LENGTH:
        raise ValueError(
            f"Writer output is too short to be a literature review "
            f"({len(review)} characters)"
        )

    lowered = review.lower()
    if "# literature review" not in lowered:
        raise ValueError("Writer output is missing the '# Literature Review' heading")
    if "# references" not in lowered:
        raise ValueError("Writer output is missing the '# References' heading")
    if not re.search(r"\[\d+\]", review):
        raise ValueError("Writer output contains no IEEE-style citations")

    return review


def build_prompt(topic, eligible):
    records = [
        {
            "filename": record["filename"],
            "citation": record["citation"],
            "findings": record["findings"],
        }
        for record in eligible
    ]
    return json.dumps(
        {"topic": topic, "research": records},
        indent=2,
        ensure_ascii=False,
    )


def invoke_writer(topic, eligible, model=DEFAULT_MODEL, runner=None):
    if not eligible:
        raise ValueError("No eligible completed research is available for the review")

    runner = runner or subprocess.run

    with tempfile.TemporaryDirectory(prefix="literature-writer-") as temp_dir:
        prompt_path = Path(temp_dir) / "research-records.json"
        prompt_path.write_text(build_prompt(topic, eligible), encoding="utf-8")

        message = (
            f"Write a literature review for this research topic: {topic}\n\n"
            "The attached JSON file contains every completed research record. "
            "Use only those records as evidence. Follow your literature-writer "
            "instructions: synthesize by theme rather than by paper, use IEEE "
            "numbered citations, and flag incomplete bibliographic details."
        )

        command = [
            "opencode",
            "run",
            "--agent", "literature-writer",
            "--model", model,
            "--file", str(prompt_path),
            message,
        ]

        result = runner(
            command,
            capture_output=True,
            text=True,
            check=False,
            stdin=subprocess.DEVNULL,
        )

    if result.returncode != 0:
        raise RuntimeError(
            f"OpenCode literature-writer failed (exit {result.returncode}): "
            f"{result.stderr.strip()}"
        )

    return validate_review(result.stdout)


def render_markdown(topic, review, eligible, generated_at):
    def quote(value):
        return json.dumps(str(value), ensure_ascii=False)

    lines = [
        "---",
        f"topic: {quote(topic)}",
        f"generated_at: {quote(generated_at)}",
        f"source_count: {len(eligible)}",
        "sources:",
    ]
    for record in eligible:
        lines.append(f"  - {quote(record['filename'])} (paper {record['id']})")
    lines += ["---", "", review, ""]
    return "\n".join(lines)


def save_review(topic, review, eligible, output_dir, generated_at=None):
    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)

    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    filename = f"review-{stamp}-{uuid4().hex[:8]}.md"
    path = directory / filename

    path.write_text(
        render_markdown(topic, review, eligible, generated_at),
        encoding="utf-8",
    )
    return path


def write_review(topic, research, output_dir=None, model=DEFAULT_MODEL, runner=None):
    runner = runner or subprocess.run
    eligible, skipped = select_eligible_research(research)
    if not eligible:
        raise ValueError("No completed papers contain relevant findings for the review")

    review = invoke_writer(topic, eligible, model=model, runner=runner)

    output_dir = output_dir or os.environ.get("REVIEW_OUTPUT_DIR", "output")
    generated_at = datetime.now(timezone.utc).isoformat()
    path = save_review(topic, review, eligible, output_dir, generated_at)

    return {
        "success": True,
        "path": str(path),
        "review": review,
        "paper_count": len(eligible),
        "skipped_count": len(skipped),
        "generated_at": generated_at,
        "sources": [
            {"id": record["id"], "filename": record["filename"]}
            for record in eligible
        ],
    }


def main():
    parser = argparse.ArgumentParser(
        description="Generate an IEEE-style literature review with OpenCode"
    )
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()

    try:
        topic, research = load_payload(sys.stdin)
        result = write_review(
            topic=topic,
            research=research,
            output_dir=args.output_dir,
            model=args.model,
        )
    except Exception as error:
        print(json.dumps({"success": False, "error": str(error)}))
        print(f"Literature writer failed: {error}", file=sys.stderr)
        sys.exit(1)

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
