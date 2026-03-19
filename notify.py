import hashlib
import html
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
from contextlib import contextmanager
from ctypes import POINTER, byref, create_unicode_buffer, sizeof, windll
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path

try:
    import winsound
except Exception:
    winsound = None


PROJECT_ROOT = Path(__file__).resolve().parent
SETTINGS_PATH = PROJECT_ROOT / "settings.json"

DEFAULT_SETTINGS = {
    "title": "Codex svar klart",
    "default_body": "Agentens svar är klart.",
    "sound_path": r"C:\Windows\Media\Speech Sleep.wav",
    "enable_sound": True,
    "sound_mode": "wav_primary_then_fallback",
    "sound_sync": True,
    "enable_toast": True,
    "suppress_visual_when_codex_focused": True,
    "suppress_sound_when_codex_focused": True,
    "suppress_visual_process_names": ["Codex.exe"],
    "visual_mode": "mshta_popup",
    "fallback_mode": "message_beep",
    "debounce_seconds": 4.0,
    "debounce_mode": "signature",
    "log_path": "logs/notify_events.jsonl",
    "log_max_bytes": 262144,
    "log_backups": 3,
    "state_path": "state/notify_state.json",
    "visual_state_path": "state/visual_popup_state.json",
    "popup_timeout_seconds": 2,
    "popup_script_path": "notify_popup.hta",
    "single_active_popup": True,
    "replace_existing_popup": True,
    "visual_mutex_name": "Local\\KRSCodexVisualPopupMutex",
    "toast_app_id": "Windows PowerShell",
    "toast_host_preference": [
        r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        r"C:\Program Files\PowerShell\7\pwsh.exe",
        "powershell.exe",
        "pwsh.exe",
    ],
    "max_message_chars": 140,
}

KNOWN_COMPLETION_EVENTS = {
    "turn.completed",
    "task_complete",
    "agent_turn_complete",
    "agent-turn-complete",
}

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
SYNCHRONIZE = 0x00100000
WAIT_OBJECT_0 = 0x00000000
WAIT_ABANDONED = 0x00000080

_user32 = windll.user32
_kernel32 = windll.kernel32

_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
_user32.GetWindowTextLengthW.restype = wintypes.INT
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, wintypes.INT]
_user32.GetWindowTextW.restype = wintypes.INT
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.ReleaseMutex.argtypes = [wintypes.HANDLE]
_kernel32.ReleaseMutex.restype = wintypes.BOOL
_kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
_kernel32.TerminateProcess.restype = wintypes.BOOL
_kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    POINTER(wintypes.DWORD),
]
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _resolve_project_path(value):
    path = Path(str(value))
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def _ensure_parent(path):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass


def _append_log(settings, entry):
    log_path = Path(settings["log_path"])
    _ensure_parent(log_path)
    _rotate_logs(settings, log_path)

    record = {"timestamp": _utc_now()}
    record.update(entry)

    try:
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def _rotate_logs(settings, log_path):
    try:
        max_bytes = int(settings.get("log_max_bytes", 0) or 0)
    except Exception:
        max_bytes = 0

    try:
        backups = int(settings.get("log_backups", 0) or 0)
    except Exception:
        backups = 0

    if max_bytes <= 0 or backups <= 0:
        return

    try:
        if not log_path.is_file() or log_path.stat().st_size < max_bytes:
            return
    except Exception:
        return

    try:
        oldest = log_path.with_name(f"{log_path.name}.{backups}")
        if oldest.exists():
            oldest.unlink()
    except Exception:
        pass

    for index in range(backups - 1, 0, -1):
        source = log_path.with_name(f"{log_path.name}.{index}")
        target = log_path.with_name(f"{log_path.name}.{index + 1}")
        try:
            if source.exists():
                source.replace(target)
        except Exception:
            pass

    try:
        log_path.replace(log_path.with_name(f"{log_path.name}.1"))
    except Exception:
        pass


def _load_settings():
    settings = dict(DEFAULT_SETTINGS)
    settings_errors = []

    try:
        if SETTINGS_PATH.is_file():
            loaded = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                settings.update(loaded)
            else:
                settings_errors.append("settings_file_not_object")
    except Exception as exc:
        settings_errors.append(f"settings_load_failed:{type(exc).__name__}:{exc}")

    settings["sound_path"] = str(_resolve_project_path(settings["sound_path"]))
    settings["log_path"] = str(_resolve_project_path(settings["log_path"]))
    settings["state_path"] = str(_resolve_project_path(settings["state_path"]))
    settings["visual_state_path"] = str(_resolve_project_path(settings["visual_state_path"]))
    settings["popup_script_path"] = str(_resolve_project_path(settings["popup_script_path"]))

    return settings, settings_errors


