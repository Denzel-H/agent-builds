# LangGraph Literature Research System

A small distributed research prototype. LangGraph on the orchestrator (MacBook Neo)
discovers PDFs, dispatches paper researchers, and explicitly generates one
IEEE-style literature review at the end. OpenCode agents do the paper analysis
and the synthesis; Python and SQLite do the deterministic control work.

## Architecture

```
MacBook Neo (orchestrator)
  orchestrator/cli.py      human-facing commands
  orchestrator/graph.py    LangGraph research loop + one-shot finalization graph
  orchestrator/papers.py   local PDF discovery (filename-based dedupe)
  orchestrator/transport.py local subprocess or noninteractive SSH transport
  orchestrator/review_store.py  durable local Markdown output on the Neo

Linux VM (worker, e.g. SSH alias `worker1`)
  worker/research.py            runs `opencode run --agent paper-researcher`
  worker/literature_writer.py   runs `opencode run --agent literature-writer`
  worker/database/cli.py        SQLite control and research retrieval
  worker/database/research.db   authoritative paper status + findings
  papers/                       transferred PDFs
```

The three OpenCode agent definitions in `.opencode/agents/` are authoritative:

- `paper-researcher.md` — extracts an IEEE citation and topic-relevant findings
  from one paper. An empty `findings` array is a valid "nothing relevant" result.
- `literature-writer.md` — synthesizes all supplied records into thematic
  Markdown with IEEE numbered citations. It never invents sources.
- `research-coordinator.md` — the human-facing conversation layer. It collects
  topic, PDF directory, execution mode, host alias, project directory and
  concurrency, then delegates execution to `orchestrator/cli.py`.

LangGraph owns dispatch, concurrency, polling and lifecycle transitions. The
coordinator never launches researchers itself. Never put passwords, private
keys, API keys or passphrases into prompts, config files or graph state.

## Requirements

- Python 3.11+ with `langgraph` installed.
- `opencode` on PATH in every worker environment.
- For SSH mode: a working `~/.ssh/config` host alias with key-based,
  noninteractive authentication. Check with
  `ssh -o BatchMode=yes <host-alias> "echo READY"`.
  Remote agents cannot answer password prompts. Use a passphrase-less Ed25519
  key, or one already unlocked through `ssh-agent`. Never use `sshpass`.

## Database initialization

The database lives on the worker. On the remote machine:

```bash
cd /home/worker-android-env-1/agent-builds
python3 worker/database/init_db.py
```

`init_db.py` uses `CREATE TABLE IF NOT EXISTS`, so it is safe to run on an
existing database. Do not delete a database during normal operation.

If a schema change is ever needed, change **only** `worker/database/init_db.py`,
then (and only then) deliberately rebuild the remote database:

```bash
ssh worker1 "rm -f /home/worker-android-env-1/agent-builds/worker/database/research.db && python3 /home/worker-android-env-1/agent-builds/worker/database/init_db.py"
```

No schema change is needed for the current implementation.

## Configuration

