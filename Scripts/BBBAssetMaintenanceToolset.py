import json

import unreal
import toolset_registry
from toolset_registry.registration import Registration


@unreal.uclass()
class BBBAssetMaintenanceToolset(unreal.ToolsetDefinition):
    """提供精确限定资产范围的维护工具"""

    @toolset_registry.tool_call
    @staticmethod
    def audit_asset_folder_move(source_folder: str, destination_folder: str) -> str:
        """只读检查目录迁移的目标冲突和目录外引用"""
        source = source_folder.rstrip("/")
        destination = destination_folder.rstrip("/")
        protected_segments = {"__ExternalActors__", "__ExternalObjects__"}
        if not source.startswith("/Game/") or not destination.startswith("/Game/"):
            raise RuntimeError("源目录和目标目录必须位于 /Game 下")
        if source == destination or source.startswith(destination + "/") or destination.startswith(source + "/"):
            raise RuntimeError("源目录与目标目录不能相同或互相嵌套")
        if protected_segments.intersection(source.split("/")) or protected_segments.intersection(destination.split("/")):
            raise RuntimeError("不允许迁移关卡外部 Actor 或对象目录")

        assets = unreal.EditorAssetLibrary.list_assets(source, recursive=True, include_folder=False)
        if not assets:
            raise RuntimeError("源目录没有可审计的资产: " + source)

        collisions = []
        external_assets = []
        referencer_counts = {}
        referencer_packages = set()
        for listed_path in assets:
            leaf = listed_path.rsplit("/", 1)[-1]
            package_path = listed_path.rsplit(".", 1)[0] if "." in leaf else listed_path
            relative_path = package_path[len(source):].lstrip("/")
            target_package = destination + "/" + relative_path
            target_name = target_package.rsplit("/", 1)[-1]
            target_object = target_package + "." + target_name
            if unreal.EditorAssetLibrary.does_asset_exist(target_object):
                collisions.append(target_object)

            referencers = unreal.EditorAssetLibrary.find_package_referencers_for_asset(package_path, False)
            external_referencers = []
            for referencer in referencers:
                referencer_leaf = referencer.rsplit("/", 1)[-1]
                referencer_package = referencer.rsplit(".", 1)[0] if "." in referencer_leaf else referencer
                if referencer_package == package_path or referencer_package.startswith(source + "/"):
                    continue
                external_referencers.append(referencer_package)
                referencer_packages.add(referencer_package)
                parts = referencer_package.split("/")
                root = "/".join(parts[:3]) if len(parts) > 2 else referencer_package
                referencer_counts[root] = referencer_counts.get(root, 0) + 1

            if external_referencers:
                external_assets.append({"asset": package_path, "referencers": external_referencers})

        report = {
            "source_folder": source,
            "destination_folder": destination,
            "asset_count": len(assets),
            "target_collision_count": len(collisions),
            "target_collision_examples": collisions[:30],
            "assets_with_external_referencers": len(external_assets),
            "external_referencer_package_count": len(referencer_packages),
            "external_referencer_counts_by_root": referencer_counts,
            "external_reference_examples": external_assets[:30],
            "read_only": True,
            "perforce_checkout_check_required": True
        }
        return json.dumps(report, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def move_assets_batch(moves_json: str, dry_run: bool = True) -> str:
        """预检并按给定顺序批量移动资产或目录"""
        from toolset_registry.helpers import require_editable

        try:
            moves = json.loads(moves_json)
        except Exception as error:
            raise RuntimeError("moves_json 不是有效 JSON: " + str(error))
        if not isinstance(moves, list) or not moves:
            raise RuntimeError("moves_json 必须是非空映射数组")
        if len(moves) > 1000:
            raise RuntimeError("单批最多允许 1000 项 请拆分批次")

        protected_segments = {"__ExternalActors__", "__ExternalObjects__"}
        validated = []
        source_paths = set()
        destination_paths = set()

        for index, entry in enumerate(moves):
            if not isinstance(entry, dict):
                raise RuntimeError("第 {} 项必须是对象".format(index))
            source_value = entry.get("source")
            destination_value = entry.get("destination")
            if not isinstance(source_value, str) or not isinstance(destination_value, str):
                raise RuntimeError("第 {} 项必须包含字符串 source 和 destination".format(index))
            source = source_value.rstrip("/")
            destination = destination_value.rstrip("/")
            if not source.startswith("/Game/") or not destination.startswith("/Game/"):
                raise RuntimeError("第 {} 项源和目标必须位于 /Game 下".format(index))
            if any(segment in {"", ".", ".."} for segment in source.split("/")[1:]):
                raise RuntimeError("第 {} 项源路径含无效片段".format(index))
            if any(segment in {"", ".", ".."} for segment in destination.split("/")[1:]):
                raise RuntimeError("第 {} 项目标路径含无效片段".format(index))
            if "." in source.rsplit("/", 1)[-1] or "." in destination.rsplit("/", 1)[-1]:
                raise RuntimeError("第 {} 项必须使用不带对象后缀的资产或目录路径".format(index))
            if protected_segments.intersection(source.split("/")) or protected_segments.intersection(destination.split("/")):
                raise RuntimeError("不允许移动关卡外部 Actor 或对象目录: " + source)
            if source == destination:
                raise RuntimeError("源路径和目标路径不能相同: " + source)
            if source in source_paths:
                raise RuntimeError("源路径重复: " + source)
            if destination in destination_paths:
                raise RuntimeError("目标路径重复: " + destination)

            is_directory = unreal.EditorAssetLibrary.does_directory_exist(source)
            is_asset = unreal.EditorAssetLibrary.does_asset_exist(source)
            if is_directory == is_asset:
                raise RuntimeError("源路径不存在或资产与目录类型不明确: " + source)
            if is_directory and (source.startswith(destination + "/") or destination.startswith(source + "/")):
                raise RuntimeError("目录不能移动到自身或其子目录: " + source)

            destination_parent = destination.rsplit("/", 1)[0]
            if not unreal.EditorAssetLibrary.does_directory_exist(destination_parent):
                raise RuntimeError("目标父目录不存在 请先创建目录: " + destination_parent)
            if unreal.EditorAssetLibrary.does_asset_exist(destination) or unreal.EditorAssetLibrary.does_directory_exist(destination):
                raise RuntimeError("目标路径已存在: " + destination)

            if is_directory:
                listed_assets = unreal.EditorAssetLibrary.list_assets(source, recursive=True, include_folder=False)
                package_paths = []
                for listed_path in listed_assets:
                    leaf = listed_path.rsplit("/", 1)[-1]
                    package_path = listed_path.rsplit(".", 1)[0] if "." in leaf else listed_path
                    package_paths.append(package_path)
            else:
                package_paths = [source]

            checked_packages = []
            for package_path in package_paths:
                asset_name = package_path.rsplit("/", 1)[-1]
                asset = unreal.EditorAssetLibrary.load_asset(package_path + "." + asset_name)
                if asset is None:
                    raise RuntimeError("无法加载待移动资产: " + package_path)
                require_editable(asset)
                checked_packages.append(package_path)

            source_paths.add(source)
            destination_paths.add(destination)
            validated.append({
                "source": source,
                "destination": destination,
                "is_directory": is_directory,
                "asset_count": len(checked_packages),
                "assets": checked_packages
            })

        for index, item in enumerate(validated):
            for other in validated[index + 1:]:
                if item["is_directory"] and other["source"].startswith(item["source"] + "/"):
                    raise RuntimeError("批次中不能同时移动父目录和其子项: " + item["source"])
                if other["is_directory"] and item["source"].startswith(other["source"] + "/"):
                    raise RuntimeError("批次中不能同时移动父目录和其子项: " + other["source"])
                if item["destination"] == other["source"] or other["destination"] == item["source"]:
                    raise RuntimeError("批次目标不能同时作为另一项的源路径")

        report = {
            "dry_run": dry_run,
            "requested_count": len(validated),
            "asset_count": sum(item["asset_count"] for item in validated),
            "moves": [
                {
                    "source": item["source"],
                    "destination": item["destination"],
                    "kind": "directory" if item["is_directory"] else "asset",
                    "asset_count": item["asset_count"]
                }
                for item in validated
            ]
        }
        if dry_run:
            report["executed"] = False
            return json.dumps(report, ensure_ascii=False)

        completed = []
        for item in validated:
            try:
                if item["is_directory"]:
                    succeeded = unreal.EditorAssetLibrary.rename_directory(item["source"], item["destination"])
                else:
                    succeeded = unreal.EditorAssetLibrary.rename_asset(item["source"], item["destination"])
                if not succeeded:
                    raise RuntimeError("UE 拒绝移动")
                completed.append({"source": item["source"], "destination": item["destination"]})
            except Exception as error:
                report["executed"] = True
                report["completed"] = completed
                report["failed"] = {"source": item["source"], "destination": item["destination"], "error": str(error)}
                report["partial"] = bool(completed)
                unreal.log_error("批量资产移动在 {} 失败 已完成 {} 项".format(item["source"], len(completed)))
                return json.dumps(report, ensure_ascii=False)

        report["executed"] = True
        report["completed"] = completed
        report["partial"] = False
        return json.dumps(report, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def resave_assets(asset_paths: list[str]) -> str:
        """校验精确资产路径与可编辑状态后强制重存指定资产"""
        from toolset_registry.helpers import require_editable

        if not asset_paths or len(set(asset_paths)) != len(asset_paths):
            raise RuntimeError("必须提供非空且不重复的精确资产路径")

        assets = []
        for path in asset_paths:
            if not path.startswith("/Game/") or "." in path:
                raise RuntimeError("必须提供 Game 下不带对象后缀的包路径")
            object_path = path + "." + path.rsplit("/", 1)[-1]
            asset = unreal.EditorAssetLibrary.load_asset(object_path)
            if asset is None:
                raise RuntimeError("无法加载精确资产: " + object_path)
            require_editable(asset)
            assets.append(asset)

        saved = []
        for asset in assets:
            asset_path = asset.get_path_name()
            if not unreal.EditorAssetLibrary.save_asset(asset_path, only_if_is_dirty=False):
                raise RuntimeError("资产重存失败 已成功重存列表: " + json.dumps(saved))
            saved.append(asset.get_outermost().get_name())

        return json.dumps({"resaved": saved}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def make_current_editor_level_explicit(expected_package: str) -> str:
        """校验活动层包名后显式同步编辑器放置目标层"""
        subsystem = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
        if subsystem.is_in_play_in_editor():
            raise RuntimeError("PIE 期间不允许切换放置层")
        level = subsystem.get_current_level()
        if level is None or level.get_outermost().get_name() != expected_package:
            raise RuntimeError("活动层不匹配 不切换也不载入其它关卡")
        if not subsystem.set_current_level_by_name(expected_package.rsplit("/", 1)[-1]):
            raise RuntimeError("设置已加载目标层失败")
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        return json.dumps({"level": level.get_path_name(), "world": world.get_path_name()}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def remove_unreferenced_loaded_redirectors(asset_paths: list[str]) -> str:
        """仅删除已加载且无包引用的重定向对象 拒绝删除普通资产"""
        from toolset_registry.helpers import require_editable

        if not asset_paths or len(set(asset_paths)) != len(asset_paths):
            raise RuntimeError("必须提供非空且不重复的精确资产路径")

        validated = []
        for path in asset_paths:
            if not path.startswith("/Game/") or "." in path:
                raise RuntimeError("必须提供 Game 下不带对象后缀的包路径")
            object_path = path + "." + path.rsplit("/", 1)[-1]
            candidates = []
            default_path = path + ".Default__" + path.rsplit("/", 1)[-1] + "_C"
            for candidate_path in (object_path, object_path + "_C", default_path):
                asset = unreal.find_object(None, candidate_path, follow_redirectors=False)
                if asset is None:
                    continue
                if asset.get_path_name() != candidate_path or asset.get_class().get_name() != "ObjectRedirector":
                    raise RuntimeError("拒绝删除非重定向对象: " + candidate_path)
                require_editable(asset)
                candidates.append(asset)
            if not candidates:
                raise RuntimeError("未找到精确的已加载重定向对象: " + object_path)
            references = unreal.EditorAssetLibrary.find_package_referencers_for_asset(path, True)
            if references:
                raise RuntimeError("重定向仍有引用: {} {}".format(path, references))
            validated.append((path, candidates))

        removed = []
        for path, candidates in validated:
            if not unreal.EditorAssetLibrary.delete_loaded_assets(candidates):
                raise RuntimeError("重定向删除失败 已删除列表: " + json.dumps(removed))
            unreal.log("已清理无引用重定向: " + path)
            removed.append(path)
        return json.dumps({"removed": removed}, ensure_ascii=False)

    @toolset_registry.tool_call
    @staticmethod
    def clean_unreferenced_redirectors_in_folder(folder_path: str, dry_run: bool = True) -> str:
        """检查或清理指定目录内无引用且可编辑的重定向器"""
        from toolset_registry.helpers import require_editable

        folder = folder_path.rstrip("/")
        if not folder.startswith("/Game/") or folder.count("/") < 2:
            raise RuntimeError("只允许处理 /Game 下的精确子目录")

        registry = unreal.AssetRegistryHelpers.get_asset_registry()
        redirector_class = unreal.load_class(None, "/Script/CoreUObject.ObjectRedirector")
        if redirector_class is None:
            raise RuntimeError("无法解析 UE ObjectRedirector 类型")
        asset_filter = unreal.ARFilter(
            package_paths=[folder],
            recursive_paths=True,
            class_paths=[redirector_class.get_class_path_name()],
            recursive_classes=True
        )
        redirector_data = registry.get_assets(asset_filter)
        redirectors = []
        referenced = []
        uneditable = []
        invalid_assets = []
        for asset_data in redirector_data:
            package_path = str(asset_data.package_name)
            if package_path != folder and not package_path.startswith(folder + "/"):
                continue

            asset_name = str(asset_data.asset_name)
            asset = unreal.EditorAssetLibrary.load_asset(package_path + "." + asset_name)
            if asset is None:
                invalid_assets.append(package_path)
                continue
            if asset.get_class().get_name() != "ObjectRedirector":
                invalid_assets.append(package_path)
                continue

            redirectors.append((package_path, asset))
            if unreal.EditorAssetLibrary.find_package_referencers_for_asset(package_path, True):
                referenced.append(package_path)
            try:
                require_editable(asset)
            except Exception:
                uneditable.append(package_path)

        report = {
            "folder": folder,
            "redirector_count": len(redirectors),
            "referenced_count": len(referenced),
            "referenced_examples": referenced[:30],
            "uneditable_count": len(uneditable),
            "uneditable_examples": uneditable[:30],
            "non_redirector_or_unloadable_count": len(invalid_assets),
            "non_redirector_or_unloadable_examples": invalid_assets[:30],
            "dry_run": dry_run
        }
        if dry_run:
            return json.dumps(report, ensure_ascii=False)

        if invalid_assets:
            raise RuntimeError("目录内存在非重定向器或无法加载资产 拒绝批量删除: " + json.dumps(report, ensure_ascii=False))
        if referenced:
            raise RuntimeError("仍有引用的重定向器必须先修复引用 拒绝删除: " + json.dumps(report, ensure_ascii=False))
        if uneditable:
            raise RuntimeError("存在不可编辑的重定向器 拒绝批量删除: " + json.dumps(report, ensure_ascii=False))
        if not redirectors:
            return json.dumps(report, ensure_ascii=False)

        assets = [asset for package_path, asset in redirectors]
        if not unreal.EditorAssetLibrary.delete_loaded_assets(assets):
            raise RuntimeError("批量删除重定向器失败 已完成状态需在内容浏览器复核")

        report["removed_count"] = len(redirectors)
        report["dry_run"] = False
        return json.dumps(report, ensure_ascii=False)


_registration = Registration([BBBAssetMaintenanceToolset])
_registration.unregister()
_registration.register()