def _load_state(settings):
    path = Path(settings["state_path"])
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_state(settings, state):
    path = Path(settings["state_path"])
    _ensure_parent(path)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        temp_path.write_text(json.dumps(state, ensure_ascii=True, indent=2), encoding="utf-8")
        temp_path.replace(path)
    except Exception:
        pass


def _load_json_file(path):
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def _save_json_file(path, state):
    _ensure_parent(path)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(path)
    except Exception:
        pass


def _load_visual_state(settings):
    return _load_json_file(Path(settings["visual_state_path"]))


def _save_visual_state(settings, state):
    _save_json_file(Path(settings["visual_state_path"]), state)


@contextmanager
def _visual_mutex(settings):
    name = str(settings.get("visual_mutex_name") or DEFAULT_SETTINGS["visual_mutex_name"])
    handle = _kernel32.CreateMutexW(None, False, name)
    acquired = False
    try:
        if handle:
            result = _kernel32.WaitForSingleObject(handle, 2000)
            acquired = result in (WAIT_OBJECT_0, WAIT_ABANDONED)
        yield acquired
    finally:
        if handle:
            if acquired:
                _kernel32.ReleaseMutex(handle)
            _kernel32.CloseHandle(handle)


def _terminate_process(pid):
    try:
        pid_value = int(pid or 0)
    except Exception:
        pid_value = 0

    if pid_value <= 0:
        return False

    handle = _kernel32.OpenProcess(PROCESS_TERMINATE | SYNCHRONIZE, False, pid_value)
    if not handle:
        return False

    try:
        return bool(_kernel32.TerminateProcess(handle, 0))
    except Exception:
        return False
    finally:
        _kernel32.CloseHandle(handle)


def _replace_existing_popup(settings):
    if not settings.get("single_active_popup", True):
        return "single_popup_disabled"

    if not settings.get("replace_existing_popup", True):
        return "replace_disabled"

    state = _load_visual_state(settings)
    pid = state.get("popup_pid")
    if not pid:
        return "no_existing_popup"

    if _terminate_process(pid):
        _save_visual_state(settings, {})
        return "replaced_existing_popup"

    _save_visual_state(settings, {})
    return "existing_popup_not_running"


def _remember_popup_process(settings, pid, kind):
    if not settings.get("single_active_popup", True):
        return

    _save_visual_state(
        settings,
        {
            "popup_pid": int(pid),
            "popup_kind": str(kind),
            "updated_at": _utc_now(),
        },
    )


def _normalize_payload(value, depth=0):
    if depth > 2:
        return {}

    if value is None:
        return {}

    if isinstance(value, (bytes, bytearray)):
        try:
            value = value.decode("utf-8", errors="ignore")
        except Exception:
            return {}

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return {}
        try:
            decoded = json.loads(text)
        except Exception:
            return {"message": text, "raw_text": text}
        return _normalize_payload(decoded, depth + 1)

    if isinstance(value, dict):
        return value

    if isinstance(value, list):
        return {"items": value}

    return {"value": str(value)}


def _read_payload(argv):
    raw = b""
    self_test = "--self-test" in argv[1:]

    try:
        if not self_test and not sys.stdin.isatty():
            raw = sys.stdin.buffer.read()
    except Exception:
        raw = b""

    if not raw:
        for arg in argv[1:]:
            if arg == "--self-test":
                continue
            try:
                raw = arg.encode("utf-8", errors="ignore")
            except Exception:
                raw = b""
            break

    if self_test:
        return {
            "event": "self_test",
            "message": "Självtest: ljud, popup och logg triggas.",
        }, True

    if not raw:
        return {}, False

    return _normalize_payload(raw), False


def _coerce_text(value):
    if isinstance(value, str):
        text = " ".join(value.split())
        if text:
            return text

    if isinstance(value, list):
        for item in value:
            text = _coerce_text(item)
            if text:
                return text

    if isinstance(value, dict):
        for key in ("text", "message", "summary", "content", "raw_text", "value"):
            if key in value:
                text = _coerce_text(value[key])
                if text:
                    return text

    return ""


