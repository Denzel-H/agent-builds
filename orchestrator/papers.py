import time
from pathlib import Path


def scan_papers(paper_directory):
    directory = Path(paper_directory).expanduser().resolve()

    if not directory.is_dir():
        raise NotADirectoryError(
            f"Paper directory does not exist: {directory}"
        )

    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix.lower() == ".pdf"
    )

def is_paper_ready(path):
    path = Path(path)

    if not path.is_file():
        return False

    if path.stat().st_size == 0:
        return False

    try:
        with path.open("rb") as file:
            return file.read(5) == b"%PDF-"
    except OSError:
        return False

def is_paper_stable(path, minimum_age=5):
    path = Path(path)

    try:
        info = path.stat()
    except OSError:
        return False

    if info.st_size == 0:
        return False

    age = time.time() - info.st_mtime

    return age >= minimum_age

def get_ready_papers(paper_directory):
    ready = []

    for paper in scan_papers(paper_directory):
        if not is_paper_ready(paper):
            continue

        if not is_paper_stable(paper):
            continue

        ready.append(paper)

    return ready

if __name__ == "__main__":
    directory = input("PDF directory: ").strip()

    for paper in scan_papers(directory):
        print(paper)