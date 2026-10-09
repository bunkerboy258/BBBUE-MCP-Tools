import argparse
import json
from pathlib import Path
import re
import sys
import threading
import time
import uuid

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))
from MCP.mcp_call import McpSession
from MCP.mcp_result import decode_tool_result


def invoke(session, toolset, name, arguments=None):
    """
    /**
     * @param session	客户端
     * @param toolset	实际工具集
     * @param name	工具名称
     * @param arguments	业务参数
     * @return 官方工具业务结果
     */
    """
    return decode_tool_result(session.call_tool("call_tool", {
        "toolset_name": toolset, "tool_name": name, "arguments": arguments or {},
    }))


def tasks(session):
    """
    /**
     * @param session	客户端
     * @return 共享占用和实际活动
     */
    """
    return decode_tool_result(session.call_tool("inspect_editor_tasks", {}))


def blocked(operation, code):
    """
    /**
     * @param operation	应被拒绝的操作
     * @param code	预期保护代码
     * @return 确认拒绝且不盲重试
     */
    """
    try:
        operation()
    except RuntimeError as error:
        if code not in str(error):
            raise
        return
    raise AssertionError("操作未被保护拒绝 " + code)


def wait_pie(session, active):
    """
    /**
     * @param session	客户端
     * @param active	等待的实际 PIE 状态
     * @return 已确认的实际状态
     */
    """
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        state = tasks(session)
        activity = state["activity"]
        if activity["pie_active"] == active and bool(activity["worlds"]) == active:
            return state
        time.sleep(0.1)
    raise AssertionError("实际 PIE 状态未达到预期")


