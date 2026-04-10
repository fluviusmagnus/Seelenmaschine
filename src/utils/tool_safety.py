import os
import re as _re
import shlex
import tempfile
from pathlib import Path
from typing import Optional

from core.config import Config

_DANGEROUS_PATTERNS: list[tuple[str, _re.Pattern]] = [
    (
        "system_write",
        _re.compile(
            r"(?:[12]?>|>>|\|\s*tee\s+(?:-a\s+)?)\s*(?!/tmp/)(?:/etc/|/usr/|/bin/|/sbin/|/var/|/lib/|/boot/|/root/|C:\\Windows|C:\\Program Files)",
            _re.I,
        ),
    ),
    ("data_loss", _re.compile(r"\b(rm|rmdir|del|rd)\b", _re.I)),
    ("file_move", _re.compile(r"\b(mv|move|ren|rename)\b", _re.I)),
    ("disk_wipe", _re.compile(r"\b(mkfs|dd|shred|wipefs|format|diskpart|fdisk|parted)\b", _re.I)),
    ("fork_bomb", _re.compile(r":\(\)\s*\{|%0\|%0|\bforkbomb\b", _re.I)),
    ("mass_kill", _re.compile(r"\b(killall|pkill|kill\s+-9\s+-1|taskkill\s+/f)\b", _re.I)),
    (
        "remote_exec",
        _re.compile(r"(curl|wget|fetch)\s+.*\|\s*(bash|sh|zsh|dash|python|perl|ruby|node)", _re.I),
    ),
    ("powershell_exec", _re.compile(r"Invoke-Expression|iex\s*\(|IEX\s*\(|DownloadString", _re.I)),
    ("reverse_shell", _re.compile(r"\b(nc|ncat|netcat|socat)\b.*(-e|exec)|/dev/tcp/|/dev/udp/", _re.I)),
    ("tunnel", _re.compile(r"\b(ngrok|chisel|frp|bore)\b", _re.I)),
    ("sudo", _re.compile(r"\bsudo\b", _re.I)),
    ("crontab", _re.compile(r"\bcrontab\b", _re.I)),
    ("ssh_keys", _re.compile(r"\.ssh/(authorized_keys|id_rsa|id_ed25519|config)", _re.I)),
    ("shadow", _re.compile(r"/etc/(shadow|passwd|sudoers)", _re.I)),
    ("chmod_777", _re.compile(r"\bchmod\s+(\+[rwxst]*\s+|)7[0-7]{2}\b", _re.I)),
    ("chattr", _re.compile(r"\bchattr\b", _re.I)),
    ("setuid", _re.compile(r"\bchmod\s+[ugo]*\+s\b", _re.I)),
    ("base64_exec", _re.compile(r"base64\s+(-d|--decode).*\|\s*(bash|sh|python|perl)", _re.I)),
    ("echo_decode", _re.compile(r"echo\s+.*\|\s*base64\s+(-d|--decode).*\|\s*(bash|sh)", _re.I)),
]

_URL_SCHEME_PATTERN = _re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*://")
_WINDOWS_DRIVE_PATTERN = _re.compile(r"^[a-zA-Z]:[\\/]")
_STATIC_SAFE_TMP_DIRS = (Path("/tmp"), Path("/private/tmp"), Path("c:/tmp"))
_SAFE_SPECIAL_PATHS = {"/dev/null"}
_DIRECT_SAFE_COMMANDS = {"pwd", "ls", "dir", "echo", "cat", "type", "rg", "grep", "find"}
_SCRIPT_INTERPRETERS = {"python", "python3", "bash", "sh", "node"}
_INLINE_CODE_INTERPRETERS = {
    "python": "-c",
    "python3": "-c",
    "node": "-e",
    "powershell": "-command",
    "pwsh": "-command",
}
_EMBEDDED_CODE_DANGEROUS_PATTERNS: list[tuple[str, _re.Pattern]] = [
    (
        "embedded_command_exec",
        _re.compile(
            r"\b(subprocess\.(run|Popen|call|check_call|check_output)|os\.system|pty\.spawn|Runtime\.getRuntime\(\)\.exec|child_process\.(exec|execSync|spawn|spawnSync)|ProcessBuilder\(|Start-Process)\b",
            _re.I,
        ),
    ),
    ("embedded_dynamic_exec", _re.compile(r"\b(eval|exec)\s*\(", _re.I)),
    ("embedded_encoded_command", _re.compile(r"-EncodedCommand\b|fromBase64String\(|base64\s+(-d|--decode)", _re.I)),
]


