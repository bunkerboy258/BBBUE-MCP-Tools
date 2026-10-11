import argparse
import json
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))

from MCP.mcp_call import McpSession
from MCP.mcp_result import McpBusinessError


def operation(identity, **arguments):
    """/** @param tool 稳定 ID @param arguments 参数 @return 单项操作 */"""
    return {"tool": identity, "arguments": arguments}


def complete(session, batch):
    """/** @param session 所属连接 @param batch 编号 @return 完成结果 */"""
    value = session.wait_batch(batch, 120)
    assert value["status"] == "completed", value
    session.control_task("close", batch)
    return value["results"]


def wait_queued(session, batch, code):
    """/** @param session 所属连接 @param batch 编号 @param code 等待原因 @return 等待证据 */"""
    deadline = time.monotonic() + 30
    revision = None
    while time.monotonic() < deadline:
        value = session.inspect_tasks(batch, after_revision=revision, wait_seconds=1)
        assert value["status"] == "queued", value
        if value.get("code") == code:
            return value
        revision = value["revision"]
    raise AssertionError("QUEUE_REASON_TIMEOUT")


def main():
    """/** @return 同一原项目双客户端流水线与 PIE 归属验收 */"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--run-pie", action="store_true", required=True)
    args = parser.parse_args()
    with McpSession(args.url, 60) as first, McpSession(args.url, 60) as second:
        state = first.inspect_tasks(detail=True)
        assert state["status"] == "ready" and state["host"]["exclusive"], state
        assert state["queued"] == state["dirty"] == state["activities"] == 0 and not state["pie"] and "occupant" not in state, state
        assert len(json.dumps(first.inspect_tasks(), separators=(",", ":")).encode()) <= 1024
        original = complete(first, first.submit_batch([operation("runtime.inspect_mcp_dependencies", tool="blueprint.inspect_blueprint_graph"), operation("runtime.inspect_mcp_performance")], "身份核验")["batch"])
        assert Path(original[0]["project_root"]).resolve() == Path(args.project_root).resolve()
        options = {"bSimulate": True, "playMode": "PlayMode_InViewPort", "warmupSeconds": 0.0}
        first.describe_tool("app.StartPIE")
        second.describe_tool("app.StopPIE")
        started = first.submit_batch([operation("app.StartPIE", options=options)], "客户端一 PIE")["batch"]
        try:
            assert first.wait_batch(started, 120)["status"] == "completed"
            foreign_stop = second.submit_batch([operation("app.StopPIE")], "客户端二等待")["batch"]
            wait_queued(second, foreign_stop, "PIE_OWNED")
            try:
                first.control_task("cancel", foreign_stop)
            except McpBusinessError as error:
                assert error.value["code"] == "BATCH_OWNERSHIP", error.value
            else:
                raise AssertionError("FOREIGN_CONTROL_ACCEPTED")
            complete(second, second.submit_batch([operation("runtime.inspect_mcp_performance"), operation("app.IsPIERunning")], "客户端二只读")["batch"])
            assert second.inspect_tasks()["pie_owner"] == "other"
            second.control_task("cancel", foreign_stop)
            second.control_task("close", foreign_stop)
            successor = second.submit_batch([operation("app.StartPIE", options=options)], "客户端二 PIE")["batch"]
            wait_queued(second, successor, "PIE_OWNED")
            complete(first, first.submit_batch([operation("app.StopPIE")], "客户端一释放 PIE")["batch"])
            first.control_task("close", started)
            assert second.wait_batch(successor, 120)["status"] == "completed"
            complete(first, first.submit_batch([operation("runtime.inspect_mcp_performance")], "客户端一只读")["batch"])
            assert first.inspect_tasks()["pie_owner"] == "other"
            complete(second, second.submit_batch([operation("app.StopPIE")], "客户端二释放 PIE")["batch"])
            second.control_task("close", successor)
            after = first.inspect_tasks(detail=True)
            assert after["host"] == state["host"], after
            assert after["dirty"] == after["queued"] == after["activities"] == 0 and not after["pie"], after
            print(json.dumps({"status": "PASS", "process_id": after["host"]["process_id"], "clients": 2, "pie_runs": 2, "reads_during_pie": True, "queued_handoff": True, "dirty_packages": 0}, ensure_ascii=False))
        finally:
            current = first.inspect_tasks()
            owner = first if current.get("pie_owner") == "mine" else second
            if current["pie"]:
                complete(owner, owner.submit_batch([operation("app.StopPIE")], "验收 PIE 收尾")["batch"])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