def _parse_json_string(text):
    stripped = str(text).strip()
    if not stripped:
        return None

    if stripped[0] not in "{[":
        return None

    if stripped[-1] not in "}]":
        return None

    try:
        return json.loads(stripped)
    except Exception:
        return None


def _extract_text_for_keys(value, keys, depth=0):
    if depth > 3:
        return ""

    if isinstance(value, dict):
        for key in keys:
            if key in value:
                text = _extract_text_for_keys(value[key], keys, depth + 1)
                if text:
                    return text

        for key in ("data", "details", "result", "notification", "meta", "payload"):
            nested = value.get(key)
            if isinstance(nested, (dict, list, str)):
                text = _extract_text_for_keys(nested, keys, depth + 1)
                if text:
                    return text
        return ""

    if isinstance(value, list):
        for item in value:
            text = _extract_text_for_keys(item, keys, depth + 1)
            if text:
                return text
        return ""

    if isinstance(value, str):
        parsed = _parse_json_string(value)
        if parsed is not None:
            return _extract_text_for_keys(parsed, keys, depth + 1)
        return _coerce_text(value)

    return _coerce_text(value)


def _first_text(payload, keys):
    return _extract_text_for_keys(payload, keys)


def _first_line(text):
    for line in str(text).splitlines():
        compact = " ".join(line.split())
        if compact:
            return compact
    return ""


