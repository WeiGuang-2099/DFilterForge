"""Linux-container tests for bounded and sanitized tshark subprocess execution."""

from dataclasses import replace
import hashlib
import os
from pathlib import Path
import signal
import sys
import textwrap
import time

import pytest

from dfilterforge.model_split import generate_model_split
from dfilterforge.runner import RunnerError
from dfilterforge.runner import RunnerLimits
from dfilterforge.runner import TsharkRunner

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="Runner requires a Linux container",
)

# The exact three-line, 85-byte stderr tshark 4.6.8 prints for an
# unresolvable field name.
_UNKNOWN_FIELD_STDERR = (
    b'tshark: "ip.ttll" is not a valid protocol or protocol field.\n'
    b"    ip.ttll\n"
    b"    ^~~~~~~\n"
)


def _fake_tshark(
    tmp_path: Path,
    body: str,
    *,
    version: str = "4.6.8",
    version_body: str | None = None,
) -> str:
    executable = tmp_path / "fake tshark"
    check = (
        version_body
        if version_body is not None
        else f"print('TShark (Wireshark) {version}.')"
    )
    executable.write_text(
        f"#!{sys.executable}\n"
        "import os\nimport subprocess\nimport sys\nimport time\n"
        "from pathlib import Path\n"
        "if '--version' in sys.argv:\n"
        + textwrap.indent(textwrap.dedent(check), "    ")
        + "\n    sys.exit(0)\n"
        + textwrap.dedent(body),
        encoding="utf-8",
        newline="\n",
    )
    executable.chmod(0o755)
    return str(executable)


def _capture(tmp_path: Path, data: bytes = b"private capture content") -> Path:
    capture = tmp_path / "capture with spaces.pcap"
    capture.write_bytes(data)
    return capture


def _model_split_capture(tmp_path: Path) -> Path:
    generate_model_split(tmp_path)
    return tmp_path / "captures" / "semantic-11.pcap"


def test_executes_argv_with_private_snapshot_and_minimal_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = _capture(tmp_path)
    marker = tmp_path / "shell-was-executed"
    display_filter = f'tcp || $(touch "{marker}"); echo secret'
    monkeypatch.setenv("SECRET_PACKET_TOKEN", "sensitive")
    monkeypatch.setenv("WIRESHARK_CONFIG_DIR", "/unsafe/config")
    executable = _fake_tshark(
        tmp_path,
        f"""
        assert sys.argv[1] == '-n'
        assert sys.argv[3].startswith('/proc/self/fd/')
        assert Path(sys.argv[3]).read_bytes() == {capture.read_bytes()!r}
        assert sys.argv[4:] == ['-Y', {display_filter!r}, '-T', 'fields', '-e', 'frame.number']
        assert 'SECRET_PACKET_TOKEN' not in os.environ
        assert os.environ['WIRESHARK_CONFIG_DIR'] == '/nonexistent'
        assert os.environ['HOME'] == '/nonexistent'
        assert os.getcwd() == '/'
        assert sys.stdin.read() == ''
        print('1\\n3\\n7')
        """,
    )
    runner = TsharkRunner(executable)

    result = runner.run(capture, display_filter)

    assert result.frames == (1, 3, 7)
    assert (
        result.capture_sha256
        == hashlib.sha256(capture.read_bytes()).hexdigest()
    )
    assert result.runtime_ms > 0
    assert runner.version() == "4.6.8"
    assert runner.executable_path == Path(executable)
    assert runner.limits == RunnerLimits()
    assert not marker.exists()


def test_capture_hash_identifies_executed_snapshot_when_original_changes(
    tmp_path: Path,
) -> None:
    capture = _capture(tmp_path, b"original capture")
    executable = _fake_tshark(
        tmp_path,
        f"""
        Path({str(capture)!r}).write_bytes(b'changed after snapshot')
        assert Path(sys.argv[3]).read_bytes() == b'original capture'
        print('2')
        """,
    )

    result = TsharkRunner(executable).run(capture, "tcp")

    assert result.frames == (2,)
    assert (
        result.capture_sha256 == hashlib.sha256(b"original capture").hexdigest()
    )


