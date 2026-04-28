import pytest

from core.config import Config
from utils.tool_safety import is_dangerous_command, is_path_outside_allowed_dirs


def test_shell_environment_info_describes_windows_cmd(monkeypatch):
    import tools.shell as shell_module

    monkeypatch.setattr(shell_module.sys, "platform", "win32")
    monkeypatch.setattr(shell_module.platform, "system", lambda: "Windows")

    info = shell_module.get_shell_environment_info()

    assert info["os_name"] == "Windows"
    assert info["platform"] == "win32"
    assert info["shell"] == "cmd.exe via cmd /D /S /C"
    assert info["path_style"] == "Windows drive-letter paths with backslashes"
    assert "Do not mix Bash, PowerShell, and cmd.exe syntax" in info["command_guidance"]


def test_shell_environment_info_describes_posix_shell(monkeypatch):
    import tools.shell as shell_module

    monkeypatch.setattr(shell_module.sys, "platform", "linux")
    monkeypatch.setattr(shell_module.platform, "system", lambda: "Linux")

    info = shell_module.get_shell_environment_info()

    assert info["os_name"] == "Linux"
    assert info["platform"] == "linux"
    assert info["shell"] == "default POSIX shell via asyncio.create_subprocess_shell"
    assert info["path_style"] == "POSIX paths with forward slashes"


def test_shell_environment_info_normalizes_macos_name_and_is_side_effect_free(
    monkeypatch,
):
    import tools.shell as shell_module

    def fail_if_subprocess_starts(*args, **kwargs):
        raise AssertionError("get_shell_environment_info should not start subprocesses")

    monkeypatch.setattr(shell_module.sys, "platform", "darwin")
    monkeypatch.setattr(shell_module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(shell_module.subprocess, "Popen", fail_if_subprocess_starts)
    monkeypatch.setattr(shell_module.subprocess, "call", fail_if_subprocess_starts)

    info = shell_module.get_shell_environment_info()

    assert info["os_name"] == "macOS"
    assert info["platform"] == "darwin"
    assert info["shell"] == "default POSIX shell via asyncio.create_subprocess_shell"


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


def test_dev_null_is_treated_as_safe_path():
    assert is_path_outside_allowed_dirs("/dev/null") is False

    is_dangerous, reason = is_dangerous_command("echo hi > /dev/null")
    assert not is_dangerous, f"Expected safe, but got dangerous: {reason}"

    is_dangerous, reason = is_dangerous_command("cat /dev/null")
    assert not is_dangerous, f"Expected safe, but got dangerous: {reason}"


def test_unified_path_guard_detects_inside_and_outside_workspace(tmp_path, monkeypatch):
    workspace_dir = tmp_path / "workspace"
    media_dir = workspace_dir / "media"
    workspace_dir.mkdir(parents=True)
    media_dir.mkdir(parents=True)

    monkeypatch.setattr(Config, "WORKSPACE_DIR", workspace_dir)
    monkeypatch.setattr(Config, "MEDIA_DIR", media_dir)

    assert is_path_outside_allowed_dirs("src/file.txt") is False
    assert is_path_outside_allowed_dirs("../secret.txt") is True


def test_safe_tmp_directory_root_is_treated_as_allowed_path():
    assert is_path_outside_allowed_dirs("/tmp") is False
    assert is_path_outside_allowed_dirs("/tmp/") is False
    assert is_path_outside_allowed_dirs("/private/tmp") is False


def test_safe_tmp_child_paths_use_robust_path_containment():
    assert is_path_outside_allowed_dirs("/tmp/nested/file.txt") is False
    assert is_path_outside_allowed_dirs("/private/tmp/nested/file.txt") is False
    assert is_path_outside_allowed_dirs(r"C:\tmp\nested\file.txt") is False


def test_env_temp_directories_are_treated_as_allowed_paths(tmp_path, monkeypatch):
    custom_tmp = tmp_path / "custom-temp"
    custom_tmp.mkdir(parents=True)

    monkeypatch.setenv("TEMP", str(custom_tmp))
    monkeypatch.setenv("TMP", str(custom_tmp))

    assert is_path_outside_allowed_dirs(str(custom_tmp)) is False
    assert is_path_outside_allowed_dirs(str(custom_tmp / "nested" / "file.txt")) is False


def test_safe_workspace_script_execution(tmp_path, monkeypatch):
    workspace_dir = tmp_path / "workspace"
    media_dir = workspace_dir / "media"
    scripts_dir = workspace_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    media_dir.mkdir(parents=True)
    (scripts_dir / "safe.py").write_text("print('hello')\n", encoding="utf-8")

    monkeypatch.setattr(Config, "WORKSPACE_DIR", workspace_dir)
    monkeypatch.setattr(Config, "MEDIA_DIR", media_dir)

    is_dangerous, reason = is_dangerous_command("python scripts/safe.py")
    assert not is_dangerous, f"Expected safe, but got dangerous: {reason}"


def test_workspace_script_with_unsafe_subprocess_requires_approval(tmp_path, monkeypatch):
    workspace_dir = tmp_path / "workspace"
    media_dir = workspace_dir / "media"
    scripts_dir = workspace_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    media_dir.mkdir(parents=True)
    (scripts_dir / "danger.py").write_text(
        "import subprocess\nsubprocess.run('echo nope', shell=True)\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(Config, "WORKSPACE_DIR", workspace_dir)
    monkeypatch.setattr(Config, "MEDIA_DIR", media_dir)

    is_dangerous, reason = is_dangerous_command("python scripts/danger.py")
    assert is_dangerous
    assert reason == "embedded_command_exec"


def test_safe_inline_python_execution():
    is_dangerous, reason = is_dangerous_command('python -c "print(123)"')
    assert not is_dangerous, f"Expected safe, but got dangerous: {reason}"


def test_inline_python_with_unsafe_subprocess_requires_approval():
    is_dangerous, reason = is_dangerous_command(
        'python -c "import subprocess; subprocess.run(\'echo hi\', shell=True)"'
    )
    assert is_dangerous
    assert reason == "embedded_command_exec"


if __name__ == "__main__":
    pytest.main([__file__])
