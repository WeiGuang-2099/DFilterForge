"""Bounded Linux subprocess boundary for the pinned tshark executable."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from typing import BinaryIO, cast

PINNED_TSHARK_VERSION = "4.6.8"
_SEARCH_PATH = "/opt/wireshark/bin:/usr/bin:/bin"


class RunnerError(RuntimeError):
    """An execution error containing only a stable code and safe message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class RunnerLimits:
    """Resource limits for one version check or capture execution."""

    timeout_seconds: float = 5.0
    max_capture_bytes: int = 16 * 1024 * 1024
    max_filter_bytes: int = 8192
    max_stdout_bytes: int = 2 * 1024 * 1024
    max_stderr_bytes: int = 64 * 1024
    max_frames: int = 100_000

    def __post_init__(self) -> None:
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("The runner timeout must be positive and finite")
        values = cast(
            tuple[object, ...],
            (
                self.max_capture_bytes,
                self.max_filter_bytes,
                self.max_stdout_bytes,
                self.max_stderr_bytes,
                self.max_frames,
            ),
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value <= 0
            for value in values
        ):
            raise ValueError(
                "Runner byte and frame limits must be positive integers"
            )


@dataclass(frozen=True, slots=True)
class RunResult:
    """Packet numbers and identity of the exact capture snapshot executed."""

    frames: tuple[int, ...]
    runtime_ms: float
    capture_sha256: str


@contextmanager
def _capture_snapshot(
    capture: Path, max_bytes: int
) -> Generator[tuple[BinaryIO, str], None, None]:
    """Open without following a final symlink and freeze bounded input bytes."""
    try:
        descriptor = os.open(
            capture, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        )
        with os.fdopen(descriptor, "rb") as source:
            source_stat = os.fstat(source.fileno())
            if not stat.S_ISREG(source_stat.st_mode):
                raise RunnerError(
                    "capture_invalid", "Capture must be a readable regular file"
                )
            if source_stat.st_size > max_bytes:
                raise RunnerError(
                    "capture_too_large",
                    "Capture exceeds the configured byte limit",
                )
            with tempfile.TemporaryFile(mode="w+b") as snapshot:
                digest = hashlib.sha256()
                copied = 0
                while chunk := source.read(
                    min(64 * 1024, max_bytes - copied + 1)
                ):
                    copied += len(chunk)
                    if copied > max_bytes:
                        raise RunnerError(
                            "capture_too_large",
                            "Capture exceeds the configured byte limit",
                        )
                    digest.update(chunk)
                    snapshot.write(chunk)
                snapshot.seek(0)
                yield snapshot, digest.hexdigest()
    except (OSError, ValueError):
        raise RunnerError(
            "capture_invalid", "Capture cannot be read or safely snapshotted"
        ) from None