def resolve_workspace_path(candidate: str, *, base_dir: Optional[Path] = None) -> Path:
    path = Path(candidate).expanduser()
    if not path.is_absolute():
        path = (base_dir or Path(Config.WORKSPACE_DIR)) / path
    return path.resolve(strict=False)


def _normalize_for_path_compare(path: Path) -> Path:
    """Normalize a path for robust containment checks across platforms."""
    return Path(str(path).replace("\\", "/")).expanduser()


def _normalize_path_string(value: str) -> str:
    """Normalize a path-like string for prefix/containment comparisons."""
    return value.strip().replace("\\", "/").lower().rstrip("/")


def _is_explicit_absolute_path(value: str) -> bool:
    """Return whether the raw user-provided path is explicitly absolute."""
    stripped = value.strip()
    if not stripped:
        return False
    normalized = stripped.replace("\\", "/")
    if normalized.startswith("/"):
        return True
    return bool(_WINDOWS_DRIVE_PATTERN.match(stripped))


def _get_safe_tmp_dirs() -> tuple[Path, ...]:
    """Return built-in cross-platform temporary directories."""
    candidates = {path for path in _STATIC_SAFE_TMP_DIRS}

    env_candidates = [
        os.environ.get("TMP"),
        os.environ.get("TEMP"),
        tempfile.gettempdir(),
    ]
    for candidate in env_candidates:
        if not candidate:
            continue
        try:
            candidates.add(Path(candidate).expanduser().resolve(strict=False))
        except Exception:
            continue

    return tuple(sorted(candidates, key=lambda item: _normalize_path_string(str(item))))


def _is_same_or_child_path(path: Path, parent: Path) -> bool:
    """Return whether path is the same as parent or contained by it."""
    normalized_path = _normalize_for_path_compare(path)
    normalized_parent = _normalize_for_path_compare(parent)
    try:
        normalized_path.relative_to(normalized_parent)
        return True
    except ValueError:
        return False


def _is_path_in_allowed_dirs(path: Path, *, allow_temp_dirs: bool) -> bool:
    if allow_temp_dirs and any(
        _is_same_or_child_path(path, safe_tmp_dir) for safe_tmp_dir in _get_safe_tmp_dirs()
    ):
        return True

    for allowed_dir in (Path(Config.WORKSPACE_DIR).resolve(), Path(Config.MEDIA_DIR).resolve()):
        if _is_same_or_child_path(path, allowed_dir):
            return True
    return False


def is_path_outside_allowed_dirs(target_path: str, *, base_dir: Optional[Path] = None) -> bool:
    if not target_path:
        return False
    normalized_target = _normalize_path_string(target_path)
    allow_temp_dirs = _is_explicit_absolute_path(target_path)
    if normalized_target in _SAFE_SPECIAL_PATHS:
        return False
    if allow_temp_dirs:
        safe_tmp_prefixes = tuple(_normalize_path_string(str(path)) for path in _get_safe_tmp_dirs())
        if normalized_target in safe_tmp_prefixes:
            return False
        if any(normalized_target.startswith(f"{prefix}/") for prefix in safe_tmp_prefixes):
            return False
    try:
        resolved = resolve_workspace_path(target_path, base_dir=base_dir)
    except Exception:
        return True
    return not _is_path_in_allowed_dirs(resolved, allow_temp_dirs=allow_temp_dirs)


