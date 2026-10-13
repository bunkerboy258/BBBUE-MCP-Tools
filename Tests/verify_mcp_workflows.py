import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))
from MCP.mcp_call import McpSession


def main():
    """/** @return 短调用 结构化写入 注释排版与双客户端的真实验收 */"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--task-directory", required=True)
    args = parser.parse_args()
    project = Path(args.project_root).resolve()
    task = Path(args.task_directory).resolve()
    if not task.is_relative_to(project / "Saved/temp") or task.exists():
        raise ValueError("FRESH_TASK_DIRECTORY_REQUIRED")
    task.mkdir(parents=True)
    namespace = "/Game/_Project/McpWorkflows_" + uuid.uuid4().hex[:12]
    assets = [namespace + "/A", namespace + "/B", namespace + "/BP"]
    instances = [path + "." + path.rsplit("/", 1)[-1] for path in assets]
    measurements = []
    with McpSession(args.url, 60) as first, McpSession(args.url, 60) as second:
        (task / "recovery.json").write_text(json.dumps({"url": args.url, "keys": [first.client_key, second.client_key], "assets": assets}), encoding="utf-8")

        def call(session, tool, arguments, **options):
            """/** @param session\t客户端 @param tool\t工具 @param arguments\t结构化参数 @param options\t批次策略 @return 实际完成结果 */"""
            started = time.perf_counter()
            value = session.submit_batch([{"tool": tool, "arguments": arguments}], **options)
            rounds = 1
            if value["status"] in {"queued", "running"}:
                value = session.wait_batch(value["batch"], 180)
                rounds += 1
            measurements.append({"tool": tool, "seconds": time.perf_counter() - started, "rounds": rounds, "status": value["status"]})
            if value["status"] not in {"completed", "review"}:
                raise AssertionError(value)
            return value

        state = first.inspect_tasks()
        assert state["status"] == "ready" and state["host"]["verified"] and state["host"]["exclusive"], state
        assert state["dirty"] == state["queued"] == state["activities"] == 0 and not state["pie"], state
        simple = call(first, "editor.inspect_dirty_packages", {})
        assert simple["status"] == "completed" and measurements[-1]["rounds"] == 1, simple
        for path in assets[:2]:
            created = call(first, "editor.create_asset_with_factory", {"asset_path": path, "asset_class_path": "/Script/Engine.Material", "factory_class_path": "/Script/UnrealEd.MaterialFactoryNew"})
            assert created["status"] == "completed", created
        factory = call(first, "object.list_properties", {"instance": "/Script/UnrealEd.BlueprintFactory", "query": "ParentClass"})["results"][0]
        parent = next(iter(factory["properties"]))
        created = call(first, "editor.create_asset_with_factory", {"asset_path": assets[2], "asset_class_path": "/Script/Engine.Blueprint", "factory_class_path": "/Script/UnrealEd.BlueprintFactory", "factory_properties": {parent: "/Script/Engine.Actor"}})
        assert created["status"] == "completed", created
        fields = call(first, "object.list_properties", {"instance": instances[0], "query": "two_sided"})["results"][0]
        assert len(fields["properties"]) == 1, fields
        two_sided = next(iter(fields["properties"]))
        changed = call(first, "object.set_properties", {"instance": instances[0], "values": {two_sided: True}})
        assert changed["status"] == "completed" and changed["proof"]["saved"] == [assets[0]], changed
        assert first.inspect_tasks()["dirty"] == 0
        staged = call(first, "object.set_properties", {"instance": instances[0], "values": {two_sided: False}}, completion="review")
        assert staged["status"] == "review" and staged["code"] == "DIRTY_ASSETS", staged
        independent = call(second, "object.set_properties", {"instance": instances[1], "values": {two_sided: True}})
        assert independent["status"] == "completed", independent
        call(first, "asset.save_assets", {"asset_paths": [assets[0]]})
        assert first.inspect_tasks(staged["batch"])["status"] == "completed"
        graph = assets[2] + ".BP:EventGraph"
        before = call(first, "blueprint.inspect_blueprint_graph", {"graph_path": graph, "view": "logic"})["results"][0]
        default_comments = [{"nodeGuid": node["guid"], "expectedText": node["nodeComment"], "text": ""} for node in before["nodes"] if not node["isComment"] and node["nodeComment"]]
        if default_comments:
            call(first, "blueprint.edit_blueprint_graph_comments", {"graph_path": graph, "request": {"expectedSnapshot": before["snapshot"], "removeComments": [], "nodeComments": default_comments}, "dry_run": False})
            before = call(first, "blueprint.inspect_blueprint_graph", {"graph_path": graph, "view": "logic"})["results"][0]
        candidates = [node for node in before["nodes"] if not node["isComment"] and not node["nodeComment"]]
        assert candidates, before
        request = {"expectedSnapshot": before["snapshot"], "blocks": [{"title": "事件入口", "description": "接收事件并启动后续处理", "members": [node["guid"] for node in candidates]}], "nodeComments": [{"nodeGuid": candidates[0]["guid"], "text": "接收事件输入"}]}
        preview = call(first, "blueprint.annotate_blueprint_graph", {"graph_path": graph, "annotations": request})
        assert preview["status"] == "completed" and preview["results"][0]["dryRun"], preview
        annotated = call(first, "blueprint.annotate_blueprint_graph", {"graph_path": graph, "annotations": request, "dry_run": False})
        assert annotated["status"] == "completed" and annotated["proof"]["saved"] == [assets[2]], annotated
        after = call(first, "blueprint.inspect_blueprint_graph", {"graph_path": graph, "view": "logic"})["results"][0]
        assert before["logicSignature"] == after["logicSignature"], after
        assert any(node["isComment"] and node["nodeComment"] == "事件入口" for node in after["nodes"]), after
        for path in assets:
            relative = Path(path[len("/Game/"):] + ".uasset")
            source = project / "Content" / relative
            backup = task / "Originals" / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, backup)
            assert hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(backup.read_bytes()).digest()
        cleanup = {"asset_paths": assets, "backup_directory": str(task / "Originals")}
        call(first, "assets.delete_unreferenced_asset_packages", {**cleanup, "dry_run": True})
        deleted = call(first, "assets.delete_unreferenced_asset_packages", {**cleanup, "dry_run": False})
        assert deleted["status"] == "completed", deleted
        final = first.inspect_tasks()
        assert final["dirty"] == final["queued"] == final["activities"] == 0 and not final["pie"], final
        report = {"status": "PASS", "process_id": final["host"]["process_id"], "measurements": measurements, "temporary_asset_directory": str(project / "Content" / namespace[len("/Game/"):]), "task_directory": str(task)}
        (task / "acceptance.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({key: value for key, value in report.items() if key != "measurements"}, ensure_ascii=True))


if __name__ == "__main__":
    main()