def _parse_frames(output: bytes, maximum: int) -> tuple[int, ...]:
    if not output:
        return ()
    lines = output.removesuffix(b"\n").split(b"\n")
    if len(lines) > maximum:
        raise RunnerError(
            "frame_limit", "Result exceeds the configured frame limit"
        )
    frames: list[int] = []
    for line in lines:
        if not re.fullmatch(rb"[1-9][0-9]{0,9}", line):
            raise RunnerError(
                "output_invalid", "tshark returned invalid frame output"
            )
        number = int(line)
        if number > 0xFFFFFFFF or (frames and number <= frames[-1]):
            raise RunnerError(
                "output_invalid", "tshark returned invalid frame output"
            )
        frames.append(number)
    return tuple(frames)


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    """Kill the process group, including descendants of an exited parent."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


class TsharkRunner:
    """Execute captures using a fixed profile in a hardened Linux container.

    The image must build tshark with native plugins and Lua disabled. The
    subprocess boundary additionally discards inherited configuration and
    environment, disables name resolution, and exposes only frame numbers.
    """

    def __init__(
        self, tshark: str = "tshark", limits: RunnerLimits = RunnerLimits()
    ) -> None:
        self._tshark = tshark
        self._limits = limits
        self._executable_path: Path | None = None
        self._version: str | None = None

    @property
    def limits(self) -> RunnerLimits:
        """Return the immutable resource policy used by this runner."""
        return self._limits

    @property
    def executable_path(self) -> Path:
        """Resolve the executable against the fixed search path."""
        if not sys.platform.startswith("linux"):
            raise RunnerError(
                "platform_unsupported",
                "The tshark runner requires a Linux container",
            )
        if self._executable_path is None:
            resolved = shutil.which(self._tshark, path=_SEARCH_PATH)
            if resolved is None:
                raise RunnerError("tshark_unavailable", "tshark is unavailable")
            self._executable_path = Path(resolved).resolve()
        return self._executable_path

    def version(self) -> str:
        """Check the pinned version within the configured execution limits."""
        if self._version is None:
            output, _ = self._execute(["--version"])
            first_line = output.split(b"\n", 1)[0]
            match = re.fullmatch(
                rb"TShark \(Wireshark\) "
                rb"([0-9]+\.[0-9]+\.[0-9]+)(?:\.|[ \t].*)?",
                first_line,
            )
            if (
                match is None
                or match.group(1).decode("ascii") != PINNED_TSHARK_VERSION
            ):
                raise RunnerError(
                    "tshark_version_mismatch",
                    "tshark must be exactly version 4.6.8",
                )
            self._version = PINNED_TSHARK_VERSION
        return self._version

    def run(self, capture: Path, display_filter: str) -> RunResult:
        """Return validated frame numbers with sanitized failure messages."""
        try:
            filter_bytes = display_filter.encode("utf-8")
        except UnicodeEncodeError:
            raise RunnerError(
                "filter_invalid", "Display filter is invalid"
            ) from None
        if not display_filter.strip() or "\x00" in display_filter:
            raise RunnerError(
                "filter_invalid", "Display filter is empty or invalid"
            )
        if len(filter_bytes) > self._limits.max_filter_bytes:
            raise RunnerError(
                "filter_too_large",
                "Display filter exceeds the configured byte limit",
            )
        self.version()
        with _capture_snapshot(capture, self._limits.max_capture_bytes) as (
            snapshot,
            capture_hash,
        ):
            output, runtime_ms = self._execute(
                [
                    "-n",
                    "-r",
                    f"/proc/self/fd/{snapshot.fileno()}",
                    "-Y",
                    display_filter,
                    "-T",
                    "fields",
                    "-e",
                    "frame.number",
                ],
                pass_fds=(snapshot.fileno(),),
                frame_limit=self._limits.max_frames,
            )
        return RunResult(
            frames=_parse_frames(output, self._limits.max_frames),
            runtime_ms=runtime_ms,
            capture_sha256=capture_hash,
        )

    def _execute(
        self,
        arguments: list[str],
        pass_fds: tuple[int, ...] = (),
        frame_limit: int | None = None,
    ) -> tuple[bytes, float]:
        environment = {
            "PATH": _SEARCH_PATH,
            "HOME": "/nonexistent",
            "XDG_CONFIG_HOME": "/nonexistent",
            "WIRESHARK_CONFIG_DIR": "/nonexistent",
            "WIRESHARK_PLUGIN_DIR": "/nonexistent",
            "LANG": "C",
            "LC_ALL": "C",
            "TZ": "UTC",
        }
        started = time.monotonic()
        try:
            # Kill the whole group before waiting or closing pipes in cleanup.
            # pylint: disable-next=consider-using-with
            process = subprocess.Popen(
                [str(self.executable_path), *arguments],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                close_fds=True,
                start_new_session=True,
                pass_fds=pass_fds,
                env=environment,
                cwd="/",
            )
        except (OSError, ValueError):
            raise RunnerError(
                "tshark_unavailable", "tshark cannot be started"
            ) from None
        try:
            output = self._read_output(process, started, frame_limit)
            remaining = self._limits.timeout_seconds - (
                time.monotonic() - started
            )
            if remaining <= 0:
                raise subprocess.TimeoutExpired(
                    "tshark", self._limits.timeout_seconds
                )
            if process.wait(timeout=remaining) != 0:
                raise RunnerError(
                    "tshark_failed",
                    "tshark rejected the capture or display filter",
                )
            return output, (time.monotonic() - started) * 1000
        except subprocess.TimeoutExpired:
            raise RunnerError(
                "timeout", "tshark exceeded the execution time limit"
            ) from None
        except OSError:
            raise RunnerError(
                "tshark_failed", "tshark execution failed"
            ) from None
        finally:
            _kill_process_group(process)
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()

    def _read_output(
        self,
        process: subprocess.Popen[bytes],
        started: float,
        frame_limit: int | None,
    ) -> bytes:
        assert process.stdout is not None and process.stderr is not None
        stdout = bytearray()
        sizes = {"stdout": 0, "stderr": 0}
        maximums = {
            "stdout": self._limits.max_stdout_bytes,
            "stderr": self._limits.max_stderr_bytes,
        }
        lines = 0
        group_cleaned = False
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            while selector.get_map():
                if not group_cleaned and process.poll() is not None:
                    _kill_process_group(process)
                    group_cleaned = True
                remaining = self._limits.timeout_seconds - (
                    time.monotonic() - started
                )
                if remaining <= 0:
                    raise subprocess.TimeoutExpired(
                        "tshark", self._limits.timeout_seconds
                    )
                for key, _ in selector.select(timeout=min(remaining, 0.05)):
                    chunk = os.read(key.fd, 64 * 1024)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    stream = cast(str, key.data)
                    sizes[stream] += len(chunk)
                    if sizes[stream] > maximums[stream]:
                        raise RunnerError(
                            "output_limit",
                            "tshark exceeded the output byte limit",
                        )
                    if stream == "stdout":
                        stdout.extend(chunk)
                        lines += chunk.count(b"\n")
                        if frame_limit is not None and lines > frame_limit:
                            raise RunnerError(
                                "frame_limit",
                                "Result exceeds the configured frame limit",
                            )
        return bytes(stdout)
