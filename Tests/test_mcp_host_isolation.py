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
from MCP.mcp_project_host import editor_inventory, project_identity


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
        from MCP.mcp_task_gateway import public_tools
        removed = {"prepare_test_snapshot", "start_test_run", "call_test_tool", "inspect_test_runs", "stop_test_run"}
        tools = {item["name"] for item in public_tools()}
        self.assertTrue(removed.isdisjoint(tools))
        self.assertEqual(tools, {"manage_operator", "find_tools", "describe_tool", "submit_batch", "inspect_tasks", "control_task"})
        self.assertTrue(all(not hasattr(McpSession, name) for name in removed))
        self.assertFalse((SCRIPTS / "MCP" / "mcp_test_runner.py").exists())

    def test_inventory_output_hides_command_line_credentials(self):
        """/** @return 公开进程清单仅包含项目 进程与端口 */"""
        payload = [{"ProcessId": 101, "CommandLine": '"C:\\Project With Spaces\\Game.uproject" -BBBMcpServicePort=8011 -SomeOtherSecret=secret-key'}]
        result = subprocess.CompletedProcess([], 0, json.dumps(payload).encode(), b"")
        with patch("MCP.mcp_project_host.subprocess.run", return_value=result):
            hosts = editor_inventory()
        self.assertEqual(hosts[0]["process_id"], 101)
        self.assertEqual(hosts[0]["public_port"], 8011)
        self.assertNotIn("secret-key", json.dumps(hosts))
        self.assertNotIn("CommandLine", json.dumps(hosts))



if __name__ == "__main__":
    unittest.main()
