import argparse
import json
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))
from MCP.mcp_call import McpSession


def operation(identity, **arguments):
    """/** @param tool\t工具身份 @param arguments\t参数 @return 有序操作 */"""
    return {"tool": identity, "arguments": arguments}


def main():
    """/** @return 两个原项目测试宿主与主宿主并行验收 */"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--map", default="/Engine/Maps/Entry")
    arguments = parser.parse_args()
    batches = []
    with McpSession(arguments.url, 60) as first, McpSession(arguments.url, 60) as second:
        initial = first.inspect_tasks(detail=True)
        assert initial["status"] == "ready" and initial["host"]["exclusive"], initial
        assert initial["queued"] == initial["activities"] == initial["dirty"] == 0 and not initial["pie"] and initial["tests"]["running"] == 0, initial
        identity = first.submit_batch([operation("runtime.inspect_mcp_dependencies", tool="blueprint.inspect_blueprint_graph"), operation("runtime.inspect_mcp_performance")])["batch"]
        checked = first.wait_batch(identity)
        assert checked["status"] == "completed", checked
        assert Path(checked["results"][0]["project_root"]).resolve() == Path(arguments.project_root).resolve()
        performance = checked["results"][1]
        first.control_task("close", identity)
        options = {"bSimulate": True, "playMode": "PlayMode_InViewPort", "warmupSeconds": 1.0}
        commands = [operation("app.StartPIE", options=options)]
        try:
            for session, label in ((first, "并行测试一"), (second, "并行测试二")):
                batch = session.submit_batch(commands, label, environment="test", test_options={"map": arguments.map})["batch"]
                batches.append((session, batch))
            deadline = time.monotonic() + 240
            views = []
            while time.monotonic() < deadline:
                views = [session.inspect_tasks(batch, True) for session, batch in batches]
                if all(value.get("host_state", {}).get("pie") for value in views):
                    break
                assert all(value["status"] in {"queued", "starting", "running", "completed"} for value in views), views
                time.sleep(0.25)
            assert len(views) == 2 and all(value.get("host_state", {}).get("pie") for value in views), views
            pids = [value["process_id"] for value in views]
            assert len(set(pids + [initial["host"]["process_id"]])) == 3, views
            current = first.inspect_tasks()
            assert current["tests"]["running"] == 2 and "edit" in current["available"] and not current["pie"], current
            edit = first.submit_batch([operation("runtime.configure_mcp_performance", profile=performance["profile"], max_fps=int(performance["max_fps"])), operation("runtime.inspect_mcp_performance")], "主宿主继续操作")["batch"]
            result = first.wait_batch(edit, 30)
            assert result["status"] == "completed", result
            assert result["results"][1]["process_id"] == initial["host"]["process_id"], result
            first.control_task("close", edit)
            for session, batch in batches:
                value = session.wait_batch(batch, 240)
                assert value["status"] == "completed" and value["input_stable"], value
                sample = session.submit_batch([operation("runtime.inspect_mcp_performance"), operation("app.IsPIERunning"), operation("app.StopPIE")],
                    environment="test", test_host=batch)["batch"]
                sampled = session.wait_batch(sample, 120)
                assert sampled["status"] == "completed" and sampled["input_stable"], sampled
                assert sampled["results"][0]["process_id"] in pids and sampled["results"][1] is True, sampled
                session.control_task("close", batch)
                session.control_task("close", sample)
            after = first.inspect_tasks()
            assert after["host"] == initial["host"] and after["tests"]["running"] == after["tests"]["queued"] == 0, after
            assert after["dirty"] == after["activities"] == after["queued"] == 0 and not after["pie"], after
            print(json.dumps({"status": "PASS", "editor_process_id": initial["host"]["process_id"], "test_process_ids": pids,
                "parallel_pie": 2, "original_project": True, "editor_progress": True}, ensure_ascii=False))
        finally:
            for session, batch in batches:
                try:
                    value = session.inspect_tasks(batch)
                    if value["status"] == "queued":
                        session.control_task("cancel", batch)
                    if value["status"] in {"completed", "rejected", "review", "cancelled"}:
                        session.control_task("close", batch)
                except Exception:
                    pass


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