@pytest.mark.parametrize("output, expected", [(b"", ()), (b"2", (2,))])
def test_accepts_empty_result_and_missing_final_newline(
    tmp_path: Path, output: bytes, expected: tuple[int, ...]
) -> None:
    executable = _fake_tshark(tmp_path, f"os.write(1, {output!r})")

    assert (
        TsharkRunner(executable).run(_capture(tmp_path), "tcp").frames
        == expected
    )


@pytest.mark.parametrize(
    "output",
    [
        b"0\n",
        b"-1\n",
        b"1\n1\n",
        b"3\n2\n",
        b"01\n",
        b"1.0\n",
        b"1\n\n",
        b" 1\n",
        b"4294967296\n",
        b"9" * 5000,
        b"sensitive payload\n",
        b"\xff\n",
    ],
)
def test_rejects_invalid_frame_output_without_exposing_content(
    tmp_path: Path, output: bytes
) -> None:
    executable = _fake_tshark(tmp_path, f"os.write(1, {output!r})")

    with pytest.raises(RunnerError, match="invalid frame output") as error:
        TsharkRunner(executable).run(_capture(tmp_path), "tcp")

    assert error.value.code == "output_invalid"
    assert "sensitive" not in str(error.value)


@pytest.mark.parametrize("stream", [1, 2])
def test_enforces_separate_output_byte_limits(
    tmp_path: Path, stream: int
) -> None:
    executable = _fake_tshark(tmp_path, f"os.write({stream}, b'x' * 8192)")
    limits = RunnerLimits(max_stdout_bytes=128, max_stderr_bytes=128)

    with pytest.raises(RunnerError, match="output byte limit") as error:
        TsharkRunner(executable, limits).run(_capture(tmp_path), "tcp")

    assert error.value.code == "output_limit"


@pytest.mark.parametrize("output", [b"1\n2\n3\n", b"1\n2\n3"])
def test_enforces_frame_count_limit(tmp_path: Path, output: bytes) -> None:
    executable = _fake_tshark(tmp_path, f"os.write(1, {output!r})")

    with pytest.raises(RunnerError, match="frame limit") as error:
        TsharkRunner(executable, RunnerLimits(max_frames=2)).run(
            _capture(tmp_path), "tcp"
        )

    assert error.value.code == "frame_limit"


@pytest.mark.parametrize("close_pipes", [False, True])
def test_enforces_wall_timeout_even_after_output_pipes_close(
    tmp_path: Path, close_pipes: bool
) -> None:
    body = "os.close(1)\nos.close(2)\n" if close_pipes else ""
    executable = _fake_tshark(tmp_path, body + "time.sleep(30)")
    started = time.monotonic()

    with pytest.raises(RunnerError, match="execution time limit") as error:
        TsharkRunner(executable, RunnerLimits(timeout_seconds=0.3)).run(
            _capture(tmp_path), "tcp"
        )

    assert error.value.code == "timeout"
    assert time.monotonic() - started < 3


@pytest.mark.parametrize(
    "failure", ["timeout", "output", "success", "inherited"]
)
def test_kills_descendants_on_failure_and_normal_exit(
    tmp_path: Path, failure: str
) -> None:
    child_pid = tmp_path / "child.pid"
    endings = {
        "timeout": "time.sleep(30)",
        "output": "os.write(1, b'x' * 8192)\ntime.sleep(30)",
        "success": "print('1')",
        "inherited": "print('1')",
    }
    executable = _fake_tshark(
        tmp_path,
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], "
        f"stdout={'None' if failure == 'inherited' else 'subprocess.DEVNULL'}, "
        f"stderr={'None' if failure == 'inherited' else 'subprocess.DEVNULL'})\n"
        f"Path({str(child_pid)!r}).write_text(str(child.pid))\n"
        + endings[failure],
    )
    runner = TsharkRunner(
        executable, RunnerLimits(timeout_seconds=0.5, max_stdout_bytes=128)
    )

    if failure in {"success", "inherited"}:
        assert runner.run(_capture(tmp_path), "tcp").frames == (1,)
    else:
        with pytest.raises(RunnerError) as error:
            runner.run(_capture(tmp_path), "tcp")
        assert error.value.code == (
            "timeout" if failure == "timeout" else "output_limit"
        )

    pid = int(child_pid.read_text(encoding="utf-8"))
    process_stat = Path(f"/proc/{pid}/stat")
    deadline = time.monotonic() + 1
    while True:
        try:
            if process_stat.read_text(encoding="utf-8").split()[2] == "Z":
                break
        except (FileNotFoundError, ProcessLookupError):
            break
        assert time.monotonic() < deadline, "A child process survived cleanup"
        time.sleep(0.01)


