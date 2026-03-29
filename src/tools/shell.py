import asyncio
import locale
import os
import re as _re
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any

from core.config import Config
from utils.logger import get_logger

logger = get_logger()


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

# Compiled regex patterns for dangerous shell command detection
_DANGEROUS_PATTERNS: list[tuple[str, _re.Pattern]] = [
    # 1. Redirection/Pipe to system paths (Check this first to categorize redirections correctly)
    (
        "system_write",
        _re.compile(
            r"(?:[12]?>|>>|\|\s*tee\s+(?:-a\s+)?)\s*(?!/tmp/)(?:/etc/|/usr/|/bin/|/sbin/|/var/|/lib/|/boot/|/root/|C:\\Windows|C:\\Program Files)",
            _re.I,
        ),
    ),
    # 2. Deletion / destructive move
    ("data_loss", _re.compile(r"\b(rm|rmdir|del|rd)\b", _re.I)),
    ("file_move", _re.compile(r"\b(mv|move|ren|rename)\b", _re.I)),
    # 3. Low-level disk formatting / wiping
    (
        "disk_wipe",
        _re.compile(r"\b(mkfs|dd|shred|wipefs|format|diskpart|fdisk|parted)\b", _re.I),
    ),
    # 4. Fork bombs / mass process kill
    ("fork_bomb", _re.compile(r":\(\)\s*\{|%0\|%0|\bforkbomb\b", _re.I)),
    (
        "mass_kill",
        _re.compile(r"\b(killall|pkill|kill\s+-9\s+-1|taskkill\s+/f)\b", _re.I),
    ),
    # 5. Remote payload execution (curl|bash pattern)
    (
        "remote_exec",
        _re.compile(
            r"(curl|wget|fetch)\s+.*\|\s*(bash|sh|zsh|dash|python|perl|ruby|node)",
            _re.I,
        ),
    ),
    (
        "powershell_exec",
        _re.compile(r"Invoke-Expression|iex\s*\(|IEX\s*\(|DownloadString", _re.I),
    ),
    # 6. Reverse shells / tunnels
    (
        "reverse_shell",
        _re.compile(
            r"\b(nc|ncat|netcat|socat)\b.*(-e|exec)|/dev/tcp/|/dev/udp/", _re.I
        ),
    ),
    ("tunnel", _re.compile(r"\b(ngrok|chisel|frp|bore)\b", _re.I)),
    # 7. Sensitive system access
    ("sudo", _re.compile(r"\bsudo\b", _re.I)),
    ("crontab", _re.compile(r"\bcrontab\b", _re.I)),
    (
        "ssh_keys",
        _re.compile(r"\.ssh/(authorized_keys|id_rsa|id_ed25519|config)", _re.I),
    ),
    ("shadow", _re.compile(r"/etc/(shadow|passwd|sudoers)", _re.I)),
    # 8. Permission escalation
    ("chmod_777", _re.compile(r"\bchmod\s+(\+[rwxst]*\s+|)7[0-7]{2}\b", _re.I)),
    ("chattr", _re.compile(r"\bchattr\b", _re.I)),
    ("setuid", _re.compile(r"\bchmod\s+[ugo]*\+s\b", _re.I)),
    # 9. Base64-to-shell execution
    (
        "base64_exec",
        _re.compile(r"base64\s+(-d|--decode).*\|\s*(bash|sh|python|perl)", _re.I),
    ),
    (
        "echo_decode",
        _re.compile(r"echo\s+.*\|\s*base64\s+(-d|--decode).*\|\s*(bash|sh)", _re.I),
    ),
]

_URL_SCHEME_PATTERN = _re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_WINDOWS_DRIVE_PATTERN = _re.compile(r"^[a-zA-Z]:[\\/]")
_SAFE_TMP_PREFIXES = (
    "/tmp/",
    "/private/tmp/",
    "c:\\tmp\\",
)


def _normalize_shell_path(candidate: str) -> Path:
    """Normalize a shell path candidate against WORKSPACE_DIR."""
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = Path(Config.WORKSPACE_DIR) / path
    return path.resolve(strict=False)