def _looks_like_path_token(token: str) -> bool:
    if not token:
        return False
    if _URL_SCHEME_PATTERN.match(token):
        return False
    if token.startswith(("~", "./", "../", ".\\", "..\\", "/", "\\")):
        return True
    if _WINDOWS_DRIVE_PATTERN.match(token):
        return True
    return "/" in token or "\\" in token


def _extract_suspicious_path_tokens(cmd: str) -> list[str]:
    token_pattern = _re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"|\'([^\'\\]*(?:\\.[^\'\\]*)*)\'|([^\s;|&<>]+)')
    tokens: list[str] = []
    for match in token_pattern.finditer(cmd):
        token = next(group for group in match.groups() if group is not None).strip()
        if token and _looks_like_path_token(token):
            tokens.append(token)
    return tokens


def has_outside_workspace_path(cmd: str) -> tuple[bool, str]:
    for token in _extract_suspicious_path_tokens(cmd):
        if is_path_outside_allowed_dirs(token):
            return True, token
    return False, ""


def _split_command_tokens(cmd: str) -> list[str]:
    try:
        return shlex.split(cmd, posix=True)
    except ValueError:
        try:
            return shlex.split(cmd, posix=False)
        except ValueError:
            return _extract_suspicious_path_tokens(cmd) or cmd.split()


def _strip_wrapping_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _is_git_safe(tokens: list[str]) -> bool:
    return bool(tokens and tokens[0].lower() == "git" and len(tokens) >= 2 and tokens[1].lower() in {"status", "diff", "log", "rev-parse", "show", "branch"})


def _is_python_module_safe(tokens: list[str]) -> bool:
    if len(tokens) < 3 or tokens[0].lower() not in {"python", "python3"} or tokens[1].lower() != "-m":
        return False
    module_name = tokens[2].lower()
    if module_name == "pytest":
        return all(not _looks_like_path_token(_strip_wrapping_quotes(token)) or not is_path_outside_allowed_dirs(_strip_wrapping_quotes(token)) for token in tokens[3:])
    if module_name == "ruff":
        subcommands = {token.lower() for token in tokens[3:] if not token.startswith("-")}
        if subcommands and not subcommands.issubset({"check", "format"}):
            return False
        return all(not _looks_like_path_token(_strip_wrapping_quotes(token)) or not is_path_outside_allowed_dirs(_strip_wrapping_quotes(token)) for token in tokens[3:])
    return False


def _match_dangerous_pattern(cmd: str) -> str:
    for category, pattern in _DANGEROUS_PATTERNS:
        for match in pattern.finditer(cmd):
            match_start = match.start()
            prefix = cmd[:match_start]
            last_delim = _re.search(r"[ ;&|<>][^ ;&|<>]*$", prefix)
            word_start = last_delim.start() + 1 if last_delim else 0
            suffix = cmd[match_start:]
            next_delim = _re.search(r"[ ;&|<>]", suffix)
            word_end = match_start + (next_delim.start() if next_delim else len(suffix))
            full_word = cmd[word_start:word_end].lower()
            if any(p in full_word for p in ("/tmp/", "c:\\tmp\\", "/private/tmp/")):
                if category not in ("data_loss", "file_move", "disk_wipe", "mass_kill", "fork_bomb", "sudo"):
                    continue
            if category in ("data_loss", "file_move"):
                paths = _re.findall(r'(?:/|[a-zA-Z]:\\)[^\s;&|<>"\']*', cmd)
                if paths and not [p for p in paths if not p.lower().startswith(("/tmp/", "c:\\tmp\\", "/private/tmp/"))]:
                    continue
            return category
    return ""


