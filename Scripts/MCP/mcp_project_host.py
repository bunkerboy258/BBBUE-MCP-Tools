import json
import os
from pathlib import Path
import re
import subprocess


def project_identity(path):
    """
    /**
     * @param path\t项目目录或项目文件
     * @return 消除目录链接和大小写差异的项目身份
     */
    """
    value = Path(path).resolve()
    if value.suffix.lower() == ".uproject":
        value = value.parent
    return os.path.normcase(str(value))


def editor_inventory():
    """
    /**
     * @return 本机编辑器的项目身份 进程编号和公开端口
     */
    """
    command = "$ErrorActionPreference = 'Stop'; [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); @(Get-CimInstance Win32_Process -Filter \"Name = 'UnrealEditor.exe'\" | Select-Object ProcessId,CommandLine) | ConvertTo-Json -Compress"
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError("PROJECT_HOST_INSPECTION_FAILED")
    items = json.loads(result.stdout.decode("utf-8-sig") or "[]")
    if isinstance(items, dict):
        items = [items]
    hosts = []
    for item in items:
        command_line = item.get("CommandLine") or ""
        match = re.search(r'(?:"([^"\r\n]+\.uproject)"|([^\s"]+\.uproject))', command_line, re.I)
        if match is None:
            continue
        port = re.search(r"-BBBMcpServicePort=(\d+)(?:\s|$)", command_line, re.I)
        role = re.search(r"-BBBMcpHostRole=(\w+)(?:\s|$)", command_line, re.I)
        test = re.search(r"-BBBMcpTestId=([0-9a-f]{16})(?:\s|$)", command_line, re.I)
        hosts.append({"kind": "editor", "process_id": item["ProcessId"], "project_root": project_identity(match.group(1) or match.group(2)),
            "public_port": int(port.group(1)) if port else None, "role": "test" if role and role.group(1).lower() == "test" else "editor",
            "batch": test.group(1) if test else None})
    return hosts
