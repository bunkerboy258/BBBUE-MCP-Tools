import argparse
import json
from pathlib import Path
import secrets
import statistics
import sys
import threading
import time
from types import SimpleNamespace

sys.dont_write_bytecode = True
parser = argparse.ArgumentParser()
parser.add_argument("--scripts-root", type=Path, default=Path(__file__).resolve().parents[1] / "Scripts")
parser.add_argument("--profile", choices=("current", "candidate"), default="candidate")
parser.add_argument("--report", required=True)
args = parser.parse_args()
sys.path[:0] = [str(args.scripts_root), str(Path(__file__).resolve().parent)]
from MCP.mcp_call import McpSession
from MCP.mcp_result import McpBusinessError, McpExecutionError
from MCP.mcp_service import make_service_server
from MCP.mcp_task_gateway import TaskGateway, UnrealBackend
from test_mcp_task_gateway import fixtures, operation


def main():
    """/** @return 真实 HTTP 加隔离执行端的二十类任务往返与证据指标 */"""
    backend, catalog, unused = fixtures()
    unused.close()
    native = object.__new__(UnrealBackend)
    native.remap = False
    native.catalog = catalog
    original = backend.invoke
    large = [False]
    graph = ["fresh"]

    def execute(contract, arguments):
        """/** @param contract 契约 @param arguments 参数 @return 隔离业务事实 */"""
        if contract["name"] == "graph_read":
            return {"snapshot": graph[0], "nodes": [{"guid": "node-a"}]}
        if contract["name"] == "graph_edit":
            if arguments["annotations"]["expectedSnapshot"] != graph[0]:
                raise McpExecutionError("rejected", "GRAPH_SNAPSHOT_CHANGED", "图表已变化")
            backend.state["dirty_packages"].append("/Game/BP")
            return {"changed": True}
        if contract["name"] == "read" and large[0]:
            return {"data": "x" * 50000}
        return original(contract, arguments)

    def native_call(method, parameters):
        """/** @param method 原生入口 @param parameters 路由参数 @return 隔离原生执行结果 */"""
        contract = next(row for row in catalog.tools.values() if row["name"] == parameters["tool_name"])
        return execute(contract, parameters["arguments"])

    native._call = native_call
    backend.invoke = lambda contract, arguments: native.invoke(contract, arguments) if contract["id"].startswith("blueprint.") else execute(contract, arguments)
    for index, extra in enumerate(({}, {"enum": ["/Game/A"]}, {}, {}, {})):
        schema = {"type": "object", "properties": {"asset": {"type": "string", **extra}}, "required": ["asset"], "additionalProperties": False}
        if index == 3:
            schema["properties"]["settings"] = {"type": "object", "properties": {"enabled": {"type": "boolean"}}, "required": ["enabled"]}
        if index == 4:
            schema["properties"]["steps"] = {"type": "array", "items": {"type": "object", "properties": {"frames": {"type": "integer", "minimum": 1}}}}
        catalog.add({"id": "validation.case_" + str(index), "name": "write", "summary": "验证写入参数", "definition": "BBBValidation", "toolset": "test", "parameters": schema, "access": "write", "world": "editor", "scope": {"fields": ["asset"]}})
    for identity, name, access, properties in (
        ("blueprint.inspect_blueprint_graph", "graph_read", "read", {"graph_path": {"type": "string"}, "view": {"type": "string"}}),
        ("blueprint.annotate_blueprint_graph", "graph_edit", "write", {"graph_path": {"type": "string"}, "annotations": {"type": "object"}})):
        catalog.add({"id": identity, "name": name, "summary": "图表快照与注释", "definition": "BBBGraph", "toolset": "test", "access": access,
            "world": "editor", "scope": {"fields": ["graph_path"]}, "parameters": {"type": "object", "properties": properties}})
    gateway = TaskGateway(backend, catalog)
    server = make_service_server(SimpleNamespace(default="isolated", projects={"isolated": SimpleNamespace(protocol=gateway)}), 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = "http://127.0.0.1:" + str(server.server_address[1]) + "/mcp"
    rows = []
    trace = []
    save_calls = []
    finalizer = backend.finalize
    backend.finalize = lambda packages: (save_calls.append(list(packages)), finalizer(packages))[1]

    def measure(label, group, run):
        """/** @param label 场景 @param group 任务类别 @param run 完整任务 @return 已核验的任务记录 */"""
        first = len(trace)
        started = time.perf_counter()
        run()
        sample = trace[first:]
        rows.append({"task": label, "group": group, "seconds": time.perf_counter() - started,
            "requests": len(sample), "response_bytes": sum(row["bytes"] for row in sample),
            "describe_requests": sum(row["tool"] == "describe_tool" for row in sample), "verified": True})

    def submit(session, operations, **options):
        """/** @param session 客户端 @param operations 操作 @param options 配置 @return 完成或已核实失败的结果 */"""
        value = session.submit_batch(operations, **options)
        if value["status"] in {"queued", "running"}:
            value = session.wait_batch(value["batch"], 5)
        return value

    try:
        with McpSession(url, 5, client_key=secrets.token_urlsafe(32)) as first, McpSession(url, 5, client_key=secrets.token_urlsafe(32)) as second:
            for session in (first, second):
                if args.profile == "candidate":
                    session.manage_operator(task="隔离任务验收")
                post = session._post
                def traced(method, parameters, post=post):
                    """/** @param method 协议动作 @param parameters 参数 @param post 实际发送 @return 原始协议结果 */"""
                    value = post(method, parameters)
                    if method == "tools/call":
                        trace.append({"tool": parameters["name"], "bytes": len(json.dumps(value, ensure_ascii=False).encode())})
                    return value
                session._post = traced
            discovery = [("read", {"asset": "/Game/A"}), ("write", {"asset": "/Game/A"}), ("save_assets", {"asset_paths": ["/Game/A"]}), ("StartPIE", {}), ("StopPIE", {})]
            for name, arguments in discovery:
                def discover(name=name, arguments=arguments):
                    """/** @param name 目标 @param arguments 输入 @return 已发现并完成的业务操作 */"""
                    identity = first.find_tools("test." + name)[0]["id"]
                    first.describe_tool(identity)
                    assert submit(first, [{"tool": identity, "arguments": arguments}])["status"] == "completed"
                measure("发现并执行 " + name, "discovery", discover)
            bad = [{}, {"asset": "/Game/Wrong"}, {"asset": 42}, {"asset": "/Game/A", "settings": {"enabled": "yes"}}, {"asset": "/Game/A", "steps": [{"frames": 0}]}]
            fixed = [{"asset": "/Game/A"}, {"asset": "/Game/A"}, {"asset": "/Game/A"}, {"asset": "/Game/A", "settings": {"enabled": True}}, {"asset": "/Game/A", "steps": [{"frames": 1}]}]
            for index in range(5):
                def repair(index=index):
                    """/** @param index 错误类型 @return 依据字段证据修正后的结果 */"""
                    identity = "validation.case_" + str(index)
                    try:
                        first.submit_batch([{"tool": identity, "arguments": bad[index]}])
                        raise AssertionError("INVALID_ARGUMENT_DISPATCHED")
                    except McpBusinessError as error:
                        if args.profile == "candidate":
                            assert error.value["needs"][0]["schema"]
                        if args.profile == "current":
                            first.describe_tool(identity)
                    assert submit(first, [{"tool": identity, "arguments": fixed[index]}])["status"] == "completed"
                measure("补参类型 " + str(index), "repair", repair)
            measure("已知工具读取", "direct", lambda: submit(first, [operation("read")]))
            measure("有序编辑保存回读", "ordered", lambda: submit(first, [operation("write", asset="/Game/A"), operation("save_assets", asset_paths=["/Game/A"]), operation("read")]))
            measure("双客户端资产交接", "handoff", lambda: (submit(first, [operation("write", asset="/Game/A")]), submit(second, [operation("write", asset="/Game/A")])))
            unrelated = ["/Game/Other/P" + str(index) for index in range(191)]
            backend.state["dirty_packages"] = list(unrelated)
            def scoped():
                """/** @return 已核实独立资产继续且原有包保持原状态 */"""
                assert submit(first, [operation("write", asset="/Game/B")])["status"] == "completed"
                assert backend.state["dirty_packages"] == unrelated
            measure("191 个无关脏包", "scope", scoped)
            backend.state["dirty_packages"] = []
            def uncertain():
                """/** @return 结果不确定时保留执行边界与核实证据 */"""
                value = submit(first, [operation("unknown", asset="/Game/A")])
                if "execution" not in value:
                    value = first.inspect_tasks(value["batch"], detail=True)
                assert value["execution"] == "unknown"
                assert value["proof"].get("reconciled")
            measure("执行中断后核实", "recovery", uncertain)
            def snapshot():
                """/** @return 旧快照拒绝后按新图表重新核实并应用 */"""
                target = "/Game/BP.BP:EventGraph"
                value = submit(first, [{"tool": "blueprint.annotate_blueprint_graph", "arguments": {"graph_path": target, "annotations": {"expectedSnapshot": "old"}}}])
                assert value["status"] == "rejected"
                if args.profile == "candidate":
                    action = value["next"]
                    current = first.request(action["tool"], action["arguments"])
                    if current["status"] in {"queued", "running"}:
                        current = first.wait_batch(current["batch"], 5)
                if args.profile == "current":
                    current = submit(first, [{"tool": "blueprint.inspect_blueprint_graph", "arguments": {"graph_path": target, "view": "logic"}}])
                result = submit(first, [{"tool": "blueprint.annotate_blueprint_graph", "arguments": {"graph_path": target, "annotations": {"expectedSnapshot": current["results"][0]["snapshot"]}}}])
                assert result["status"] == "completed"
            measure("图表快照过期恢复", "snapshot", snapshot)
            for index in range(4):
                def activity():
                    """/** @return 长阶段期间紧凑等待并保留最终数据 */"""
                    large[0] = True
                    backend.entered.clear()
                    backend.release.clear()
                    def release():
                        """/** @return 隔离活动按实际完成边界释放 */"""
                        backend.entered.wait(2)
                        time.sleep(.05)
                        backend.release.set()
                    worker = threading.Thread(target=release)
                    worker.start()
                    try:
                        result = submit(first, [operation("read"), operation("long", asset="/Game/A"), operation("read")], await_seconds=0)
                        assert result["status"] == "completed"
                        assert len(result["results"][0]["data"]) == 50000
                    finally:
                        backend.release.set()
                        worker.join(2)
                        large[0] = False
                measure("活动等待与完整证据 " + str(index), "activity", activity)
            if args.profile == "candidate":
                first.manage_operator(action="finish")
                second.manage_operator(action="finish")
    finally:
        gateway.jobs.close()
        server.shutdown()
        server.server_close()
        thread.join(2)
    times = sorted(row["seconds"] for row in rows)
    report = {"mode": "real_http_with_isolated_unreal_backend", "profile": args.profile, "tasks": len(rows), "verified": sum(row["verified"] for row in rows),
        "requests": sum(row["requests"] for row in rows), "contract_requests": sum(row["describe_requests"] for row in rows),
        "avoidable_group_requests": sum(row["requests"] for row in rows if row["group"] in {"discovery", "repair"}),
        "response_bytes": sum(row["response_bytes"] for row in rows), "p50_seconds": statistics.median(times), "p95_seconds": times[int((len(times)-1)*.95)],
        "save_calls": len(save_calls), "rows": rows}
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "rows"}))
    assert report["tasks"] == report["verified"] == 20


if __name__ == "__main__":
    main()