def _is_direct_safe_command(cmd: str, tokens: list[str]) -> tuple[bool, str]:
    if not tokens:
        return True, ""
    category = _match_dangerous_pattern(cmd)
    if category:
        return False, category
    outside_workspace, _ = has_outside_workspace_path(cmd)
    if outside_workspace:
        return False, "outside_workspace_path"
    return True, ""


def _detect_embedded_payload(cmd: str) -> tuple[str, Optional[str], Optional[str]]:
    tokens = _split_command_tokens(cmd)
    if not tokens:
        return "none", None, None
    executable = Path(_strip_wrapping_quotes(tokens[0])).name.lower()
    if executable in _INLINE_CODE_INTERPRETERS:
        flag = _INLINE_CODE_INTERPRETERS[executable]
        for index, token in enumerate(tokens[1:], start=1):
            if token.lower() == flag and index + 1 < len(tokens):
                return "inline", executable, _strip_wrapping_quotes(tokens[index + 1])
    if executable in _SCRIPT_INTERPRETERS:
        skip_next = False
        for token in tokens[1:]:
            if skip_next:
                skip_next = False
                continue
            lowered = token.lower()
            if lowered in {"-m", "-c", "-e", "-command"}:
                skip_next = True
                continue
            if token.startswith("-"):
                continue
            candidate = _strip_wrapping_quotes(token)
            if _looks_like_path_token(candidate) or Path(candidate).suffix:
                return "script", executable, candidate
            break
    return "none", None, None


def _embedded_code_is_dangerous(code: str, *, base_dir: Optional[Path] = None) -> tuple[bool, str]:
    if not code:
        return False, ""
    for category, pattern in _EMBEDDED_CODE_DANGEROUS_PATTERNS:
        if pattern.search(code):
            return True, category
    for token in _extract_suspicious_path_tokens(code):
        if is_path_outside_allowed_dirs(token, base_dir=base_dir):
            return True, "outside_workspace_path"
    for category, pattern in _DANGEROUS_PATTERNS:
        if pattern.search(code):
            return True, category
    return False, ""


def _script_payload_is_safe(script_path: str) -> tuple[bool, str]:
    if is_path_outside_allowed_dirs(script_path):
        return False, "outside_workspace_path"
    resolved = resolve_workspace_path(script_path)
    if not resolved.exists() or not resolved.is_file():
        return False, "script_not_found"
    try:
        content = resolved.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False, "script_not_readable"
    dangerous, reason = _embedded_code_is_dangerous(content, base_dir=resolved.parent)
    return (False, reason) if dangerous else (True, "")


def _inline_payload_is_safe(code: str) -> tuple[bool, str]:
    dangerous, reason = _embedded_code_is_dangerous(code)
    return (False, reason) if dangerous else (True, "")


def _is_explicitly_safe_command(cmd: str) -> tuple[bool, str]:
    tokens = _split_command_tokens(cmd)
    if not tokens:
        return True, ""
    executable = Path(_strip_wrapping_quotes(tokens[0])).name.lower()
    if executable in _DIRECT_SAFE_COMMANDS:
        return _is_direct_safe_command(cmd, tokens)
    if _is_git_safe(tokens) or _is_python_module_safe(tokens):
        return True, ""
    payload_type, _interpreter, payload = _detect_embedded_payload(cmd)
    if payload_type == "script" and payload:
        return _script_payload_is_safe(payload)
    if payload_type == "inline" and payload is not None:
        return _inline_payload_is_safe(payload)
    return False, ""


def is_dangerous_command(cmd: str) -> tuple[bool, str]:
    safe, safe_reason = _is_explicitly_safe_command(cmd)
    if safe:
        return False, safe_reason
    if safe_reason:
        return True, safe_reason
    category = _match_dangerous_pattern(cmd)
    if category:
        return True, category
    outside_workspace, _ = has_outside_workspace_path(cmd)
    if outside_workspace:
        return True, "outside_workspace_path"
    return False, ""