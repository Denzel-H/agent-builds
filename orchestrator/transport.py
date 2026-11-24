import asyncio
import shlex
import json
from pathlib import Path


def _encode_input(input_data):
    if input_data is None:
        return None
    if isinstance(input_data, bytes):
        return input_data
    return str(input_data).encode("utf-8")


async def execute_command(command, execution, input_data=None):
    """Run a worker command locally or over noninteractive SSH.

    ``input_data`` is sent on stdin when present, which keeps large research
    payloads out of shell arguments.  All other runs use DEVNULL so unattended
    worker processes can never wait for interactive input.
    """
    mode = execution["mode"]
    project_dir = execution["project_dir"]
    stdin = (
        asyncio.subprocess.PIPE
        if input_data is not None
        else asyncio.subprocess.DEVNULL
    )

    if mode == "local":
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=project_dir,
            stdin=stdin,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    elif mode == "ssh":
        host = execution["host"]

        remote_command = (
            f"cd {shlex.quote(project_dir)} && "
            + shlex.join(command)
        )

        process = await asyncio.create_subprocess_exec(
            "ssh",
            "-o", "BatchMode=yes",
            host,
            remote_command,
            stdin=stdin,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    else:
        raise ValueError(f"Unsupported execution mode: {mode}")

    stdout, stderr = await process.communicate(_encode_input(input_data))

    if process.returncode != 0:
        raise RuntimeError(
            f"Worker command failed: {stderr.decode().strip()}"
        )

    return stdout.decode().strip()


async def get_pending_papers(execution):
    output = await execute_command(
        ["python3", "worker/database/cli.py", "pending"],
        execution,
    )

    papers = json.loads(output)
    if not isinstance(papers, list):
        raise ValueError("Worker returned invalid pending papers data")
    return papers


async def get_completed_research(execution):
    """Retrieve every completed paper through the worker's CLI."""
    output = await execute_command(
        ["python3", "worker/database/cli.py", "completed"],
        execution,
    )

    papers = json.loads(output)
    if not isinstance(papers, list):
        raise ValueError("Worker returned invalid completed research data")
    return papers


async def get_research_stats(execution):
    output = await execute_command(
        ["python3", "worker/database/cli.py", "stats"],
        execution,
    )

    stats = json.loads(output)
    if not isinstance(stats, dict):
        raise ValueError("Worker returned invalid paper statistics")
    return stats


async def get_papers(execution):
    output = await execute_command(
        ["python3", "worker/database/cli.py", "papers"],
        execution,
    )

    papers = json.loads(output)
    if not isinstance(papers, list):
        raise ValueError("Worker returned invalid paper list")
    return papers


async def execute_paper(paper_id, topic, filename, execution):
    output = await execute_command(
        [
            "python3",
            "worker/research.py",
            "--paper-id", str(paper_id),
            "--topic", topic,
            "--filename", filename,
        ],
        execution,
    )

    return json.loads(output)


async def generate_review(topic, research, execution, output_dir=None):
    """Invoke the literature writer with the full completed research dataset."""
    payload = {
        "topic": topic,
        "research": research,
    }
    command = ["python3", "worker/literature_writer.py"]
    if output_dir:
        command += ["--output-dir", output_dir]

    output = await execute_command(
        command,
        execution,
        input_data=json.dumps(payload, ensure_ascii=False),
    )

    result = json.loads(output)
    if not isinstance(result, dict):
        raise ValueError("Worker returned invalid literature writer result")
    return result


async def get_investigation_status(execution):
    output = await execute_command(
        ["python3", "worker/database/cli.py", "status"],
        execution,
    )

    return json.loads(output)["status"]


async def request_investigation_stop(execution):
    output = await execute_command(
        ["python3", "worker/database/cli.py", "stop"],
        execution,
    )

    return json.loads(output)


async def start_investigation(execution):
    output = await execute_command(
        ["python3", "worker/database/cli.py", "start"],
        execution,
    )

    return json.loads(output)


async def finish_investigation(execution):
    output = await execute_command(
        ["python3", "worker/database/cli.py", "finish"],
        execution,
    )

    return json.loads(output)


async def transfer_paper(paper, execution):
    paper = Path(paper).resolve()

    if execution["mode"] == "local":
        return str(paper)

    if execution["mode"] != "ssh":
        raise ValueError("Unsupported execution mode")

    host = execution["host"]
    remote_dir = f"{execution['project_dir']}/papers"

    await execute_command(
        ["mkdir", "-p", remote_dir],
        execution,
    )

    process = await asyncio.create_subprocess_exec(
        "sftp",
        "-b", "-",
        "-o", "BatchMode=yes",
        host,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Quote the remote path according to SFTP's command syntax.
    destination = f"{remote_dir}/{paper.name}"
    batch = f'put "{paper}" "{destination}"\n'

    stdout, stderr = await process.communicate(batch.encode())

    if process.returncode != 0:
        raise RuntimeError(
            f"PDF transfer failed: {stderr.decode().strip()}"
        )

    return f"papers/{paper.name}"


async def register_paper(filename, execution):
    output = await execute_command(
        [
            "python3",
            "worker/database/cli.py",
            "add",
            "--filename", filename,
        ],
        execution,
    )

    return json.loads(output)


async def paper_exists(filename, execution):
    output = await execute_command(
        [
            "python3",
            "worker/database/cli.py",
            "exists",
            "--filename", filename,
        ],
        execution,
    )

    return json.loads(output)["exists"]


if __name__ == "__main__":
    execution = {
        "mode": "ssh",
        "host": "worker1",
        "project_dir": "/home/worker-android-env-1/agent-builds",
    }

    async def test():
        print(await paper_exists("papers/transport-test.pdf", execution))
        print(await paper_exists("papers/nonexistent.pdf", execution))

    asyncio.run(test())
