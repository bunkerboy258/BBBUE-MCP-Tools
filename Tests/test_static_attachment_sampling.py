import ast
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


class StaticAttachmentSamplingTests(unittest.TestCase):
    """/** 验证静态附件只读原生渲染面采样的范围与失败边界 */"""

    def fixture(self, project):
        path = Path(__file__).resolve().parents[1] / 'Scripts/BBBGripAuthoringToolset.py'
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        names = {'sample_static_attachment_surface', '_asset'}
        functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name in names]
        for function in functions:
            function.decorator_list = []

        class StaticMesh:
            def __init__(self):
                self.saved_asset_state = {'build_settings': 'original', 'materials': ['original']}

        mesh = StaticMesh()
        dynamic = object()
        state = SimpleNamespace(mesh=mesh, outcome='success', copied=dynamic,
                                vertex_gaps=False, triangle_gaps=False)
        positions = [SimpleNamespace(to_tuple=lambda: (1.0, 2.0, 3.0))]
        triangles = [SimpleNamespace(to_tuple=lambda: (0, 0, 0))]

        def copy_mesh(*args):
            return state.copied, state.outcome

        copy = Mock(side_effect=copy_mesh)
        engine = SimpleNamespace(
            StaticMesh=StaticMesh, load_asset=Mock(return_value=mesh),
            Paths=SimpleNamespace(project_dir=lambda: project), DynamicMesh=lambda: dynamic,
            GeometryScriptCopyMeshFromAssetOptions=SimpleNamespace,
            GeometryScriptMeshReadLOD=lambda **kwargs: SimpleNamespace(**kwargs),
            GeometryScriptLODType=SimpleNamespace(RENDER_DATA='render_data'),
            GeometryScriptOutcomePins=SimpleNamespace(SUCCESS='success'),
            GeometryScript_AssetUtils=SimpleNamespace(copy_mesh_from_static_mesh_v2=copy),
            GeometryScript_MeshQueries=SimpleNamespace(
                get_all_vertex_positions=lambda *args: (None, positions, state.vertex_gaps),
                get_all_triangle_indices=lambda *args: (None, triangles, state.triangle_gaps)),
            GeometryScript_List=SimpleNamespace(convert_vector_list_to_array=lambda value: value,
                                                convert_triangle_list_to_array=lambda value: value),
        )
        namespace = {'unreal': engine, 'Path': Path, 're': re, 'os': os, 'json': json}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), 'exec'), namespace)
        state.engine = engine
        state.copy = copy
        return lambda output='Task/Attachment': namespace['sample_static_attachment_surface'](
            '/Game/Items/StaticAttachment', output), state

    def test_output_scope_rejects_absolute_parent_and_extra_segments_before_native_copy(self):
        with TemporaryDirectory() as project:
            sample, state = self.fixture(project)
            for output in ['../Attachment', 'Task/../Attachment', '/Task/Attachment',
                           'C:/Task/Attachment', 'E:\\Outside\\Attachment', 'Task/Child/Attachment',
                           'Task/Attachment.json', 'Task', 'Task\\Attachment']:
                with self.subTest(output=output), self.assertRaisesRegex(RuntimeError, 'OUTPUT_TASK_REQUIRED'):
                    sample(output)
            state.engine.load_asset.assert_not_called()
            state.copy.assert_not_called()
            self.assertFalse((Path(project) / 'Saved').exists())

    def test_native_copy_failure_or_wrong_return_object_does_not_write_report(self):
        for outcome, wrong_copy in [('failure', False), ('success', True)]:
            with self.subTest(outcome=outcome, wrong_copy=wrong_copy), TemporaryDirectory() as project:
                sample, state = self.fixture(project)
                state.outcome = outcome
                if wrong_copy:
                    state.copied = object()
                with self.assertRaisesRegex(RuntimeError, 'RENDER_LOD0_COPY_FAILED'):
                    sample()
                self.assertFalse((Path(project) / 'Saved').exists())

    def test_native_vertex_or_triangle_index_gaps_reject_report(self):
        for attribute in ['vertex_gaps', 'triangle_gaps']:
            with self.subTest(attribute=attribute), TemporaryDirectory() as project:
                sample, state = self.fixture(project)
                setattr(state, attribute, True)
                with self.assertRaisesRegex(RuntimeError, 'TOPOLOGY_HAS_GAPS'):
                    sample()
                self.assertFalse((Path(project) / 'Saved').exists())

    def test_success_records_real_render_lod_zero_and_preserves_source_mesh(self):
        with TemporaryDirectory() as project:
            sample, state = self.fixture(project)
            original = json.dumps(state.mesh.saved_asset_state, sort_keys=True)
            result = json.loads(sample())
            report = json.loads(Path(result['report']).read_text(encoding='utf-8'))
            self.assertEqual(Path(result['report']), Path(project).resolve() / 'Saved/temp/Task/Attachment.json')
            self.assertEqual(result['source'], 'RenderDataLOD0')
            self.assertTrue(result['readOnly'])
            self.assertEqual(report['source'], 'RenderDataLOD0')
            self.assertEqual(report['lod'], 0)
            self.assertEqual(report['space'], 'mesh_component_centimeters')
            self.assertEqual(report['vertices'][0]['position'], [1.0, 2.0, 3.0])
            self.assertEqual(report['triangles'][0]['vertices'], [0, 0, 0])
            self.assertEqual(report['localRotationOverrides'], {})
            self.assertEqual(json.dumps(state.mesh.saved_asset_state, sort_keys=True), original)
            arguments = state.copy.call_args.args
            self.assertIs(arguments[0], state.mesh)
            self.assertEqual(arguments[3].lod_type, 'render_data')
            self.assertEqual(arguments[3].lod_index, 0)


if __name__ == '__main__':
    unittest.main()
