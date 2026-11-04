"""/** 已核验宿主的独立弹窗控制通道 */"""

import ctypes
from ctypes import wintypes
import json
import re
import struct
import time
import uuid
from urllib.parse import urlparse

from MCP.mcp_result import McpBusinessError


def _exchange(row, request):
    """/** @param row 已核验宿主登记 @param request 控制请求 @return 原生模态快照与提交状态 */"""
    endpoint = urlparse(row["backend_url"])
    match = re.fullmatch(r"/bbb-mcp-([0-9a-f]{32})", endpoint.path)
    if match is None:
        raise ValueError("DIALOG_HOST_IDENTITY")
    name = "\\\\.\\pipe\\BBBMcpDialog-" + str(row["process_id"]) + "-" + match[1]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    kernel.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    kernel.WriteFile.argtypes = kernel.ReadFile.argtypes
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    if not kernel.WaitNamedPipeW(name, 300):
        raise OSError("DIALOG_BRIDGE_UNAVAILABLE")
    handle = kernel.CreateFileW(name, 0xC0000000, 0, None, 3, 0x40000000, None)
    if handle == ctypes.c_void_p(-1).value:
        raise OSError("DIALOG_BRIDGE_CONNECT_FAILED")
    try:
        data = json.dumps(request, ensure_ascii=False).encode("utf-8")
        payload = struct.pack("<i", len(data)) + data
        class Overlapped(ctypes.Structure):
            _fields_ = [("internal", ctypes.c_size_t), ("high", ctypes.c_size_t),
                ("offset", wintypes.DWORD), ("offset_high", wintypes.DWORD), ("event", wintypes.HANDLE)]
        kernel.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        kernel.CreateEventW.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.POINTER(Overlapped), ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
        kernel.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.POINTER(Overlapped)]
        deadline = time.monotonic() + 1.0
        def transfer(operation, buffer, size):
            offset = 0
            while offset < size:
                event = kernel.CreateEventW(None, True, False, None)
                if not event:
                    raise OSError("DIALOG_BRIDGE_EVENT_FAILED")
                overlapped = Overlapped(event=event)
                count = wintypes.DWORD()
                try:
                    success = operation(handle, ctypes.byref(buffer, offset), size - offset, ctypes.byref(count), ctypes.byref(overlapped))
                    if not success and ctypes.get_last_error() != 997:
                        raise OSError("DIALOG_BRIDGE_IO_FAILED")
                    milliseconds = max(0, int((deadline - time.monotonic()) * 1000))
                    if kernel.WaitForSingleObject(event, milliseconds) != 0:
                        kernel.CancelIoEx(handle, ctypes.byref(overlapped))
                        kernel.GetOverlappedResult(handle, ctypes.byref(overlapped), ctypes.byref(count), True)
                        raise OSError("DIALOG_BRIDGE_TIMEOUT")
                    if not kernel.GetOverlappedResult(handle, ctypes.byref(overlapped), ctypes.byref(count), False) or not count.value:
                        raise OSError("DIALOG_BRIDGE_IO_FAILED")
                    offset += count.value
                finally:
                    kernel.CloseHandle(event)
        if len(data) > 8192:
            raise ValueError("DIALOG_REQUEST_SIZE")
        transfer(kernel.WriteFile, ctypes.create_string_buffer(payload), len(payload))
        header = ctypes.create_string_buffer(4)
        transfer(kernel.ReadFile, header, 4)
        size = struct.unpack("<i", header.raw)[0]
        if not 2 <= size <= 262144:
            raise OSError("DIALOG_BRIDGE_RESPONSE_SIZE")
        buffer = ctypes.create_string_buffer(size)
        transfer(kernel.ReadFile, buffer, size)
        value = json.loads(buffer.raw)
        if value.get("snapshot", {}).get("pid") != row["process_id"]:
            raise OSError("DIALOG_BRIDGE_IDENTITY_CHANGED")
        return value
    finally:
        kernel.CloseHandle(handle)


