import asyncio
import shlex
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


if __name__ == "__main__":
    execution = {
        "mode": "ssh",
        "host": "worker1",
        "project_dir": "/home/worker-android-env-1/agent-builds",
    }


    result = asyncio.run(
        execute_command(
            [
                "python3",
                "worker/research.py",
                "--paper-id", "2",  # Replace with your actual new paper ID
                "--topic", "Counter-UAS detection methods",
                "--filename", "test.pdf",
            ],
            execution,
        )
    )

    print(result)