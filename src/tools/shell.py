import asyncio
import locale
import os
import platform
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from core.config import Config
from utils.logger import get_logger

logger = get_logger()


def get_shell_environment_info() -> Dict[str, str]:
    """Return the shell semantics used by ShellCommandTool."""
    os_name = platform.system() or "Unknown"
    if os_name == "Darwin":
        display_os_name = "macOS"
    else:
        display_os_name = os_name

    if sys.platform == "win32":
        shell = "cmd.exe via cmd /D /S /C"
        path_style = "Windows drive-letter paths with backslashes"
    else:
        shell = "default POSIX shell via asyncio.create_subprocess_shell"
        path_style = "POSIX paths with forward slashes"

    return {
        "os_name": display_os_name,
        "platform": sys.platform,
        "shell": shell,
        "path_style": path_style,
        "command_guidance": (
            "Generate commands for this shell and path style. Do not mix Bash, "
            "PowerShell, and cmd.exe syntax; prefer cross-platform Python when "
            "a command must work across operating systems."
        ),
    }


def smart_decode(data: bytes) -> str:
    if not isinstance(data, bytes):
        if data is None:
            return ""
        return str(data)
    try:
        decoded_str = data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            encoding = locale.getpreferredencoding(False) or "utf-8"
            decoded_str = data.decode(encoding, errors="replace")
        except Exception:
            decoded_str = data.decode("utf-8", errors="replace")
    except Exception as e:
        return f"[Decode Error Occurred: {e}]"
    return decoded_str.strip("\n")