def _is_path_in_allowed_dirs(path: Path) -> bool:
    """Return whether a path is inside workspace/media."""
    normalized_str = str(path).lower().replace("/", "\\")
    if normalized_str.startswith("\\tmp\\"):
        normalized_str = "/tmp/" + normalized_str[len("\\tmp\\") :]

    lower_path = str(path).lower()
    if lower_path.startswith(_SAFE_TMP_PREFIXES):
        return True

    allowed_dirs = [
        Path(Config.WORKSPACE_DIR).resolve(),
        Path(Config.MEDIA_DIR).resolve(),
    ]

    for allowed_dir in allowed_dirs:
        try:
            path.relative_to(allowed_dir)
            return True
        except ValueError:
            continue

    return False


def _looks_like_path_token(token: str) -> bool:
    """Heuristically determine whether a shell token looks like a path."""
    if not token:
        return False

    if _URL_SCHEME_PATTERN.match(token):
        return False

    if token.startswith(("~", "./", "../", ".\\", "..\\", "/", "\\")):
        return True

    if _WINDOWS_DRIVE_PATTERN.match(token):
        return True

    if "/" in token or "\\" in token:
        return True

    return False


def _extract_suspicious_path_tokens(cmd: str) -> list[str]:
    """Extract path-like shell tokens conservatively.

    This is intentionally heuristic rather than a full shell parser.
    """
    token_pattern = _re.compile(
        r'"([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\'|([^\s;|&<>]+)'
    )
    tokens: list[str] = []

    for match in token_pattern.finditer(cmd):
        token = next(group for group in match.groups() if group is not None)
        token = token.strip()
        if not token:
            continue
        if _looks_like_path_token(token):
            tokens.append(token)

    return tokens


def has_outside_workspace_path(cmd: str) -> tuple[bool, str]:
    """Check whether a shell command references an explicit path outside workspace/media."""
    for token in _extract_suspicious_path_tokens(cmd):
        try:
            normalized = _normalize_shell_path(token)
        except Exception:
            return True, token

        if not _is_path_in_allowed_dirs(normalized):
            return True, token

    return False, ""


def is_dangerous_command(cmd: str) -> tuple[bool, str]:
    """Check if a shell command matches known dangerous patterns.

    Returns:
        (is_dangerous, reason): If dangerous, reason describes the matched threat category.
    """
    for category, pattern in _DANGEROUS_PATTERNS:
        for match in pattern.finditer(cmd):
            # HITL logic refinement: Consider /tmp/ as a safe context.
            match_start = match.start()

            # Find the full "word" (path or command) containing this match
            prefix = cmd[:match_start]
            last_delim = _re.search(r"[ ;&|<>][^ ;&|<>]*$", prefix)
            word_start = last_delim.start() + 1 if last_delim else 0

            suffix = cmd[match_start:]
            next_delim = _re.search(r"[ ;&|<>]", suffix)
            word_end = match_start + (next_delim.start() if next_delim else len(suffix))

            full_word = cmd[word_start:word_end].lower()

            # If the current match is part of a /tmp/ path, and it's a file-based category, we consider it safe.
            if any(p in full_word for p in ("/tmp/", "c:\\tmp\\", "/private/tmp/")):
                if category not in (
                    "data_loss",
                    "file_move",
                    "disk_wipe",
                    "mass_kill",
                    "fork_bomb",
                    "sudo",
                ):
                    continue  # Skip this match, look for others or other categories

            # Special case for destructive commands: if they ONLY operate on /tmp/, skip
            if category in ("data_loss", "file_move"):
                # Find all absolute paths in the entire command
                paths = _re.findall(r'(?:/|[a-zA-Z]:\\)[^\s;&|<>"\']*', cmd)
                if paths:
                    non_tmp_paths = [
                        p
                        for p in paths
                        if not p.lower().startswith(
                            ("/tmp/", "c:\\tmp\\", "/private/tmp/")
                        )
                    ]
                    if not non_tmp_paths:
                        continue  # All absolute paths are in /tmp/, so this category doesn't trigger for this match
                else:
                    # No absolute paths found (e.g., 'rm relative_file').
                    # We keep the warning as we can't be sure it's safe without absolute context.
                    pass

            return True, category

    outside_workspace, _ = has_outside_workspace_path(cmd)
    if outside_workspace:
        return True, "outside_workspace_path"

    return False, ""


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
                    "description": "The maximum time (in seconds) allowed. Default is 60.",
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
        timeout: int = 60,
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

