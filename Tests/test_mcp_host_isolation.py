import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parents[1] / "Scripts"
sys.path.insert(0, str(SCRIPTS))
from MCP.mcp_project_host import ProjectHostGuard, editor_inventory, project_identity


class ProjectHostTests(unittest.TestCase):
    """/** 项目归属跨端口核验和真实跨进程唯一锁验收 */"""

    def test_project_file_and_directory_share_identity(self):
        """/** @return 文件路径与规范化目录属于同一项目 */"""
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(project_identity(Path(root) / "Game.uproject"), project_identity(root))
            self.assertEqual(project_identity(Path(root) / "Child" / ".."), project_identity(root))

    def test_public_contract_contains_only_main_project_controls(self):
        """/** @return 副本功能从公共协议 SDK 和源码同时移除 */"""
        from MCP.mcp_call import McpSession
        from MCP.mcp_task_gateway import control_tools
        removed = {"prepare_test_snapshot", "start_test_run", "call_test_tool", "inspect_test_runs", "stop_test_run"}
        tools = {item["name"] for item in control_tools()}
        self.assertTrue(removed.isdisjoint(tools))
        self.assertEqual(len(tools), 11)
        self.assertTrue(all(not hasattr(McpSession, name) for name in removed))
        self.assertFalse((SCRIPTS / "MCP" / "mcp_test_runner.py").exists())

    def test_inventory_output_hides_command_line_credentials(self):
        """/** @return 公开进程清单仅包含项目 进程与端口 */"""
        payload = [{"ProcessId": 101, "CommandLine": '"C:\\Project With Spaces\\Game.uproject" -BBBProtectedMcpPort=8011 -BBBProtectedMcpKey=secret-key'}]
        result = subprocess.CompletedProcess([], 0, json.dumps(payload).encode(), b"")
        with patch("MCP.mcp_project_host.subprocess.run", return_value=result):
            hosts = editor_inventory()
        self.assertEqual(hosts[0]["process_id"], 101)
        self.assertEqual(hosts[0]["public_port"], 8011)
        self.assertNotIn("secret-key", json.dumps(hosts))
        self.assertNotIn("CommandLine", json.dumps(hosts))

    def test_all_ports_share_project_conflict_and_recovery(self):
        """/** @return 切换端口仍识别同项目冲突 退出后刷新为独占 */"""
        project = project_identity("project")
        hosts = [{"process_id": 101, "project_root": project, "public_port": 8010},
            {"process_id": 202, "project_root": project, "public_port": 8011},
            {"process_id": 303, "project_root": project_identity("other"), "public_port": 8000}]
        guard = ProjectHostGuard(project, 101, lambda: list(hosts))
        self.assertFalse(guard.inspect()["exclusive"])
        self.assertEqual(len(guard.inspect()["hosts"]), 2)
        hosts.pop(1)
        self.assertTrue(guard.inspect(force=True)["exclusive"])

    def test_inspection_failure_has_explicit_safe_state(self):
        """/** @return 进程查询异常提供可读阻塞证据 */"""
        def fail():
            """/** @return 模拟只读进程查询故障 */"""
            raise RuntimeError("private-command-line")
        state = ProjectHostGuard("project", 101, fail).inspect()
        self.assertFalse(state["verified"])
        self.assertFalse(state["exclusive"])
        self.assertNotIn("private-command-line", json.dumps(state))

    def test_existing_gateway_on_same_host_blocks_second_coordinator(self):
        """/** @return 一个编辑器同样只归属一个网关 */"""
        project = project_identity("project")
        hosts = [{"kind": "editor", "process_id": 101, "project_root": project, "public_port": 8010},
            {"kind": "gateway", "process_id": 202, "project_root": project, "public_port": 8011}]
        state = ProjectHostGuard(project, 101, lambda: hosts).inspect()
        self.assertFalse(state["exclusive"])
        self.assertEqual(state["gateways"][0]["public_port"], 8011)

    def test_gateway_inventory_uses_public_identity_and_hides_backend(self):
        """/** @return 网关清单覆盖全部端口并隐藏后端密钥 */"""
        payload = [{"ProcessId": 101, "CommandLine": 'python "C:\\Tools\\mcp_task_gateway.py" --port 8011 --project-root "C:\\Project With Spaces" --backend-url http://127.0.0.1:19000/private-secret --host-pid 202'}]
        result = subprocess.CompletedProcess([], 0, json.dumps(payload).encode(), b"")
        with patch("MCP.mcp_project_host.subprocess.run", return_value=result):
            hosts = editor_inventory()
        self.assertEqual(hosts[0]["kind"], "gateway")
        self.assertEqual(hosts[0]["public_port"], 8011)
        self.assertNotIn("private-secret", json.dumps(hosts))

    @unittest.skipUnless(os.name == "nt", "需要 Windows 项目互斥锁")
    def test_actual_other_process_is_blocked_until_gateway_exits(self):
        """/** @return 真实第二进程受项目唯一锁约束 释放后取得归属 */"""
        with tempfile.TemporaryDirectory() as root:
            guard = ProjectHostGuard(root, 101, lambda: [{"process_id": 101, "project_root": root, "public_port": 8010}])
            guard.acquire()
            script = "\n".join([
                "import sys", "sys.dont_write_bytecode = True", "sys.path.insert(0, sys.argv[1])",
                "from MCP.mcp_project_host import ProjectHostGuard",
                "root = sys.argv[2]",
                "guard = ProjectHostGuard(root, 202, lambda: [{'process_id': 202, 'project_root': root, 'public_port': 8011}])",
                "try:", "    guard.acquire()", "    print('ACQUIRED')", "    guard.close()",
                "except RuntimeError as error:", "    print(str(error))",
            ])
            try:
                result = subprocess.run([sys.executable, "-B", "-c", script, str(SCRIPTS), root], capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), "PROJECT_GATEWAY_ALREADY_RUNNING")
            finally:
                guard.close()
            result = subprocess.run([sys.executable, "-B", "-c", script, str(SCRIPTS), root], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), "ACQUIRED")

    @unittest.skipUnless(os.name == "nt", "需要 Windows 项目互斥锁")
    def test_startup_conflict_releases_its_own_lock(self):
        """/** @return 启动冲突退出时释放自身项目锁 */"""
        with tempfile.TemporaryDirectory() as root:
            guard = ProjectHostGuard(root, 101, lambda: [])
            with self.assertRaisesRegex(RuntimeError, "PROJECT_HOST_CONFLICT"):
                guard.acquire()
            self.assertIsNone(guard.handle)


if __name__ == "__main__":
    unittest.main()
