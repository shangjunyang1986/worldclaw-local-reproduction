from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from .store import JobStore


class JobCancelled(RuntimeError):
    pass


class CommandFailed(RuntimeError):
    pass


class CommandRunner:
    def __init__(self, store: JobStore, root: Path):
        self.store = store
        self.root = root

    @staticmethod
    def _stamp() -> str:
        return datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")

    def log(self, job: dict, stage: str, message: str) -> None:
        log_path = Path(job["output_dir"]) / "logs/pipeline.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as target:
            target.write(f"[{self._stamp()}] [{stage}] {message.rstrip()}\n")

    def run(
        self,
        job: dict,
        stage: str,
        command: Iterable[str | Path],
        *,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> None:
        cmd = [str(part) for part in command]
        self.log(job, stage, "$ " + " ".join(cmd))
        process_env = os.environ.copy()
        if env:
            process_env.update(env)
        process = subprocess.Popen(
            cmd,
            cwd=str(cwd or self.root),
            env=process_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        self.store.update_job(job["id"], process_pid=process.pid)
        selector = selectors.DefaultSelector()
        assert process.stdout is not None
        selector.register(process.stdout, selectors.EVENT_READ)
        try:
            while process.poll() is None:
                current = self.store.get_job(job["id"])
                if current["cancel_requested"]:
                    self.log(job, stage, "Cancellation requested; terminating process group")
                    os.killpg(process.pid, signal.SIGTERM)
                    deadline = time.monotonic() + 10
                    while process.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.2)
                    if process.poll() is None:
                        os.killpg(process.pid, signal.SIGKILL)
                    raise JobCancelled("Job cancelled by user")
                for key, _ in selector.select(timeout=0.5):
                    line = key.fileobj.readline()
                    if line:
                        self.log(job, stage, line)
            for line in process.stdout:
                self.log(job, stage, line)
        finally:
            selector.close()
            self.store.update_job(job["id"], process_pid=None)
        if process.returncode:
            raise CommandFailed(f"Stage {stage} exited with code {process.returncode}")
