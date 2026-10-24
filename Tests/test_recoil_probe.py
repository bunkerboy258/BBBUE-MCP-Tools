import importlib.util
from pathlib import Path
import unittest
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock, patch


SPEC = importlib.util.spec_from_file_location("recoil_probe", Path(__file__).resolve().parents[1] / "Scripts/BBBRecoilProbeTools.py")
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)


class RecoilProbeTests(unittest.TestCase):
    """/** 屏幕统计不受分辨率变化影响且异常样本不能伪装成正常数据 */"""

    def data(self, scale=1):
        """/** @param scale 像素缩放 @return 包含基线 连射及回落的确定性样本 */"""
        columns = ["frame", "time", "valid", "onScreen", "shot", "viewWidth", "viewHeight", "fov", "screenX", "screenY", "impactX", "impactY", "impactZ"]
        rows = []
        for frame in range(100):
            time = frame / 60
            shot = min(max((frame - 30) // 6 + 1, 0), 5)
            up = 30 if 30 <= frame < 65 else 0
            rows.append([frame, time, 1, 1, shot, 1920 * scale, 1080 * scale, 70,
                         960 * scale, (540 - up) * scale, 0, 0, 0])
        return {"columns": columns, "samples": rows}

    def test_resolution_independence_and_recovery(self):
        """/** @return 分辨率不改变归一化偏移且停火后能识别回稳 */"""
        a = PROBE.summarize(self.data())
        b = PROBE.summarize(self.data(2))
        self.assertEqual(a["shotCount"], 5)
        self.assertEqual(a["peakOffsetHeight"], b["peakOffsetHeight"])
        self.assertAlmostEqual(a["peakOffsetHeight"][1], 30 / 1080)
        self.assertIsNotNone(a["settleSeconds"])
        self.assertFalse(a["warnings"])

    def test_invalid_projection_and_missing_frames(self):
        """/** @return 无效投影不进入峰值且帧间隙明确报告 */"""
        data = self.data()
        data["samples"][40][2] = 0
        data["samples"][40][9] = -99999
        del data["samples"][41]
        summary = PROBE.summarize(data)
        self.assertEqual(summary["validCount"], 98)
        self.assertEqual(summary["frameGaps"], 1)
        self.assertLess(summary["peakOffsetHeight"][1], 0.03)
        self.assertTrue(summary["warnings"])

    def test_empty_and_multiple_shots_are_explicit(self):
        """/** @return 空采样不生成伪造轨迹且同帧多枪明确报警 */"""
        self.assertIsNone(PROBE.summarize({})["sampleFPS"])
        data = self.data()
        data["samples"][31][4] = 4
        self.assertTrue(any("同帧多枪" in value for value in PROBE.summarize(data)["warnings"]))

    def test_native_rejection_and_pagination(self):
        """/** @return 运行中采样被拒绝时不重新登记且分页不丢失总数 */"""
        library = Mock()
        registry = Mock()
        modules = {"unreal": SimpleNamespace(BBBRecoilProbeEditorLibrary=library),
                   "BBBMcpCapabilities": SimpleNamespace(register_activity=registry)}
        with patch.dict(sys.modules, modules):
            library.start_recoil_probe.return_value = json.dumps({"state": "rejected", "error": "已运行"})
            with self.assertRaisesRegex(RuntimeError, "已运行"):
                PROBE.sample_runtime("start", 3, 0, 0)
            registry.assert_not_called()
            library.read_recoil_probe.return_value = json.dumps({"state": "finished", **self.data()})
            result = PROBE.sample_runtime("status", 3, 10, 20)
            self.assertEqual(result["totalSamples"], 100)
            self.assertEqual(len(result["samples"]), 20)
            self.assertEqual(result["nextOffset"], 30)
            self.assertEqual(result["summary"]["shotCount"], 5)

    def test_activity_queries_do_not_serialize_samples(self):
        """/** @return 活动轮询只查询原生状态 不反复复制全量轨迹 */"""
        library = Mock()
        registry = Mock()
        library.start_recoil_probe.return_value = json.dumps({"state": "running", **self.data()})
        library.read_recoil_probe.return_value = json.dumps({"state": "running"})
        with patch.dict(sys.modules, {"unreal": SimpleNamespace(BBBRecoilProbeEditorLibrary=library),
                                    "BBBMcpCapabilities": SimpleNamespace(register_activity=registry)}):
            PROBE.sample_runtime("start", 3, 0, 0)
            registry.call_args.args[1]()
            library.read_recoil_probe.assert_called_once_with(False)

    def test_contract_dependencies_and_read_only_status(self):
        """/** @return 公共入口能发现原生依赖且状态查询不占用编辑权限 */"""
        with patch.object(sys, "path", [str(Path(__file__).resolve().parents[1] / "Scripts"), *sys.path]):
            import BBBMcpCapabilities as capabilities
            contract = capabilities.tool_contract("BBBAnimationMigrationToolset", "sample_recoil_runtime", {"type": "object"})
            self.assertEqual(capabilities.resolve_access(contract, {"action": "status"}), ("read", "any"))
            self.assertEqual(capabilities.native_requirements("BBBAnimationMigrationToolset", "sample_recoil_runtime")["BBBRecoilProbeEditorLibrary"],
                             {"start_recoil_probe", "read_recoil_probe", "stop_recoil_probe"})


if __name__ == "__main__":
    unittest.main()