@pytest.mark.parametrize(
    "returncode, expected",
    [
        (4, "filter_rejected"),
        (3, "capture_unreadable"),
        (14, "capture_unreadable"),
        (1, "tshark_failed"),
        (2, "tshark_failed"),
    ],
)
def test_exit_status_maps_to_code_without_stderr(
    tmp_path: Path, returncode: int, expected: str
) -> None:
    executable = _fake_tshark(
        tmp_path,
        "os.write(1, b'1\\n2\\n')\n"
        "os.write(2, b'private capture and secret filter')\n"
        f"sys.exit({returncode})",
    )

    with pytest.raises(RunnerError) as error:
        TsharkRunner(executable).run(
            _capture(tmp_path), "invalid secret filter"
        )

    assert error.value.code == expected
    assert "secret" not in str(error.value)
    assert "private" not in str(error.value)
    assert "secret" not in repr(error.value.args)
    assert "private" not in repr(error.value.args)


def test_signal_termination_is_a_generic_failure(tmp_path: Path) -> None:
    executable = _fake_tshark(
        tmp_path, f"os.kill(os.getpid(), {int(signal.SIGTERM)})"
    )

    with pytest.raises(RunnerError) as error:
        TsharkRunner(executable).run(_capture(tmp_path), "tcp")

    assert error.value.code == "tshark_failed"


def test_rejected_filter_with_worst_measured_stderr_is_not_an_output_limit(
    tmp_path: Path,
) -> None:
    executable = _fake_tshark(
        tmp_path, "os.write(2, b'x' * 24648)\nsys.exit(4)"
    )

    with pytest.raises(RunnerError) as error:
        TsharkRunner(executable).run(_capture(tmp_path), 'ip.ttl <= "abc"')

    assert RunnerLimits().max_stderr_bytes > 24648
    assert error.value.code == "filter_rejected"


def test_stderr_above_the_limit_is_still_an_output_limit(
    tmp_path: Path,
) -> None:
    executable = _fake_tshark(tmp_path, "os.write(2, b'x' * 8192)\nsys.exit(4)")

    with pytest.raises(RunnerError) as error:
        TsharkRunner(executable, RunnerLimits(max_stderr_bytes=128)).run(
            _capture(tmp_path), "tcp"
        )

    assert error.value.code == "output_limit"


def test_unknown_field_sentence_on_first_line_gives_filter_unknown_field(
    tmp_path: Path,
) -> None:
    executable = _fake_tshark(
        tmp_path, f"os.write(2, {_UNKNOWN_FIELD_STDERR!r})\nsys.exit(4)"
    )

    with pytest.raises(RunnerError) as error:
        TsharkRunner(executable).run(_capture(tmp_path), "ip.ttll")

    assert error.value.code == "filter_unknown_field"
    assert "ip.ttll" not in str(error.value)
    assert "ip.ttll" not in repr(error.value.args)


@pytest.mark.parametrize(
    "stderr, returncode, expected",
    [
        (
            b"tshark: Unexpected end of filter expression.\n"
            + _UNKNOWN_FIELD_STDERR,
            4,
            "filter_rejected",
        ),
        (_UNKNOWN_FIELD_STDERR, 3, "capture_unreadable"),
        (b"x" * 200 + _UNKNOWN_FIELD_STDERR, 4, "filter_rejected"),
        (
            b'tshark: "'
            + b"a" * 300
            + b'" is not a valid protocol or protocol field.\n',
            4,
            "filter_rejected",
        ),
    ],
)
def test_unknown_field_sentence_elsewhere_is_only_a_rejection(
    tmp_path: Path, stderr: bytes, returncode: int, expected: str
) -> None:
    executable = _fake_tshark(
        tmp_path, f"os.write(2, {stderr!r})\nsys.exit({returncode})"
    )

    with pytest.raises(RunnerError) as error:
        TsharkRunner(executable).run(_capture(tmp_path), "ip.ttll")

    assert error.value.code == expected


