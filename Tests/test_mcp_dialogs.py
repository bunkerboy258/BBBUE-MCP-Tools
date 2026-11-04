import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))
from MCP import mcp_dialogs
from MCP.mcp_call import McpSession
from MCP.mcp_result import McpBusinessError
from MCP.mcp_task_gateway import public_tools


class DialogTests(unittest.TestCase):
    """/** 弹窗快照 选项与等待中断的静态契约检查 */"""

    def test_slate_snapshot_exposes_exact_options(self):
        snapshot = {"pid": 42, "open": True, "id": "dialog", "buttons": [{"id": "0", "label": "保存"}]}
        with patch.object(mcp_dialogs, "_exchange", return_value={"snapshot": snapshot}):
            state = mcp_dialogs.inspect_dialog({"process_id": 42})
        self.assertEqual(state["code"], "EDITOR_DIALOG_OPEN")
        self.assertEqual(state["dialog"]["buttons"][0]["label"], "保存")

    def test_stale_choice_keeps_the_dialog_untouched(self):
        state = {"dialog": {"id": "new", "buttons": [{"id": "0"}]}}
        with patch.object(mcp_dialogs, "inspect_dialog", return_value=state), patch.object(mcp_dialogs, "_exchange") as exchange:
            with self.assertRaises(McpBusinessError):
                mcp_dialogs.respond_dialog({}, "old", "0")
            exchange.assert_not_called()

    def test_choice_is_dispatched_with_request_identity(self):
        state = {"dialog": {"id": "current", "kind": "slate", "buttons": [{"id": "0"}]}}
        with patch.object(mcp_dialogs, "inspect_dialog", return_value=state), patch.object(mcp_dialogs, "_exchange", return_value={"status": "queued"}) as exchange:
            value = mcp_dialogs.respond_dialog({}, "current", "0", "request")
        self.assertEqual(value["status"], "queued")
        self.assertEqual(exchange.call_args.args[1]["request"], "request")

    def test_native_dialog_is_detected_during_bridge_failure(self):
        with patch.object(mcp_dialogs, "_exchange", side_effect=OSError("unavailable")), patch.object(mcp_dialogs, "native_dialogs", return_value=[{"id": "native", "kind": "native"}]):
            value = mcp_dialogs.inspect_dialog({"process_id": 42})
        self.assertEqual(value["dialog"]["id"], "native")

    def test_bridge_failure_retains_unknown_state(self):
        with patch.object(mcp_dialogs, "_exchange", side_effect=OSError("timeout")), patch.object(mcp_dialogs, "native_dialogs", return_value=[]):
            value = mcp_dialogs.inspect_dialog({"process_id": 42})
        self.assertEqual(value["status"], "unknown")

    def test_batch_wait_returns_the_dialog_for_a_decision(self):
        value = {"status": "blocked", "code": "EDITOR_DIALOG_OPEN"}
        session = object.__new__(McpSession)
        session.inspect_tasks = lambda **arguments: value
        self.assertIs(session.wait_batch("batch", 1), value)

    def test_modal_inspection_bypasses_gateway_queue(self):
        from MCP.mcp_service import ProjectRuntime
        runtime = object.__new__(ProjectRuntime)
        runtime.clients = SimpleNamespace(operators=Mock())
        runtime._inspect_dialog = Mock(return_value={"status": "clear"})
        self.assertEqual(runtime.control("owner", "inspect_dialog")["status"], "clear")
        runtime._inspect_dialog.assert_called_once_with(force=True)

    def test_dialog_response_checks_owner_or_level_zero(self):
        import threading
        from MCP.mcp_service import ProjectRuntime
        for owner, privileged in (("owner", False), ("other", True)):
            runtime = object.__new__(ProjectRuntime)
            pool = Mock()
            runtime.clients = SimpleNamespace(operators=pool)
            runtime.registry = Mock()
            runtime.registry.candidate.return_value = {"process_id": 42}
            runtime.project = "project"
            runtime.dialog_lock = threading.Lock()
            queue = SimpleNamespace(changed=threading.RLock(), jobs={"job": {"status": "running", "owner": owner}})
            runtime.gateway = SimpleNamespace(jobs=SimpleNamespace(editor=queue))
            with patch("MCP.mcp_service.RegistryGuard"), patch.object(mcp_dialogs, "respond_dialog", return_value={"status": "queued"}):
                self.assertEqual(runtime.control("owner", "respond_dialog", dialog="d", button="0")["status"], "queued")
            self.assertEqual(any(call.kwargs.get("level") == 0 for call in pool.require.call_args_list), privileged)

    def test_control_contract_contains_out_of_queue_actions(self):
        schema = next(row["inputSchema"] for row in public_tools() if row["name"] == "control_task")
        self.assertIn("inspect_dialog", schema["properties"]["action"]["enum"])
        self.assertIn("respond_dialog", schema["properties"]["action"]["enum"])
        self.assertIn("dialog", schema["properties"])
        self.assertIn("button", schema["properties"])


if __name__ == "__main__":
    unittest.main()
