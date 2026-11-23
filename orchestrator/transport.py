import asyncio
import shlex
import json
from pathlib import Path

async def execute_command(command, execution):
    mode = execution["mode"]
    project_dir = execution["project_dir"]

    if mode == "local":
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=project_dir,
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
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

    else:
        raise ValueError(f"Unsupported execution mode: {mode}")

    stdout, stderr = await process.communicate()

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

    return json.loads(output)

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

if __name__ == "__main__":
    execution = {
        "mode": "ssh",
        "host": "worker1",
        "project_dir": "/home/worker-android-env-1/agent-builds",
    }

    status = asyncio.run(get_investigation_status(execution))
    print(status)