The CLI accepts either flags or a JSON config file (matching the coordinator
agent's structure):

```json
{
  "topic": "Counter-UAS detection methods",
  "paper_directory": "/Users/oa/research-papers/test",
  "execution": {
    "mode": "ssh",
    "host": "worker1",
    "project_dir": "/home/worker-android-env-1/agent-builds"
  },
  "max_workers": 3,
  "output_dir": "/Users/oa/repos/agent-builds/output"
}
```

Flags override JSON values. For local execution use `--mode local` and either
omit `--project-dir` (defaults to this repository) or supply its absolute path.

The PDF directory is always on the machine running the coordinator and
LangGraph, even for SSH workers. It may start empty. Drop more PDFs into it at
any time; only complete, readable, stable (`>= 5 s` old) files are registered.
Deduplication is by filename, so a re-run needs new basenames.

## Full end-to-end example

Start research (blocks until you request a stop; use a second terminal for the
other commands):

```bash
cd /Users/oa/repos/agent-builds

python3 orchestrator/cli.py start \
  --topic "Counter-UAS detection methods" \
  --paper-directory /Users/oa/research-papers/test \
  --mode ssh \
  --host worker1 \
  --project-dir /home/worker-android-env-1/agent-builds \
  --max-workers 3
```

Monitor progress from another terminal:

```bash
python3 orchestrator/cli.py status \
  --mode ssh --host worker1 \
  --project-dir /home/worker-android-env-1/agent-builds
```

This reports the control status, paper counts (`pending`, `processing`,
`completed`, `failed`, `total`) and the latest local review path. Add
`--papers` to also get `paper_details`: each paper's id, filename, status,
citation and `finding_count`. The coordinator uses this to tell you which
papers have completed.

Request a graceful stop. This only stops **dispatching** new researchers;
currently running researchers finish, pending papers stay pending, and the
investigation becomes `stopped`. It does **not** generate a review:

```bash
python3 orchestrator/cli.py stop \
  --mode ssh --host worker1 \
  --project-dir /home/worker-android-env-1/agent-builds
```

Explicitly generate the literature review after research has stopped. This is
a separate one-shot graph and runs the writer once per invocation. It fetches
**all** completed research from SQLite, excludes papers without relevant
findings, and saves a new Markdown file on the Neo:

```bash
python3 orchestrator/cli.py finalize \
  --topic "Counter-UAS detection methods" \
  --mode ssh --host worker1 \
  --project-dir /home/worker-android-env-1/agent-builds
```

Retrieve the result:

```bash
python3 orchestrator/cli.py review
# {"found": true, "path": "/Users/oa/repos/agent-builds/output/review-....md"}

python3 orchestrator/cli.py review --content   # print the Markdown
open "$(python3 orchestrator/cli.py review | python3 -c 'import json,sys; print(json.load(sys.stdin)["path"])')"
```

The default output directory is `<repo>/output`. Override it with
`--output-dir` (or the `REVIEW_OUTPUT_DIR` environment variable). Filenames are
timestamped with a random suffix, so previous reviews are never overwritten.
Each file has YAML front matter with the topic, UTC generation time, source
count and source filenames/paper IDs.

A worker-side copy is also written under the worker's `output/` directory; the
Neo's copy is the durable human-facing artifact.

## Coordinator-only operation

You can stay entirely in the `research-coordinator` OpenCode agent. Select it
in the TUI (`/agent`) or start it with:

```bash
cd /Users/oa/repos/agent-builds
opencode run --agent research-coordinator \
  "Research counter-UAS detection using /Users/oa/research-papers/test on worker1 with 3 concurrent researchers"
```

The coordinator asks for missing details, verifies noninteractive SSH, and then
controls LangGraph by sending commands to the project's LangGraph CLI,
`orchestrator/cli.py`. It does not import Python modules or call `graph.py`
directly. To keep the conversation responsive, it uses `start --background`:

```bash
python3 orchestrator/cli.py start \
  --topic "Counter-UAS detection methods" \
  --paper-directory /Users/oa/research-papers/test \
  --mode ssh --host worker1 \
  --project-dir /home/worker-android-env-1/agent-builds \
  --max-workers 3 \
  --background
```

This returns immediately with a JSON `pid` and log path (default
`output/research.log`). The coordinator then runs `status`, `stop`, `finalize`,
and `review` for you and reports the Markdown location. Use a foreground
`start` (without `--background`) only when you want the terminal to block until
research is stopped. Saying **"finish"**, "finalize", or "write the review"
makes the coordinator run `finalize`; saying **"stop"** only stops research and
does not generate a review.

## Development end-to-end test

The original test harness is preserved and extended in `orchestrator/graph.py`.
It uses the configured SSH alias `worker1`, the remote project directory above,
the PDF directory `/Users/oa/research-papers/test`, and three concurrent
researchers. It starts research, waits 10 seconds, requests a graceful stop,
waits for active workers, collects completed research, runs the writer once,
and prints the final Markdown path:

```bash
python3 orchestrator/graph.py
```

To rerun it with fresh papers, replace the contents of
`/Users/oa/research-papers/test` with copies that have **different names**,
because the remote database deduplicates by filename:

```bash
mkdir -p /Users/oa/research-papers/test
for f in /Users/oa/research-papers/counter-uas/*.pdf; do
  cp "$f" "/Users/oa/research-papers/test/run2-$(basename "$f")"
done
```

Edit `paper_directory` in the `__main__` block of `orchestrator/graph.py` if you
want to use a different folder. Do not reuse existing filenames if you expect
new research.

## Tests

Tests mock OpenCode and SSH, so they do not spend API credits:

```bash
python3 -m unittest discover -s tests -v
```

Coverage includes completed-research retrieval and JSON deserialization,
malformed/empty input, writer invocation and failure handling, graceful
shutdown, explicit finalization, duplicate-writer prevention, full-dataset
handoff, Markdown generation/retrieval, concurrency limits, and local/SSH
transport interfaces.

## Troubleshooting

- **`ssh: connect to host ...` / password prompt** — fix `~/.ssh/config` and
  verify `ssh -o BatchMode=yes <alias> "echo READY"` before starting.
- **`Worker command failed: ...`** — the CLI printed worker stderr. Check that
  the remote project directory contains `worker/database/cli.py` and that the
  remote database exists.
- **`No completed papers with relevant findings`** — the researchers either
  have not finished, found nothing relevant, or failed. Check `status`; a
  completed paper with empty findings is not a failure and is not sent to the
  writer.
- **`Writer output is missing ...` / `OpenCode literature-writer failed`** —
  the writer response was invalid or OpenCode errored. `finalize` reports this
  explicitly; no Markdown is saved on failure.
- **Papers processed again** — the filename already existed? Confirm the new
  copies have new basenames. Duplicate filenames are intentionally skipped.
- **Research appears idle** — an empty queue is normal. New PDFs are discovered
  while the investigation is running; only `stop` ends it.
- **High recursion limit** — long-running investigations use polling. Raise
  `--recursion-limit` if you expect to run for many hours without stopping.