def _kill_process_tree_win32(pid: int) -> None:
    try:
        subprocess.call(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except Exception:
        pass


def _sanitize_win_cmd(cmd: str) -> str:
    if '\\"' in cmd and '"' not in cmd.replace('\\"', ""):
        return cmd.replace('\\"', '"')
    return cmd


def _read_temp_file(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return smart_decode(f.read())
    except OSError:
        return ""


def _execute_subprocess_sync(
    cmd: str,
    cwd: str,
    timeout: int,
    env: Optional[Dict[str, str]] = None,
) -> tuple[int, str, str]:
    stdout_path: Optional[str] = None
    stderr_path: Optional[str] = None
    stdout_file = None
    stderr_file = None

    try:
        cmd = _sanitize_win_cmd(cmd)
        wrapped = f'cmd /D /S /C "chcp 65001 >nul & {cmd}"'

        stdout_fd, stdout_path = tempfile.mkstemp(prefix="seelen_out_")
        stderr_fd, stderr_path = tempfile.mkstemp(prefix="seelen_err_")
        stdout_file = os.fdopen(stdout_fd, "wb")
        stderr_file = os.fdopen(stderr_fd, "wb")

        proc = subprocess.Popen(
            wrapped,
            shell=False,
            stdout=stdout_file,
            stderr=stderr_file,
            text=False,
            cwd=cwd,
            env=env,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )

        stdout_file.close()
        stdout_file = None
        stderr_file.close()
        stderr_file = None

        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_process_tree_win32(proc.pid)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                except OSError:
                    pass

        stdout_str = _read_temp_file(stdout_path)
        stderr_str = _read_temp_file(stderr_path)

        if timed_out:
            timeout_msg = (
                f"Command execution exceeded the timeout of {timeout} seconds."
            )
            if stderr_str:
                stderr_str = f"{stderr_str}\n{timeout_msg}"
            else:
                stderr_str = timeout_msg
            return -1, stdout_str, stderr_str

        returncode = proc.returncode if proc.returncode is not None else -1
        return returncode, stdout_str, stderr_str

    except Exception as e:
        return -1, "", str(e)
    finally:
        for f in (stdout_file, stderr_file):
            if f is not None:
                try:
                    f.close()
                except OSError:
                    pass
        for path in (stdout_path, stderr_path):
            if path is not None:
                try:
                    os.unlink(path)
                except OSError:
                    pass


class ShellCommandTool:
    """Tool for LLM to execute shell commands."""

    @property
    def name(self) -> str:
        return "execute_shell_command"

    @property
    def description(self) -> str:
        return "Execute shell commands and return the return code, standard output and error. Default working directory is WORKSPACE_DIR."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "The maximum time (in seconds) allowed. Default is 90.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory. Defaults to WORKSPACE_DIR if omitted.",
                },
            },
            "required": ["command"],
        }

    async def execute(
        self,
        command: str,
        timeout: int = 90,
        cwd: Optional[str] = None,
    ) -> str:
        cmd = (command or "").strip()

        if cwd is not None:
            working_dir = Path(cwd)
            if not working_dir.is_absolute():
                working_dir = Config.WORKSPACE_DIR / working_dir
        else:
            working_dir = Config.WORKSPACE_DIR

        # create working dir if it doesn't exist
        try:
            working_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"  # Enforce Python subprocesses to use UTF-8

        python_bin_dir = str(Path(sys.executable).parent)
        existing_path = env.get("PATH", "")
        if existing_path:
            env["PATH"] = python_bin_dir + os.pathsep + existing_path
        else:
            env["PATH"] = python_bin_dir

        try:
            if sys.platform == "win32":
                returncode, stdout_str, stderr_str = await asyncio.to_thread(
                    _execute_subprocess_sync,
                    cmd,
                    str(working_dir),
                    timeout,
                    env,
                )
            else:
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    bufsize=0,
                    cwd=str(working_dir),
                    env=env,
                    start_new_session=True,
                )

                try:
                    stdout, stderr = await asyncio.wait_for(
                        proc.communicate(),
                        timeout=timeout,
                    )
                    stdout_str = smart_decode(stdout)
                    stderr_str = smart_decode(stderr)
                    returncode = proc.returncode

                except asyncio.TimeoutError:
                    stderr_suffix = (
                        f"⚠️ TimeoutError: The command execution exceeded "
                        f"the timeout of {timeout} seconds."
                    )
                    returncode = -1
                    try:
                        pgid = os.getpgid(proc.pid)
                        os.killpg(pgid, signal.SIGTERM)
                        try:
                            await asyncio.wait_for(proc.wait(), timeout=2)
                        except asyncio.TimeoutError:
                            os.killpg(pgid, signal.SIGKILL)
                            await asyncio.wait_for(proc.wait(), timeout=2)

                        try:
                            stdout, stderr = await asyncio.wait_for(
                                proc.communicate(),
                                timeout=1,
                            )
                        except asyncio.TimeoutError:
                            stdout, stderr = b"", b""
                        stdout_str = smart_decode(stdout)
                        stderr_str = smart_decode(stderr)
                        if stderr_str:
                            stderr_str += f"\n{stderr_suffix}"
                        else:
                            stderr_str = stderr_suffix
                    except (ProcessLookupError, OSError):
                        try:
                            proc.kill()
                            await proc.wait()
                        except (ProcessLookupError, OSError):
                            pass
                        stdout_str = ""
                        stderr_str = stderr_suffix

            # Truncation helper to prevent LLM context explosion
            def truncate_output(
                output: str, max_len: int = Config.SHELL_OUTPUT_MAX_CHARS
            ) -> str:
                if len(output) <= max_len:
                    return output
                head = output[: Config.SHELL_OUTPUT_HEAD_CHARS].rstrip()
                tail = output[-Config.SHELL_OUTPUT_TAIL_CHARS :].lstrip()
                omitted = len(output) - (
                    Config.SHELL_OUTPUT_HEAD_CHARS + Config.SHELL_OUTPUT_TAIL_CHARS
                )
                if omitted > 0:
                    return f"{head}\n\n...[truncated {omitted} chars]...\n\n{tail}"
                return output

            stdout_str = truncate_output(stdout_str)
            stderr_str = truncate_output(stderr_str)

            if returncode == 0:
                if stdout_str:
                    response_text = stdout_str
                else:
                    response_text = "Command executed successfully (no output)."
                if stderr_str:
                    response_text += f"\n[stderr]\n{stderr_str}"
            else:
                response_parts = [f"Command failed with exit code {returncode}."]
                if stdout_str:
                    response_parts.append(f"\n[stdout]\n{stdout_str}")
                if stderr_str:
                    response_parts.append(f"\n[stderr]\n{stderr_str}")
                response_text = "".join(response_parts)

            return response_text

        except Exception as e:
            return f"Error: Shell command execution failed due to \n{e}"