def native_dialogs(pid):
    """/** @param pid 已核验编辑器编号 @return 该进程系统模态框的实际按钮 */"""
    user = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    user.EnumChildWindows.argtypes = [wintypes.HWND, callback_type, wintypes.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetWindow.restype = wintypes.HWND
    for name in ("IsWindowVisible", "IsWindowEnabled"):
        getattr(user, name).argtypes = [wintypes.HWND]
    for name in ("GetClassNameW", "GetWindowTextW"):
        getattr(user, name).argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    dialogs = []
    def text(handle, method="GetWindowTextW"):
        buffer = ctypes.create_unicode_buffer(1001)
        getattr(user, method)(handle, buffer, len(buffer))
        return buffer.value
    def visit(handle, unused):
        identity = wintypes.DWORD()
        user.GetWindowThreadProcessId(handle, ctypes.byref(identity))
        owner = user.GetWindow(handle, 4)
        if identity.value != pid or not user.IsWindowVisible(handle) or text(handle, "GetClassNameW") != "#32770" or not owner or user.IsWindowEnabled(owner):
            return True
        item = {"kind": "native", "window": str(handle), "title": text(handle), "text": [], "buttons": []}
        def child(control, unused_child):
            label = text(control)
            kind = text(control, "GetClassNameW")
            if kind == "Static" and label and len(item["text"]) < 32:
                item["text"].append(label)
            if kind == "Button" and user.IsWindowVisible(control) and user.IsWindowEnabled(control):
                item["buttons"].append({"id": str(control), "label": label})
            return True
        user.EnumChildWindows(handle, callback_type(child), 0)
        import hashlib
        item["id"] = "native-" + hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()[:24]
        dialogs.append(item)
        return True
    user.EnumWindows(callback_type(visit), 0)
    return dialogs


def inspect_dialog(row):
    """/** @param row 已核验宿主登记 @return 弹窗状态与独立通道诊断 */"""
    try:
        value = _exchange(row, {"action": "inspect"})
        state = value["snapshot"]
        if state.get("open"):
            return {"status": "blocked", "code": "EDITOR_DIALOG_OPEN", "dialog": {**state, "kind": "slate"}, "outcome": value.get("outcome")}
    except OSError as error:
        value = {"bridge": str(error)}
    dialogs = native_dialogs(row["process_id"])
    if dialogs:
        return {"status": "blocked", "code": "EDITOR_DIALOG_OPEN", "dialog": dialogs[-1]}
    return {"status": "unknown" if "bridge" in value else "clear", **{key: value[key] for key in ("bridge", "outcome") if key in value}}


def respond_dialog(row, dialog, button, request=None):
    """/** @param row 已核验宿主 @param dialog 当前快照标识 @param button 明确选项 @param request 幂等身份 @return 已提交选项与实际状态 */"""
    state = inspect_dialog(row)
    current = state.get("dialog", {})
    if current.get("id") != dialog or button not in {item["id"] for item in current.get("buttons", [])}:
        raise McpBusinessError({"status": "rejected", "code": "DIALOG_SNAPSHOT_CHANGED", "next": {"tool": "control_task", "arguments": {"action": "inspect_dialog"}}})
    if current["kind"] == "slate":
        return _exchange(row, {"action": "respond", "dialog": dialog, "button": button, "request": request or uuid.uuid4().hex})
    user = ctypes.WinDLL("user32", use_last_error=True)
    user.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user.GetParent.argtypes = [wintypes.HWND]
    user.GetParent.restype = wintypes.HWND
    user.GetDlgCtrlID.argtypes = [wintypes.HWND]
    if not user.PostMessageW(user.GetParent(int(button)), 0x111, user.GetDlgCtrlID(int(button)), int(button)):
        raise OSError("DIALOG_OPTION_DISPATCH_FAILED")
    return {"status": "dispatched", "next": {"tool": "control_task", "arguments": {"action": "inspect_dialog"}}}
