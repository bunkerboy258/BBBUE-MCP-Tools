import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import secrets
import subprocess


class _SidAttributes(ctypes.Structure):
    _fields_ = [("sid", ctypes.c_void_p), ("attributes", wintypes.DWORD)]


class _StartupInfo(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("reserved", wintypes.LPWSTR),
        ("desktop", wintypes.LPWSTR), ("title", wintypes.LPWSTR),
        ("x", wintypes.DWORD), ("y", wintypes.DWORD),
        ("width", wintypes.DWORD), ("height", wintypes.DWORD),
        ("chars_x", wintypes.DWORD), ("chars_y", wintypes.DWORD),
        ("fill", wintypes.DWORD), ("flags", wintypes.DWORD),
        ("show", wintypes.WORD), ("reserved_size", wintypes.WORD),
        ("reserved_bytes", ctypes.c_void_p), ("stdin", wintypes.HANDLE),
        ("stdout", wintypes.HANDLE), ("stderr", wintypes.HANDLE)]


class _ProcessInfo(ctypes.Structure):
    _fields_ = [("process", wintypes.HANDLE), ("thread", wintypes.HANDLE),
        ("process_id", wintypes.DWORD), ("thread_id", wintypes.DWORD)]


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("descriptor", ctypes.c_void_p), ("inherit", wintypes.BOOL)]


class _JobLimits(ctypes.Structure):
    _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
        ("flags", wintypes.DWORD), ("minimum_working_set", ctypes.c_size_t),
        ("maximum_working_set", ctypes.c_size_t), ("active_processes", wintypes.DWORD),
        ("affinity", ctypes.c_size_t), ("priority", wintypes.DWORD),
        ("scheduling", wintypes.DWORD)]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("basic", _JobLimits), ("io", ctypes.c_uint64 * 6),
        ("process_memory", ctypes.c_size_t), ("job_memory", ctypes.c_size_t),
        ("peak_process_memory", ctypes.c_size_t), ("peak_job_memory", ctypes.c_size_t)]


def _checked(success):
    if not success:
        raise ctypes.WinError(ctypes.get_last_error())


