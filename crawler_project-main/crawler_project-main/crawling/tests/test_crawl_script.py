"""Exercise the actual crawl wrapper with a local wget substitute; no network."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "crawl_script_batched.sh"
URLS = [f"https://example.test/page-{index}" for index in range(1, 4)]


@pytest.fixture(scope="module")
def bash() -> str:
    # Prefer Git Bash over a possible WSL launcher on Windows.
    git_bash = Path("C:/Program Files/Git/bin/bash.exe")
    executable = str(git_bash) if git_bash.is_file() else shutil.which("bash")
    if not executable:
        pytest.skip("Bash is required to exercise the crawl wrapper")
    return executable


def run_crawl(tmp_path: Path, bash: str, mode: str, codes: list[int]):
    workspace = tmp_path.resolve()
    script = workspace / SCRIPT.name
    output = workspace / "crawl_out" / "test-run"
    # The copied script derives all cleanup paths from its own directory. Keep
    # its WARC temp directory as well, so it never runs a recursive shell delete.
    assert script.is_relative_to(workspace)
    assert output.resolve().is_relative_to(workspace)
    script.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    mock_bin = workspace / "bin"
    mock_bin.mkdir()
    mock_wget = mock_bin / "wget"
    mock_wget.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'count=0; [[ ! -f wget_calls ]] || read -r count < wget_calls\n'
        'count=$((count + 1)); printf "%s\\n" "$count" > wget_calls\n'
        'IFS=, read -r -a codes <<< "$MOCK_WGET_EXIT_CODES"\n'
        'exit "${codes[$((count - 1))]:-${codes[0]}}"\n',
        encoding="utf-8",
        newline="\n",
    )
    mock_wget.chmod(0o755)
    target = URLS[0]
    if mode != "url":
        (workspace / "seeds.txt").write_text("\n".join(URLS) + "\n", encoding="utf-8")
        target = "seeds.txt"

    env = os.environ.copy()
    for key in (
        "BASH_ENV", "ENV", "LOGFILE", "REJECTED_LOG", "FAILED_URLS",
        "WARC_TEMPDIR", "DEPTH", "WAIT_SECS", "RANDOM_WAIT", "TIMEOUT_SECS",
        "TRIES", "MAX_REDIRECT", "QUOTA", "ROBOTS", "UA", "REJECT_REGEX",
        "DELETE_AFTER", "WARC_MAX_SIZE",
    ):
        env.pop(key, None)
    env.update(
        KEEP_TEMPDIR="1",
        DRY_RUN="0",
        BATCH_SIZE="1" if mode == "batch" else "100",
        BATCH_PAUSE="0",
        MOCK_WGET_EXIT_CODES=",".join(str(code) for code in codes),
    )
    result = subprocess.run(
        [
            bash, "-c",
            'export PATH="$PWD/bin:$PATH"; hash -r; '
            '[[ "$(command -v wget)" == "$PWD/bin/wget" ]] || exit 99; '
            'exec bash ./crawl_script_batched.sh "$@"',
            "test-crawl", target, "test-run",
        ],
        cwd=workspace,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    failed_path = output / "logs" / "test-run.failed_urls.txt"
    assert failed_path.is_file(), result.stdout + result.stderr
    failed = failed_path.read_text(encoding="utf-8").splitlines()
    calls = int((workspace / "wget_calls").read_text(encoding="utf-8"))
    return result, failed, calls


@pytest.mark.parametrize("mode", ["url", "file", "batch"])
@pytest.mark.parametrize("wget_code", [0, 4, 8, 5])
def test_wget_status_controls_exit_summary_and_retry_inputs(tmp_path, bash, mode, wget_code):
    result, failed, calls = run_crawl(tmp_path, bash, mode, [wget_code])
    expected_calls = 3 if mode == "batch" else 1
    expected_failures = expected_calls if wget_code else 0
    assert result.returncode == (3 if wget_code else 0), result.stdout + result.stderr
    assert calls == expected_calls
    assert f"Failures      : {expected_failures}" in result.stdout
    assert failed == ((URLS[:1] if mode == "url" else URLS) if wget_code else [])


def test_batches_continue_and_only_failed_batches_are_saved(tmp_path, bash):
    result, failed, calls = run_crawl(tmp_path, bash, "batch", [4, 0, 8])
    assert result.returncode == 3, result.stdout + result.stderr
    assert calls == 3
    assert "Failures      : 2" in result.stdout
    assert failed == [URLS[0], URLS[2]]