def main():
    """
    /**
     * @return 真实 UE 双客户端保护验收 不修改或保存资产
     */
    """
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--project-root", required=True)
    options = parser.parse_args()
    identifier = "task-protection-" + uuid.uuid4().hex
    owner = McpSession(options.url, 70)
    other = McpSession(options.url, 70)
    tokens = []
    checks = []
    second_task = None
    queue_thread = None
    queue_failure = []

    def definition(listing, label):
        """
        /**
         * @param listing	本次发现结果
         * @param label	工具集类名
         * @return 唯一完整注册名称
         */
        """
        matches = re.findall(r"(?m)^- ([^\r\n: ]+\." + label + r"(?:_0x[0-9a-fA-F]{8})?)(?=:|\s|$)", listing)
        assert len(matches) == 1, label
        return matches[0]

    try:
        initial = tasks(other)
        assert Path(initial["activity"]["project_root"]).resolve() == Path(options.project_root).resolve()
        assert not initial["tasks"] and not initial["host_changed"], "宿主仍有任务或身份保护 不开始验收"
        assert not initial["activity"]["pie_active"] and not initial["activity"]["activities"]
        assert not initial["activity"]["dirty_packages"], "现有未保存资产 不开始验收"
        listing = decode_tool_result(other.call_tool("list_toolsets", {}))
        assert "bbb_task" in listing
        controls = decode_tool_result(other.call_tool("describe_toolset", {"toolset_name": "bbb_task"}))
        assert len(controls["tools"]) == 8
        task_definition = definition(listing, "BBBMcpTaskToolset")
        schema = decode_tool_result(other.call_tool("describe_toolset", {"toolset_name": task_definition}))
        if isinstance(schema, str):
            schema = json.loads(schema)
        actual = schema["tools"][0]
        baseline = json.loads((Path(__file__).parent / "tool_schema_baseline.json").read_text(encoding="utf-8"))["BBBMcpTaskToolset"]["inspect_editor_activity"]
        assert actual["inputSchema"] == baseline["inputSchema"]
        assert actual["outputSchema"] == baseline["outputSchema"]
        checks.append("activity_schema")
        editor = definition(listing, "EditorAppToolset")
        runtime = definition(listing, "BBBMcpRuntimeToolset")

        first_task = owner.acquire_task(identifier + "-A", "真实双客户端阶段验收", "pie", 300)
        second_task = other.acquire_task(identifier + "-B", "持续登记和交接验收", "pie", 300)
        tokens.extend([first_task, second_task])
        first_b_stage = other.begin_write()
        second_task["write_token"] = first_b_stage["write_token"]
        performance = invoke(other, runtime, "inspect_mcp_performance")
        configured = invoke(other, runtime, "configure_mcp_performance", {
            "profile": performance["profile"], "max_fps": int(performance["configured_max_fps"]),
        })
        assert configured["matches_configured_settings"]
        other.end_write()
        checks.append("idle_registration_allows_other_editor")

        stage = owner.begin_write()
        first_task["write_token"] = stage["write_token"]
        options_pie = {"options": {"bSimulate": True, "playMode": "PlayMode_InViewPort", "warmupSeconds": 0.0}}
        invoke(owner, editor, "StartPIE", options_pie)
        playing = wait_pie(other, True)["activity"]
        for operation in [
            lambda: invoke(other, editor, "StopPIE"),
            lambda: invoke(other, editor, "StartPIE", options_pie),
        ]:
            blocked(operation, "EDITOR_WRITE_REQUIRED")
        checks.append("official_pie_routes")
        level = definition(listing, "BBBLevelEditingToolset")
        external = definition(listing, "BBBExternalToolset")
        blocked(lambda: invoke(other, level, "set_pie_paused", {"paused": True}), "EDITOR_WRITE_REQUIRED")
        blocked(lambda: invoke(other, external, "util", {"action": "stop_pie", "params_json": "{}"}), "EDITOR_WRITE_REQUIRED")
        blocked(lambda: other.begin_write(), "EDITOR_WRITE_BUSY")
        blocked(lambda: other.call_tool("shutdown_editor_host", {}), "HOST_BUSY")
        current = tasks(other)["activity"]
        assert current["worlds"] == playing["worlds"]
        assert current["pie_generation"] == playing["pie_generation"]
        assert current["paused_worlds"] == playing["paused_worlds"]
        invoke(other, editor, "IsPIERunning")
        checks.append("project_routes_and_read_queries")

        owner.close()
        blocked(lambda: other.begin_write(), "EDITOR_WRITE_BUSY")
        owner = McpSession(options.url, 70, first_task["task_token"], stage["write_token"])
        owner.renew_write()
        checks.append("reconnect_preserves_ownership")

        def wait_for_stage():
            """/** @return 本次第二个任务等待编辑阶段 不控制其他任务 */"""
            try:
                next_stage = other.begin_write(wait_seconds=60)
                second_task["write_token"] = next_stage["write_token"]
            except Exception as error:
                queue_failure.append(error)

        queue_thread = threading.Thread(target=wait_for_stage)
        queue_thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            queued = tasks(owner)
            if queued["write_queue"] == [second_task["task_id"]]:
                break
            time.sleep(0.05)
        assert queued["write_queue"] == [second_task["task_id"]]
        invoke(owner, editor, "StopPIE")
        wait_pie(owner, False)
        owner.end_write()
        queue_thread.join(10)
        assert not queue_thread.is_alive() and not queue_failure
        assert tasks(owner)["writer_task_id"] == second_task["task_id"]
        checks.append("queued_stage_handoff")

        invoke(other, editor, "StartPIE", options_pie)
        next_playing = wait_pie(owner, True)["activity"]
        owner.write_token = stage["write_token"]
        blocked(lambda: invoke(owner, editor, "StopPIE"), "EDITOR_WRITE_REQUIRED")
        owner.release_task()
        owner.task_token = first_task["task_token"]
        owner.write_token = stage["write_token"]
        blocked(lambda: invoke(owner, editor, "StopPIE"), "TASK_TOKEN_INVALID")
        assert tasks(other)["activity"]["worlds"] == next_playing["worlds"]
        invoke(other, editor, "StopPIE")
        wait_pie(other, False)
        other.end_write()
        other.release_task()
        checks.append("old_stage_and_task_tokens_cannot_control_next_pie")
        final = tasks(other)
        assert final["activity"]["dirty_packages"] == initial["activity"]["dirty_packages"]
        assert not final["tasks"] and not final["inflight"] and not final["activity"]["activities"]
        assert final["writer_task_id"] is None and not final["write_queue"]
        checks.append("no_asset_writes_or_leaked_tasks")
        print(json.dumps({"passed": checks, "process_id": final["activity"]["process_id"], "pie_generation": final["activity"]["pie_generation"], "dirty_packages": final["activity"]["dirty_packages"]}, ensure_ascii=False))
    finally:
        for record in tokens:
            if record is second_task and queue_thread is not None:
                queue_thread.join(5)
            with McpSession(options.url, 70, record["task_token"], record.get("write_token")) as cleanup:
                snapshot = tasks(cleanup)
                owned = next((item for item in snapshot["tasks"] if item["task_id"] == record["task_id"]), None)
                if owned is None:
                    continue
                try:
                    if owned["write"] is not None:
                        cleanup.renew_write(resume=True)
                        if snapshot["activity"]["pie_active"]:
                            invoke(cleanup, editor, "StopPIE")
                            wait_pie(cleanup, False)
                        cleanup.end_write()
                    cleanup.release_task()
                except RuntimeError:
                    print("验收登记或阶段仍需检查 请查询 inspect_editor_tasks 不停止其他任务", file=sys.stderr)
        owner.close()
        other.close()


if __name__ == "__main__":
    main()