class TestProcess:
    """/** 持有一个受限测试进程及其子进程的生命周期 */"""

    def __init__(self, arguments, directory, environment):
        """
        /**
         * @param arguments\t实际程序与参数
         * @param directory\t本批次已建立的空输出目录
         * @param environment\t测试进程环境
         * @return 受限进程
         */
        """
        if os.name != "nt":
            raise RuntimeError("WINDOWS_TEST_PROCESS_REQUIRED")
        directory = Path(directory)
        for item in (directory, *directory.parents):
            if item.is_symlink() or (item.exists() and item.stat().st_file_attributes & 0x400):
                raise ValueError("TEST_OUTPUT_LINK_REQUIRES_REVIEW")
        if directory.is_symlink() or not directory.is_dir() or any(directory.iterdir()):
            raise ValueError("EMPTY_TEST_DIRECTORY_REQUIRED")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.security = ctypes.WinDLL("advapi32", use_last_error=True)
        self.user = ctypes.WinDLL("user32", use_last_error=True)
        self.process = None
        self.job = None
        self.desktop = None
        self.pid = None
        self._declare()
        source = wintypes.HANDLE()
        token = wintypes.HANDLE()
        sid = ctypes.c_void_p()
        descriptor = ctypes.c_void_p()
        restricted_code = ctypes.c_void_p()
        interactive = ctypes.c_void_p()
        everyone = ctypes.c_void_p()
        integrity = ctypes.c_void_p()
        try:
            _checked(self.security.OpenProcessToken(self.kernel.GetCurrentProcess(), 0x8B, ctypes.byref(source)))
            user_buffer = self._token_info(source, 1)
            user = ctypes.cast(user_buffer, ctypes.POINTER(_SidAttributes)).contents.sid
            user_text = self._sid_text(user)
            restriction = "S-1-5-21-" + "-".join(str(secrets.randbelow(0xFFFFFFFE) + 1) for _ in range(4))
            _checked(self.security.ConvertStringSidToSidW(restriction, ctypes.byref(sid)))
            groups_buffer = self._token_info(source, 2)
            count = ctypes.cast(groups_buffer, ctypes.POINTER(wintypes.DWORD)).contents.value
            offset = (ctypes.sizeof(wintypes.DWORD) + ctypes.alignment(_SidAttributes) - 1) // ctypes.alignment(_SidAttributes) * ctypes.alignment(_SidAttributes)
            groups = (_SidAttributes * count).from_buffer(groups_buffer, offset)
            restrictions = [_SidAttributes(sid, 0)]
            _checked(self.security.ConvertStringSidToSidW("S-1-5-12", ctypes.byref(restricted_code)))
            restrictions.append(_SidAttributes(restricted_code, 0))
            _checked(self.security.ConvertStringSidToSidW("S-1-5-4", ctypes.byref(interactive)))
            restrictions.append(_SidAttributes(interactive, 0))
            _checked(self.security.ConvertStringSidToSidW("S-1-1-0", ctypes.byref(everyone)))
            restrictions.append(_SidAttributes(everyone, 0))
            restrictions.extend(_SidAttributes(group.sid, 0) for group in groups if group.attributes & 0xC0000000 == 0xC0000000)
            restricted = (_SidAttributes * len(restrictions))(*restrictions)
            _checked(self.security.CreateRestrictedToken(source, 0x9, 0, None, 0, None, len(restricted), restricted, ctypes.byref(token)))
            _checked(self.security.ConvertStringSidToSidW("S-1-16-4096", ctypes.byref(integrity)))
            label = _SidAttributes(integrity, 0x20)
            _checked(self.security.SetTokenInformation(token, 25, ctypes.byref(label), ctypes.sizeof(label) + self.security.GetLengthSid(integrity)))
            sddl = "D:P(A;OICI;GA;;;SY)(A;OICI;GA;;;" + user_text + ")(A;OICI;GA;;;" + restriction + ")S:(ML;OICI;NW;;;LW)"
            _checked(self.security.ConvertStringSecurityDescriptorToSecurityDescriptorW(sddl, 1, ctypes.byref(descriptor), None))
            _checked(self.security.SetFileSecurityW(str(directory), 0x80000004, descriptor))
            _checked(self.security.SetFileSecurityW(str(directory), 0x10, descriptor))
            present = wintypes.BOOL()
            defaulted = wintypes.BOOL()
            acl = ctypes.c_void_p()
            _checked(self.security.GetSecurityDescriptorDacl(descriptor, ctypes.byref(present), ctypes.byref(acl), ctypes.byref(defaulted)))
            _checked(self.security.SetTokenInformation(token, 6, ctypes.byref(acl), ctypes.sizeof(acl)))
            self.job = self.kernel.CreateJobObjectW(None, "Local\\BBBMcpTest_" + directory.name)
            _checked(self.job)
            limits = _ExtendedLimits()
            limits.basic.flags = 0
            _checked(self.kernel.SetInformationJobObject(self.job, 9, ctypes.byref(limits), ctypes.sizeof(limits)))
            startup = _StartupInfo()
            startup.size = ctypes.sizeof(startup)
            startup.flags = 1
            startup.show = 0
            desktop_name = "BBBMcpTest" + secrets.token_hex(8)
            attributes = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), descriptor, False)
            self.desktop = self.user.CreateDesktopW(desktop_name, None, None, 0, 0x1FF, ctypes.byref(attributes))
            _checked(self.desktop)
            startup.desktop = "winsta0\\" + desktop_name
            process = _ProcessInfo()
            command = ctypes.create_unicode_buffer(subprocess.list2cmdline([str(value) for value in arguments]))
            values = {**environment, "TEMP": str(directory), "TMP": str(directory)}
            block = ctypes.create_unicode_buffer("\0".join(key + "=" + str(value) for key, value in sorted(values.items(), key=lambda item: item[0].upper())) + "\0\0")
            _checked(self.security.CreateProcessAsUserW(token, str(arguments[0]), command, None, None, False,
                0x08000000 | 0x400 | 0x4, block, str(directory), ctypes.byref(startup), ctypes.byref(process)))
            self.process = process.process
            self.pid = process.process_id
            try:
                _checked(self.kernel.AssignProcessToJobObject(self.job, self.process))
                retained_job = wintypes.HANDLE()
                _checked(self.kernel.DuplicateHandle(self.kernel.GetCurrentProcess(), self.job, self.process,
                    ctypes.byref(retained_job), 0, False, 2))
                if self.kernel.ResumeThread(process.thread) == 0xFFFFFFFF:
                    raise ctypes.WinError(ctypes.get_last_error())
            except Exception:
                self.kernel.TerminateProcess(self.process, 1)
                raise
            finally:
                self.kernel.CloseHandle(process.thread)
        except Exception:
            self.close()
            raise
        finally:
            for handle in (token, source):
                if handle:
                    self.kernel.CloseHandle(handle)
            for value in (descriptor, sid, restricted_code, interactive, everyone, integrity):
                if value:
                    self.kernel.LocalFree(value)

    def _declare(self):
        bindings = [
            (self.kernel, "GetCurrentProcess", [], wintypes.HANDLE),
            (self.kernel, "CloseHandle", [wintypes.HANDLE], wintypes.BOOL),
            (self.kernel, "DuplicateHandle", [wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.BOOL),
            (self.kernel, "LocalFree", [ctypes.c_void_p], ctypes.c_void_p),
            (self.kernel, "CreateJobObjectW", [ctypes.c_void_p, wintypes.LPCWSTR], wintypes.HANDLE),
            (self.kernel, "SetInformationJobObject", [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            (self.kernel, "AssignProcessToJobObject", [wintypes.HANDLE, wintypes.HANDLE], wintypes.BOOL),
            (self.kernel, "ResumeThread", [wintypes.HANDLE], wintypes.DWORD),
            (self.kernel, "TerminateProcess", [wintypes.HANDLE, wintypes.UINT], wintypes.BOOL),
            (self.kernel, "WaitForSingleObject", [wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            (self.kernel, "GetExitCodeProcess", [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            (self.security, "OpenProcessToken", [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)], wintypes.BOOL),
            (self.security, "GetTokenInformation", [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)], wintypes.BOOL),
            (self.security, "SetTokenInformation", [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
            (self.security, "CreateRestrictedToken", [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.HANDLE)], wintypes.BOOL),
            (self.security, "ConvertStringSidToSidW", [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p)], wintypes.BOOL),
            (self.security, "ConvertSidToStringSidW", [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)], wintypes.BOOL),
            (self.security, "GetLengthSid", [ctypes.c_void_p], wintypes.DWORD),
            (self.security, "ConvertStringSecurityDescriptorToSecurityDescriptorW", [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p], wintypes.BOOL),
            (self.security, "SetFileSecurityW", [wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_void_p], wintypes.BOOL),
            (self.security, "GetSecurityDescriptorDacl", [ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)], wintypes.BOOL),
            (self.security, "CreateProcessAsUserW", [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.POINTER(_StartupInfo), ctypes.POINTER(_ProcessInfo)], wintypes.BOOL),
            (self.user, "CreateDesktopW", [wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_SecurityAttributes)], wintypes.HANDLE),
            (self.user, "CloseDesktop", [wintypes.HANDLE], wintypes.BOOL),
        ]
        for library, name, arguments, result in bindings:
            function = getattr(library, name)
            function.argtypes = arguments
            function.restype = result

    def _token_info(self, token, kind):
        size = wintypes.DWORD()
        self.security.GetTokenInformation(token, kind, None, 0, ctypes.byref(size))
        buffer = ctypes.create_string_buffer(size.value)
        _checked(self.security.GetTokenInformation(token, kind, buffer, size, ctypes.byref(size)))
        return buffer

    def _sid_text(self, sid):
        value = wintypes.LPWSTR()
        _checked(self.security.ConvertSidToStringSidW(sid, ctypes.byref(value)))
        try:
            return value.value
        finally:
            self.kernel.LocalFree(value)

    def poll(self):
        """/** @return 进程退出码或运行状态 */"""
        if self.kernel.WaitForSingleObject(self.process, 0) == 0x102:
            return None
        code = wintypes.DWORD()
        _checked(self.kernel.GetExitCodeProcess(self.process, ctypes.byref(code)))
        return code.value

    @classmethod
    def adopt(cls, pid, created, batch):
        """/** @param pid 原测试进程 @param created 原创建时间 @param batch 原归属 @return 重新持有的受限测试进程 */"""
        from MCP.mcp_host_registry import process_identity
        identity = process_identity(pid)
        if identity is None or identity["created"] != created:
            raise RuntimeError("TEST_PROCESS_IDENTITY_CHANGED")
        value = object.__new__(cls)
        value.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        value.security = ctypes.WinDLL("advapi32", use_last_error=True)
        value.user = ctypes.WinDLL("user32", use_last_error=True)
        value._declare()
        value.kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        value.kernel.OpenProcess.restype = wintypes.HANDLE
        value.kernel.OpenJobObjectW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
        value.kernel.OpenJobObjectW.restype = wintypes.HANDLE
        value.kernel.IsProcessInJob.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
        value.job = value.kernel.OpenJobObjectW(0x1F003F, False, "Local\\BBBMcpTest_" + batch)
        value.process = value.kernel.OpenProcess(0x1000 | 0x100000, False, pid)
        value.desktop = None
        value.pid = pid
        belongs = wintypes.BOOL()
        valid = value.job and value.process and value.kernel.IsProcessInJob(value.process, value.job, ctypes.byref(belongs)) and belongs.value
        if not valid:
            for handle in (value.job, value.process):
                if handle:
                    value.kernel.CloseHandle(handle)
            raise RuntimeError("TEST_PROCESS_JOB_IDENTITY")
        return value

    def wait(self, seconds):
        """/** @param seconds\t等待上限 @return 实际退出码或运行状态 */"""
        self.kernel.WaitForSingleObject(self.process, int(seconds * 1000))
        return self.poll()

    def close(self):
        """/** @return 回收所属测试进程与子进程 */"""
        if self.job:
            self.kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
            _checked(self.kernel.TerminateJobObject(self.job, 0))
            self.kernel.CloseHandle(self.job)
            self.job = None
        if self.process:
            if self.kernel.WaitForSingleObject(self.process, 10000) != 0:
                raise RuntimeError("TEST_PROCESS_EXIT_UNVERIFIED")
            self.kernel.CloseHandle(self.process)
            self.process = None
        if self.desktop:
            self.user.CloseDesktop(self.desktop)
            self.desktop = None