def test_stderr_head_stops_growing_after_the_first_bytes(
    tmp_path: Path,
) -> None:
    executable = _fake_tshark(
        tmp_path,
        "os.write(2, b'x' * 300)\n"
        "time.sleep(0.2)\n"
        f"os.write(2, {_UNKNOWN_FIELD_STDERR!r})\n"
        "sys.exit(4)",
    )

    with pytest.raises(RunnerError) as error:
        TsharkRunner(executable).run(_capture(tmp_path), "ip.ttll")

    assert error.value.code == "filter_rejected"


def test_version_and_report_failures_stay_generic(tmp_path: Path) -> None:
    failure = f"os.write(2, {_UNKNOWN_FIELD_STDERR!r})\nsys.exit(4)"
    report_directory = tmp_path / "report"
    report_directory.mkdir()
    version_directory = tmp_path / "version"
    version_directory.mkdir()
    report_executable = _fake_tshark(report_directory, failure)
    version_executable = _fake_tshark(
        version_directory,
        "raise AssertionError('must not run')",
        version_body=failure,
    )

    with pytest.raises(RunnerError) as report_error:
        TsharkRunner(report_executable).report("fields")
    with pytest.raises(RunnerError) as version_error:
        TsharkRunner(version_executable).version()

    assert report_error.value.code == "tshark_failed"
    assert version_error.value.code == "tshark_failed"


