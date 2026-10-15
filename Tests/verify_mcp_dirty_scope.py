import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import uuid


sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Scripts"))

from MCP.mcp_call import McpSession


def operation(tool, **arguments):
    """
    /**
     * @param tool	公共工具身份
     * @param arguments	明确参数
     * @return 单项操作
     */
    """
    return {"tool": tool, "arguments": arguments}


def main():
    """/** @return 临时资产的真实双客户端范围与交接验收 */"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--task-directory", required=True)
    args = parser.parse_args()
    project = Path(args.project_root).resolve()
    task = Path(args.task_directory).resolve()
    assert task.is_relative_to(project / "Saved" / "temp") and not task.exists(), "FRESH_TASK_DIRECTORY_REQUIRED"
    task.mkdir(parents=True)
    root = "/Game/_Project/McpDirtyScope_" + uuid.uuid4().hex[:12]
    paths = [root + "/A", root + "/B"]
    batches = []
    with McpSession(args.url, 60) as first, McpSession(args.url, 60) as second:
        state = first.inspect_tasks()
        assert state["host"]["verified"] and state["host"]["exclusive"] and state["status"] == "ready", state
        assert state["dirty"] == 0 and state["queued"] == 0 and state["activities"] == 0 and not state["pie"] and state.get("tests", {}).get("running", 0) == 0, state
        (task / "recovery.json").write_text(json.dumps({"url": args.url, "keys": [first.client_key, second.client_key], "assets": paths, "batches": batches}), encoding="utf-8")

        def submit(session, operations, label):
            """
            /**
             * @param session	所属客户端
             * @param operations	明确操作
             * @param label	验收阶段
             * @return 可恢复批次身份
             */
            """
            batch = session.submit_batch(operations, label=label)["batch"]
            batches.append({"client": 0 if session is first else 1, "batch": batch})
            recovery = {"url": args.url, "keys": [first.client_key, second.client_key], "assets": paths, "batches": batches}
            (task / "recovery.json").write_text(json.dumps(recovery), encoding="utf-8")
            return batch

        def complete(session, batch):
            """
            /**
             * @param session	所属客户端
             * @param batch	本次批次
             * @return 实际完成结果
             */
            """
            result = session.wait_batch(batch, 120)
            assert result["status"] == "completed", result
            session.control_task("close", batch)
            return result

        fixture = submit(first, [operation("editor.create_asset_with_factory", asset_path=path, asset_class_path="/Script/Engine.Material", factory_class_path="/Script/UnrealEd.MaterialFactoryNew") for path in paths], "Dirty scope fixtures")
        complete(first, fixture)
        fields = complete(first, submit(first, [operation("object.list_properties", instance=paths[0] + ".A", query="two_sided")], "Dirty scope property"))["results"][0]["properties"]
        owner = submit(first, [operation("object.set_properties", instance=paths[0] + ".A", values={next(iter(fields)): True})], "Automatic scope owner")
        complete(first, owner)
        independent = submit(second, [operation("assets.normalize_material_auxiliary_data", asset_paths=[paths[1]], dry_run=False)], "Automatic scope independent material")
        complete(second, independent)
        same = submit(second, [operation("assets.resave_assets", asset_paths=[paths[0]])], "Automatic scope same asset successor")
        complete(second, same)
        assert first.inspect_tasks()["dirty"] == 0
        files = []
        for path in paths:
            relative = Path(path[len("/Game/"):] + ".uasset")
            source = project / "Content" / relative
            assert source.is_file() and not source.is_symlink(), str(source)
            backup = task / "Originals" / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, backup)
            assert hashlib.sha256(source.read_bytes()).digest() == hashlib.sha256(backup.read_bytes()).digest()
            files.append(source)
        cleanup_arguments = {"asset_paths": paths, "backup_directory": str(task / "Originals")}
        complete(first, submit(first, [operation("assets.delete_unreferenced_asset_packages", **cleanup_arguments, dry_run=True)], "Dirty scope cleanup inspection"))
        complete(first, submit(first, [operation("assets.delete_unreferenced_asset_packages", **cleanup_arguments, dry_run=False)], "Dirty scope native cleanup"))
        assert all(not path.exists() for path in files), files
        final = first.inspect_tasks()
        assert final["dirty"] == 0 and final["queued"] == 0 and final["activities"] == 0 and not final["pie"], final
        print(json.dumps({"status": "PASS", "process_id": final["host"]["process_id"], "clients": 2, "independent_material": True, "same_asset_progressed": True, "automatic_save": True, "dirty_packages": 0, "asset_directory": str(files[0].parent), "task_directory": str(task)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