def _clip_text(text, limit):
    compact = " ".join(str(text).split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _build_notification(payload, settings, self_test=False):
    title = str(settings.get("title") or DEFAULT_SETTINGS["title"])
    if self_test:
        title = f"{title} (self-test)"

    body = _first_text(payload, ("message", "summary", "text", "content", "raw_text"))
    body = _first_line(body)

    event = _first_text(payload, ("event", "type"))
    if not body:
        if event and event.lower() not in KNOWN_COMPLETION_EVENTS:
            body = f"Event: {event}"

    if not body:
        body = str(settings.get("default_body") or DEFAULT_SETTINGS["default_body"])

    return title, _clip_text(body, int(settings.get("max_message_chars", 140)))


def _get_foreground_window_info():
    hwnd = _user32.GetForegroundWindow()
    if not hwnd:
        return {}

    window_title = ""
    try:
        title_length = _user32.GetWindowTextLengthW(hwnd)
        if title_length > 0:
            title_buffer = create_unicode_buffer(title_length + 1)
            _user32.GetWindowTextW(hwnd, title_buffer, title_length + 1)
            window_title = title_buffer.value
    except Exception:
        window_title = ""

    pid = wintypes.DWORD(0)
    try:
        _user32.GetWindowThreadProcessId(hwnd, byref(pid))
    except Exception:
        pid = wintypes.DWORD(0)

    if not pid.value:
        return {"window_title": window_title}

    process_name = ""
    process_path = ""
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if handle:
        try:
            buffer_length = wintypes.DWORD(32768)
            buffer = create_unicode_buffer(buffer_length.value)
            if _kernel32.QueryFullProcessImageNameW(handle, 0, buffer, byref(buffer_length)):
                process_path = buffer.value
                process_name = Path(process_path).name
        except Exception:
            process_name = ""
            process_path = ""
        finally:
            _kernel32.CloseHandle(handle)

    return {
        "process_id": int(pid.value),
        "process_name": process_name,
        "process_path": process_path,
        "window_title": window_title,
    }


def _should_suppress_visual_notification(settings, self_test=False):
    if self_test:
        return False, {}

    if not settings.get("suppress_visual_when_codex_focused", True):
        return False, {}

    names = settings.get("suppress_visual_process_names") or ["Codex.exe"]
    blocked = {str(name).lower() for name in names if str(name).strip()}
    if not blocked:
        return False, {}

    info = _get_foreground_window_info()
    process_name = str(info.get("process_name") or "").lower()
    if process_name and process_name in blocked:
        return True, info

    return False, info


def _is_blocked_focus_process(settings, focus_info):
    names = settings.get("suppress_visual_process_names") or ["Codex.exe"]
    blocked = {str(name).lower() for name in names if str(name).strip()}
    if not blocked:
        return False

    process_name = str((focus_info or {}).get("process_name") or "").lower()
    return bool(process_name and process_name in blocked)


def _should_suppress_sound_notification(settings, self_test=False, focus_info=None):
    if self_test:
        return False, focus_info or {}

    if not settings.get("suppress_sound_when_codex_focused", True):
        return False, focus_info or {}

    info = focus_info or _get_foreground_window_info()
    if _is_blocked_focus_process(settings, info):
        return True, info

    return False, info


def _should_notify(payload, self_test=False):
    if self_test:
        return True

    if not payload:
        return True

    event = payload.get("event") or payload.get("type") or ""
    if isinstance(event, str) and event.lower() in KNOWN_COMPLETION_EVENTS:
        return True

    return True


def _notification_signature(payload, title, body):
    event = _first_text(payload, ("event", "type"))
    agent = _first_text(payload, ("agent", "assistant", "model"))
    source = json.dumps(
        {
            "title": title,
            "body": body,
            "event": event,
            "agent": agent,
        },
        ensure_ascii=True,
        sort_keys=True,
    )
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _debounce_suppressed(settings, signature, self_test=False):
    if self_test:
        return False, {}

    try:
        window = float(settings.get("debounce_seconds", 0) or 0)
    except Exception:
        window = 0

    if window <= 0:
        return False, {}

    state = _load_state(settings)
    last_sent_at = float(state.get("last_sent_at", 0) or 0)
    last_signature = str(state.get("last_signature") or "")
    mode = str(settings.get("debounce_mode") or "signature").lower()

    if time.time() - last_sent_at >= window:
        return False, state

    if mode == "all":
        return True, state

    return signature == last_signature, state


def _remember_notification(settings, signature):
    _save_state(
        settings,
        {
            "last_sent_at": time.time(),
            "last_signature": signature,
        },
    )


def _find_toast_host(settings):
    hosts = settings.get("toast_host_preference") or DEFAULT_SETTINGS["toast_host_preference"]
    if not isinstance(hosts, list):
        hosts = DEFAULT_SETTINGS["toast_host_preference"]

    for host in hosts:
        candidate = os.path.expandvars(str(host))
        if "\\" in candidate or "/" in candidate:
            if Path(candidate).is_file():
                return candidate
            continue

        path = shutil.which(candidate)
        if path:
            return path

    return None


def _show_mshta_popup_async(settings, title, body):
    script_path = Path(settings["popup_script_path"])
    if not script_path.is_file():
        return "popup_script_missing"

    host = Path(r"C:\Windows\System32\mshta.exe")
    if not host.is_file():
        return "mshta_missing"

    try:
        timeout_seconds = int(settings.get("popup_timeout_seconds", 2) or 2)
    except Exception:
        timeout_seconds = 2

    query = urllib.parse.urlencode(
        {
            "title": title,
            "body": body,
            "timeout": str(max(timeout_seconds, 1)),
        }
    )
    popup_target = f"{script_path.as_uri()}?{query}"

    creationflags = 0
    for flag_name in ("CREATE_NO_WINDOW", "DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
        creationflags |= getattr(subprocess, flag_name, 0)

    try:
        process = subprocess.Popen(
            [
                str(host),
                popup_target,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        return "mshta_popup_spawned", process.pid
    except Exception as exc:
        return f"mshta_popup_failed:{type(exc).__name__}:{exc}", None


def _show_wscript_popup_async(settings, title, body):
    script_path = PROJECT_ROOT / "notify_popup.vbs"
    if not script_path.is_file():
        return "popup_script_missing"

    host = Path(r"C:\Windows\System32\wscript.exe")
    if not host.is_file():
        return "wscript_missing"

    try:
        timeout_seconds = int(settings.get("popup_timeout_seconds", 2) or 2)
    except Exception:
        timeout_seconds = 2

    creationflags = 0
    for flag_name in ("CREATE_NO_WINDOW", "DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
        creationflags |= getattr(subprocess, flag_name, 0)

    try:
        process = subprocess.Popen(
            [
                str(host),
                "//nologo",
                str(script_path),
                title,
                body,
                str(max(timeout_seconds, 1)),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        return "wscript_popup_spawned", process.pid
    except Exception as exc:
        return f"wscript_popup_failed:{type(exc).__name__}:{exc}", None


def _show_powershell_toast_async(settings, title, body):
    if not settings.get("enable_toast", True):
        return "disabled"

    host = _find_toast_host(settings)
    if not host:
        return "toast_host_missing"

    title_xml = html.escape(title, quote=False)
    body_xml = html.escape(body, quote=False)
    app_id = html.escape(str(settings.get("toast_app_id") or DEFAULT_SETTINGS["toast_app_id"]), quote=False)
    script = rf"""
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] > $null
$xml = @"
<toast>
  <visual>
    <binding template="ToastGeneric">
      <text>{title_xml}</text>
      <text>{body_xml}</text>
    </binding>
  </visual>
</toast>
"@
$doc = New-Object Windows.Data.Xml.Dom.XmlDocument
$doc.LoadXml($xml)
$toast = [Windows.UI.Notifications.ToastNotification]::new($doc)
$notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("{app_id}")
$notifier.Show($toast)
""".strip()

    creationflags = 0
    for flag_name in ("CREATE_NO_WINDOW", "DETACHED_PROCESS", "CREATE_NEW_PROCESS_GROUP"):
        creationflags |= getattr(subprocess, flag_name, 0)

    try:
        subprocess.Popen(
            [
                host,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-Command",
                script,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        return "toast_spawned"
    except Exception as exc:
        return f"toast_failed:{type(exc).__name__}:{exc}"


def _show_managed_popup(settings, title, body):
    with _visual_mutex(settings) as acquired:
        if not acquired:
            return "popup_mutex_timeout"

        replace_result = _replace_existing_popup(settings)
        popup_result, pid = _show_mshta_popup_async(settings, title, body)
        if popup_result == "mshta_popup_spawned" and pid:
            _remember_popup_process(settings, pid, "mshta")
            return popup_result if replace_result == "no_existing_popup" else f"{replace_result}|{popup_result}"

        fallback_result, fallback_pid = _show_wscript_popup_async(settings, title, body)
        if fallback_result == "wscript_popup_spawned" and fallback_pid:
            _remember_popup_process(settings, fallback_pid, "wscript")
            prefix = popup_result
            if replace_result != "no_existing_popup":
                prefix = f"{replace_result}|{prefix}"
            return f"{prefix}|{fallback_result}"

        if replace_result != "no_existing_popup":
            return f"{replace_result}|{popup_result}|{fallback_result}"
        return f"{popup_result}|{fallback_result}"


def _show_managed_wscript_popup(settings, title, body):
    with _visual_mutex(settings) as acquired:
        if not acquired:
            return "popup_mutex_timeout"

        replace_result = _replace_existing_popup(settings)
        popup_result, popup_pid = _show_wscript_popup_async(settings, title, body)
        if popup_result == "wscript_popup_spawned" and popup_pid:
            _remember_popup_process(settings, popup_pid, "wscript")
            return popup_result if replace_result == "no_existing_popup" else f"{replace_result}|{popup_result}"

        if replace_result != "no_existing_popup":
            return f"{replace_result}|{popup_result}"
        return popup_result


def _show_visual_notification(settings, title, body, self_test=False, focus_info=None):
    if not settings.get("enable_toast", True):
        return "disabled", focus_info or {}

    if focus_info is None:
        suppressed, focus_info = _should_suppress_visual_notification(settings, self_test=self_test)
    else:
        suppressed = (not self_test) and settings.get("suppress_visual_when_codex_focused", True) and _is_blocked_focus_process(settings, focus_info)
    if suppressed:
        return "suppressed_focused_codex", focus_info

    mode = str(settings.get("visual_mode") or "mshta_popup").lower()

    if mode == "none":
        return "disabled", focus_info

    if mode == "powershell_toast":
        return _show_powershell_toast_async(settings, title, body), focus_info

    if mode == "mshta_popup":
        return _show_managed_popup(settings, title, body), focus_info

    if mode == "wscript_popup":
        return _show_managed_wscript_popup(settings, title, body), focus_info

    popup_result = _show_managed_popup(settings, title, body)
    if "spawned" in popup_result:
        return popup_result, focus_info

    toast_result = _show_powershell_toast_async(settings, title, body)
    return f"{popup_result}|{toast_result}", focus_info


def _play_sound(settings, self_test=False, focus_info=None):
    if not settings.get("enable_sound", True):
        return "sound_disabled"

    suppressed, focus_info = _should_suppress_sound_notification(
        settings,
        self_test=self_test,
        focus_info=focus_info,
    )
    if suppressed:
        return "suppressed_focused_codex"

    sound_path = Path(settings["sound_path"])
    sound_mode = str(settings.get("sound_mode") or "wav_primary_then_fallback").lower()
    sound_sync = bool(settings.get("sound_sync", True))
    fallback_mode = str(settings.get("fallback_mode") or "message_beep").lower()

    if winsound is None:
        return "winsound_unavailable"

    wav_result = "sound_file_missing"
    try:
        if sound_path.is_file():
            flags = winsound.SND_FILENAME
            if not sound_sync:
                flags |= winsound.SND_ASYNC
            winsound.PlaySound(
                str(sound_path),
                flags,
            )
            wav_result = "wav_played_sync" if sound_sync else "wav_played_async"
    except Exception as exc:
        wav_result = f"wav_failed:{type(exc).__name__}:{exc}"

    if sound_mode == "wav_primary_only" and wav_result.startswith("wav_played"):
        return wav_result

    if sound_mode == "wav_primary_then_fallback" and wav_result.startswith("wav_played"):
        return wav_result

    if sound_mode in {"wav_plus_message_beep", "message_beep_only"}:
        try:
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
            if sound_mode == "message_beep_only":
                return "message_beep_played"
            return f"{wav_result}|message_beep_played"
        except Exception as exc:
            beep_error = f"message_beep_failed:{type(exc).__name__}:{exc}"
            if sound_mode == "message_beep_only":
                return beep_error
            wav_result = f"{wav_result}|{beep_error}"

    if sound_mode == "wav_plus_beep":
        try:
            winsound.Beep(1568, 220)
            return f"{wav_result}|beep_played"
        except Exception as exc:
            wav_result = f"{wav_result}|beep_failed:{type(exc).__name__}:{exc}"

    if wav_result == "wav_played":
        return wav_result

    wav_error = wav_result

    if fallback_mode == "none":
        return wav_error

    if fallback_mode == "beep":
        try:
            winsound.Beep(1046, 180)
            return f"{wav_error}|beep_played"
        except Exception as exc:
            return f"{wav_error}|beep_failed:{type(exc).__name__}:{exc}"

    try:
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
        return f"{wav_error}|message_beep_played"
    except Exception as exc:
        try:
            winsound.Beep(1046, 180)
            return f"{wav_error}|message_beep_failed:{type(exc).__name__}:{exc}|beep_played"
        except Exception as beep_exc:
            return (
                f"{wav_error}|message_beep_failed:{type(exc).__name__}:{exc}"
                f"|beep_failed:{type(beep_exc).__name__}:{beep_exc}"
            )


def _payload_preview(payload):
    try:
        preview = json.dumps(payload, ensure_ascii=False)
    except Exception:
        preview = repr(payload)
    return _clip_text(preview, 240)


def main(argv=None):
    argv = argv or sys.argv
    settings, settings_errors = _load_settings()
    payload, self_test = _read_payload(argv)
    title, body = _build_notification(payload, settings, self_test=self_test)
    signature = _notification_signature(payload, title, body)

    log_context = {
        "self_test": self_test,
        "python_executable": sys.executable,
        "resolved_python": os.environ.get("CODEX_NOTIFY_RESOLVED_PYTHON", ""),
        "payload_preview": _payload_preview(payload),
        "title": title,
        "body": body,
        "settings_errors": settings_errors,
        "signature": signature,
    }

    if not _should_notify(payload, self_test=self_test):
        _append_log(settings, {"result": "skipped", "reason": "should_notify_false", **log_context})
        return 0

    suppressed, _state = _debounce_suppressed(settings, signature, self_test=self_test)
    if suppressed:
        _append_log(settings, {"result": "suppressed", "reason": "debounced", **log_context})
        return 0

    focus_info = {} if self_test else _get_foreground_window_info()
    toast_result, focus_info = _show_visual_notification(
        settings,
        title,
        body,
        self_test=self_test,
        focus_info=focus_info,
    )
    sound_result = _play_sound(settings, self_test=self_test, focus_info=focus_info)
    if not self_test:
        _remember_notification(settings, signature)

    _append_log(
        settings,
        {
            "result": "notified",
            "toast_result": toast_result,
            "sound_result": sound_result,
            "foreground_process_name": focus_info.get("process_name", ""),
            "foreground_window_title": focus_info.get("window_title", ""),
            **log_context,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
