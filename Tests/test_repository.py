import ast
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]


class RepositoryTests(unittest.TestCase):
    """
    /**
     * 不启动编辑器的源码与注册生命周期回归检查
     */
    """

    def test_source_and_public_tools(self):
        """/** @return 源码语法与原公共工具保留断言 */"""
        baseline = json.loads((ROOT / "Tests/tool_schema_baseline.json").read_text(encoding="utf-8"))
        for source in (ROOT / "Scripts").rglob("*.py"):
            ast.parse(source.read_text(encoding="utf-8-sig"), filename=str(source))
        for name, tools in baseline.items():
            tree = ast.parse((ROOT / "Scripts" / (name + ".py")).read_text(encoding="utf-8-sig"))
            definition = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
            current = {node.name for node in definition.body if isinstance(node, ast.FunctionDef)}
            self.assertTrue(set(tools).issubset(current), name)
        self.assertTrue((ROOT / "Scripts/BBBAssetMaintenanceToolset.py").is_file())
        self.assertTrue((ROOT / "Scripts/MCP/ThirdParty/GenOrca/LICENSE.txt").is_file())
        self.assertTrue((ROOT / "Scripts/ProbeScripts/probe_locomotion_sync_runtime.py").is_file())

    def test_bootstrap_metadata_and_reload(self):
        """/** @return 包名 原生依赖与性能状态保留断言 */"""
        existing = dict(sys.modules)
        previous_reload = importlib.reload
        registered = set()
        events = []
        fake_unreal = types.ModuleType("unreal")

        class Registry:
            """/** 注册表隔离替身 */"""

            @staticmethod
            def is_available():
                """/** @return 可用状态 */"""
                return True

            @staticmethod
            def is_toolset_registered(name):
                """
                /**
                 * @param name	注册名称
                 * @return 已注册状态
                 */
                """
                return name in registered

            @staticmethod
            def is_toolset_class_registered(definition):
                """
                /**
                 * @param definition	工具类
                 * @return 已注册状态
                 */
                """
                return definition.name in registered

            @staticmethod
            def register_toolset_class(definition):
                """
                /**
                 * @param definition	工具类
                 * @return 无返回值
                 */
                """
                registered.add(definition.name)

            @staticmethod
            def unregister_toolset_class(definition):
                """
                /**
                 * @param definition	工具类
                 * @return 无返回值
                 */
                """
                registered.discard(definition.name)

        fake_unreal.ToolsetRegistry = Registry
        fake_unreal.Paths = types.SimpleNamespace(project_dir=lambda: str(ROOT / "TestProject"))
        fake_unreal.SystemLibrary = types.SimpleNamespace(get_engine_version=lambda: "5.8-test")
        fake_unreal.log = events.append
        fake_unreal.log_warning = events.append
        fake_unreal.log_error = events.append
        sys.modules["unreal"] = fake_unreal
        try:
            spec = importlib.util.spec_from_file_location("BBBMcpBootstrap", ROOT / "Scripts/BBBMcpBootstrap.py")
            bootstrap = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(bootstrap)
            for name in bootstrap._TOOLSET_MODULES:
                module = types.ModuleType(name)
                module.__file__ = str(ROOT / "Scripts" / (name + ".py"))
                definition = types.SimpleNamespace(name="Game.Scripts." + name + "." + name)
                definition.get_name = lambda name=name: name
                path = "/Game/Scripts/" + name + "_PY." + name
                definition.static_class = lambda path=path: types.SimpleNamespace(get_path_name=lambda: path)
                setattr(module, name, definition)
                sys.modules[name] = module
            runtime = sys.modules["BBBMcpRuntimeToolset"]
            fake_unreal.Class = object
            fake_unreal.ObjectIterator = lambda value: [getattr(sys.modules[name], name) for name in bootstrap._TOOLSET_MODULES]
            bootstrap.importlib.reload = lambda module: events.append(module.__name__)
            runtime._snapshot = lambda: {"profile": "GamingBackground", "configured_max_fps": 10}
            sys.modules["BBBExternalToolset"]._DOMAIN_MODULES = {}
            report = bootstrap.register_mcp_toolsets()
            self.assertEqual(len(registered), 7)
            self.assertEqual(runtime._active_profile, "GamingBackground")
            self.assertEqual(runtime._configured_max_fps, 10)
            self.assertTrue(report["modules"]["BBBBlueprintGraphToolset"]["missing_native_classes"])
            self.assertEqual(bootstrap.get_toolset_name("BBBMcpRuntimeToolset"), "Game.Scripts.BBBMcpRuntimeToolset.BBBMcpRuntimeToolset")
            bootstrap.reload_mcp_toolsets()
            self.assertEqual(len(registered), 7)
            self.assertEqual(runtime._configured_max_fps, 10)
            self.assertEqual(sum(value in bootstrap._TOOLSET_MODULES for value in events), 7)
            runtime_definition = runtime.BBBMcpRuntimeToolset
            runtime_definition.static_class = lambda: types.SimpleNamespace(get_path_name=lambda: "/Engine/PythonTypes.BBBMcpRuntimeToolset_0x1234ABCD")
            self.assertEqual(bootstrap.get_toolset_name("BBBMcpRuntimeToolset"), "PythonTypes.BBBMcpRuntimeToolset_0x1234ABCD")
            Registry.is_available = staticmethod(lambda: False)
            with self.assertRaisesRegex(RuntimeError, "注册表不可用"):
                bootstrap.register_mcp_toolsets()
        finally:
            importlib.reload = previous_reload
            for name in set(sys.modules) - set(existing):
                del sys.modules[name]
            sys.modules.update(existing)


if __name__ == "__main__":
    unittest.main()
