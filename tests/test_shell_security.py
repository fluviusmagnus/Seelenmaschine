import sys
from pathlib import Path
import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from tools.shell import is_dangerous_command


def test_safe_tmp_deletion():
    # rm /tmp/file should be safe
    is_dangerous, reason = is_dangerous_command("rm /tmp/test.txt")
    assert not is_dangerous, f"Expected safe, but got dangerous: {reason}"

    is_dangerous, reason = is_dangerous_command("rm -rf /tmp/my_dir")
    assert not is_dangerous, f"Expected safe, but got dangerous: {reason}"

    is_dangerous, reason = is_dangerous_command("del C:\\tmp\\file.txt")
    assert not is_dangerous, f"Expected safe, but got dangerous: {reason}"


def test_dangerous_deletion():
    # rm /etc/passwd should be dangerous
    is_dangerous, reason = is_dangerous_command("rm /etc/passwd")
    assert is_dangerous
    assert reason == "data_loss"

    # Combined safe and dangerous should be dangerous
    is_dangerous, reason = is_dangerous_command("rm /tmp/foo /etc/shadow")
    assert is_dangerous
    assert reason == "data_loss"


def test_safe_tmp_redirection():
    # Redirection to /tmp should be safe
    is_dangerous, reason = is_dangerous_command("echo 'hello' > /tmp/out.txt")
    assert not is_dangerous, f"Expected safe, but got dangerous: {reason}"


def test_dangerous_redirection():
    # Redirection to system paths should be dangerous
    is_dangerous, reason = is_dangerous_command("echo 'hack' > /etc/passwd")
    assert is_dangerous
    assert reason == "system_write"

    is_dangerous, reason = is_dangerous_command("command >> /var/log/syslog")
    assert is_dangerous
    assert reason == "system_write"


def test_dangerous_pipe_tee():
    # Piping to tee targeting system paths should be dangerous
    is_dangerous, reason = is_dangerous_command("cat payload | tee /usr/bin/malware")
    assert is_dangerous
    assert reason == "system_write"

    is_dangerous, reason = is_dangerous_command("cat payload | tee -a /etc/shadow")
    assert is_dangerous
    assert reason == "system_write"


def test_tmp_prefixed_sensitive_file():
    # /tmp/etc/shadow should be safe
    is_dangerous, reason = is_dangerous_command("cat /tmp/etc/shadow")
    assert not is_dangerous, f"Expected safe, but got dangerous: {reason}"


def test_genuine_sensitive_file():
    # /etc/shadow should be dangerous
    is_dangerous, reason = is_dangerous_command("cat /etc/shadow")
    assert is_dangerous
    assert reason == "shadow"


def test_move_safe():
    is_dangerous, reason = is_dangerous_command("mv /tmp/a /tmp/b")
    assert not is_dangerous, f"Expected safe, but got dangerous: {reason}"


def test_move_dangerous():
    is_dangerous, reason = is_dangerous_command("mv /tmp/payload /usr/bin/ls")
    assert is_dangerous
    assert reason == "file_move"


def test_workspace_external_read_like_path_requires_approval():
    is_dangerous, reason = is_dangerous_command("cat ../secret.txt")
    assert is_dangerous
    assert reason == "outside_workspace_path"

    is_dangerous, reason = is_dangerous_command("ls ~")
    assert is_dangerous
    assert reason == "outside_workspace_path"


def test_workspace_internal_relative_path_stays_allowed():
    is_dangerous, reason = is_dangerous_command("cat src/file.txt")
    assert not is_dangerous, f"Expected safe, but got dangerous: {reason}"


def test_workspace_external_redirection_requires_approval():
    is_dangerous, reason = is_dangerous_command("echo hi > ../out.txt")
    assert is_dangerous
    assert reason == "outside_workspace_path"


if __name__ == "__main__":
    pytest.main([__file__])