@pytest.mark.parametrize(
    "display_filter, capture_kind, expected",
    [
        ("tcp &&", "valid", "filter_rejected"),
        ('ip.ttl <= "abc"', "valid", "filter_rejected"),
        ("tcp.port in {80 443}", "valid", "filter_rejected"),
        ("foo(ip.ttl) == 1", "valid", "filter_rejected"),
        ("tcp", "truncated", "capture_unreadable"),
        ("tcp", "garbage", "capture_unreadable"),
        ("ip.ttll", "garbage", "filter_unknown_field"),
    ],
)
def test_real_tshark_separates_filter_rejection_from_capture_failure(
    tmp_path: Path, display_filter: str, capture_kind: str, expected: str
) -> None:
    capture = _model_split_capture(tmp_path)
    data = capture.read_bytes()
    truncated = tmp_path / "truncated.pcap"
    truncated.write_bytes(data[: len(data) // 2 + 7])
    garbage = tmp_path / "garbage.pcap"
    garbage.write_bytes(b"this is not a capture file\n" * 20)
    captures = {"valid": capture, "truncated": truncated, "garbage": garbage}

    with pytest.raises(RunnerError) as error:
        TsharkRunner().run(captures[capture_kind], display_filter)

    assert error.value.code == expected
    assert '"' not in str(error.value)


@pytest.mark.parametrize(
    "display_filter, expected_code, expected_frames",
    [
        ("ip.ttll == 64", "filter_unknown_field", 0),
        ("ip.ttl-1 == 63", "filter_unknown_field", 0),
        ("{ip.ttl-1} == 63", "filter_unknown_field", 0),
        ("ssl", None, 0),
        ("http.request.method == GET", None, 0),
        ("diameter.TCP-SYN == 01:02", None, 0),
        # 10 TCP recipe frames and 15 TCP witness frames.
        ("tcp", None, 25),
    ],
)
def test_real_tshark_names_unknown_fields_and_accepts_aliases(
    tmp_path: Path,
    display_filter: str,
    expected_code: str | None,
    expected_frames: int,
) -> None:
    capture = _model_split_capture(tmp_path)

    if expected_code is None:
        frames = TsharkRunner().run(capture, display_filter).frames
        assert len(frames) == expected_frames
        return

    with pytest.raises(RunnerError) as error:
        TsharkRunner().run(capture, display_filter)

    assert error.value.code == expected_code


def test_real_tshark_accepted_filter_never_classifies(tmp_path: Path) -> None:
    capture = _model_split_capture(tmp_path)

    result = TsharkRunner().run(capture, "tcp")

    assert result.frames == tuple(sorted(result.frames))
    # 10 TCP recipe frames and 15 TCP witness frames.
    assert len(result.frames) == 25
    assert (
        result.capture_sha256
        == hashlib.sha256(capture.read_bytes()).hexdigest()
    )
    narrowed = TsharkRunner().run(capture, "tcp && ip.ttl <= 1")
    assert set(narrowed.frames) <= set(result.frames)


@pytest.mark.parametrize("version", ["4.6.80", "4.6.7", "4.6.8-rc1", "garbage"])
def test_requires_exact_pinned_version(tmp_path: Path, version: str) -> None:
    executable = _fake_tshark(
        tmp_path, "raise AssertionError('must not run')", version=version
    )

    with pytest.raises(RunnerError) as error:
        TsharkRunner(executable).run(_capture(tmp_path), "tcp")

    assert error.value.code == "tshark_version_mismatch"


def test_version_check_is_bounded_and_cached(tmp_path: Path) -> None:
    count = tmp_path / "version-count"
    executable = _fake_tshark(
        tmp_path,
        "print('1')",
        version_body=f"""
        count = Path({str(count)!r})
        count.write_text(count.read_text() + 'v' if count.exists() else 'v')
        print('TShark (Wireshark) 4.6.8.')
        """,
    )
    runner = TsharkRunner(executable)

    assert runner.version() == "4.6.8"
    runner.run(_capture(tmp_path), "tcp")
    runner.run(_capture(tmp_path), "udp")
    assert count.read_text(encoding="utf-8") == "v"


def test_version_timeout_is_sanitized(tmp_path: Path) -> None:
    executable = _fake_tshark(tmp_path, "", version_body="time.sleep(30)")

    with pytest.raises(RunnerError) as error:
        TsharkRunner(executable, RunnerLimits(timeout_seconds=0.3)).version()

    assert error.value.code == "timeout"


@pytest.mark.parametrize(
    "display_filter", ["", "  ", "tcp\x00secret", "\ud800"]
)
def test_rejects_invalid_filters_before_starting_process(
    display_filter: str,
) -> None:
    with pytest.raises(RunnerError) as error:
        TsharkRunner("unavailable-tshark").run(Path("private"), display_filter)

    assert error.value.code == "filter_invalid"
    assert "private" not in str(error.value)


def test_filter_size_uses_encoded_bytes() -> None:
    with pytest.raises(RunnerError) as error:
        TsharkRunner(
            "unavailable-tshark", RunnerLimits(max_filter_bytes=3)
        ).run(Path("private"), "\u00e9\u00e9")

    assert error.value.code == "filter_too_large"


@pytest.mark.parametrize(
    "kind", ["missing", "directory", "symlink", "fifo", "large", "nul"]
)
def test_rejects_unsafe_capture_paths(tmp_path: Path, kind: str) -> None:
    capture = tmp_path / "untrusted.pcap"
    if kind == "directory":
        capture.mkdir()
    elif kind == "symlink":
        capture.symlink_to(_capture(tmp_path))
    elif kind == "fifo":
        os.mkfifo(capture)
    elif kind == "large":
        capture.write_bytes(b"x" * 129)
    elif kind == "nul":
        capture = tmp_path / "untrusted\x00.pcap"
    executable = _fake_tshark(tmp_path, "raise AssertionError('must not run')")

    with pytest.raises(RunnerError) as error:
        TsharkRunner(executable, RunnerLimits(max_capture_bytes=128)).run(
            capture, "tcp"
        )

    assert error.value.code == (
        "capture_too_large" if kind == "large" else "capture_invalid"
    )
    assert "untrusted" not in str(error.value)


def test_missing_executable_is_sanitized() -> None:
    with pytest.raises(RunnerError) as error:
        TsharkRunner("missing-private-tshark").version()

    assert error.value.code == "tshark_unavailable"
    assert "private" not in str(error.value)


@pytest.mark.parametrize("timeout", [0, -1, float("inf"), float("nan")])
def test_rejects_invalid_time_limits(timeout: float) -> None:
    with pytest.raises(ValueError):
        RunnerLimits(timeout_seconds=timeout)


@pytest.mark.parametrize(
    "name",
    [
        "max_capture_bytes",
        "max_filter_bytes",
        "max_stdout_bytes",
        "max_stderr_bytes",
        "max_frames",
    ],
)
def test_rejects_nonpositive_size_limits(name: str) -> None:
    with pytest.raises(ValueError):
        replace(RunnerLimits(), **{name: 0})
