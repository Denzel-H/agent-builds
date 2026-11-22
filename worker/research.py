import subprocess
import json
import argparse
from database.db import (
    claim_paper,
    save_findings,
    failed_paper,
)

def research_paper(topic, filename):
    prompt = (
        f"Research topic: {topic}\n"
        f"Paper: {filename}\n"
        "Analyze this paper and return the structured JSON response."
    )

    result = subprocess.run(
        ["opencode",
         "run",
        "--agent", 
        "paper-researcher", 
        "--model",
        "openai/gpt-6-luna",
        prompt],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(f"OpenCode failed: {result.stderr}")

    response = json.loads(result.stdout)

    if response.get("error"):
        raise RuntimeError(response["error"])

    return response

def process_paper(paper_id, topic, filename):
    if not claim_paper(paper_id):
        return False
    try:
        result = research_paper(topic, filename)
        saved = save_findings(
            paper_id,
            result["citation"],
            result["findings"],
        )
        if not saved:
            raise RuntimeError(f"FAILED to save research findings for {filename}!")

        return True
    except Exception:
        failed_paper(paper_id)
        raise

def main():
    parser = argparse.ArgumentParser(
        description="Process a research paper using OpenCode"
    )

    parser.add_argument("--paper-id", type=int, required=True)
    parser.add_argument("--topic", required=True)
    parser.add_argument("--filename", required=True)

    args = parser.parse_args()

    process_paper(
        paper_id=args.paper_id,
        topic=args.topic,
        filename=args.filename,
    )


if __name__ == "__main__":
    main()
