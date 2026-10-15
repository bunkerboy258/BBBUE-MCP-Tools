import importlib.util
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Scripts'))


class StartupTests(unittest.TestCase):
    """/** UE 登记独立于常驻服务的生命周期 */"""

    def setUp(self):
        self.native = types.SimpleNamespace(inspect_private_backend=Mock(return_value=json.dumps({
            'process_id': os.getpid(), 'project_file': str(ROOT/'Fixture/Game.uproject'),
            'editor_path': str(ROOT/'Fixture/UnrealEditor.exe')})),
            start_private_backend=Mock(return_value=json.dumps({'success':True,'owned':True,'running':True,
                'backend_url':'http://127.0.0.1:18000/bbb-mcp-'+'a'*32})))
        self.unreal = types.SimpleNamespace(BBBMcpEditorStartupLibrary=self.native,
            SystemLibrary=types.SimpleNamespace(get_command_line=lambda:''),log=Mock(),log_warning=Mock(),
            register_slate_post_tick_callback=Mock(return_value=1))
        with patch.dict(sys.modules, {'unreal':self.unreal}):
            spec=importlib.util.spec_from_file_location('startup_under_test',ROOT/'Scripts/BBBMcpEditorStartup.py')
            self.module=importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)
        for item in [patch.object(self.module,'publish_host',return_value={'process_id':os.getpid(),'project_file':str(ROOT/'Fixture/Game.uproject')}),
                     patch.object(self.module,'_port_available',return_value=18000),
                     patch.object(self.module.shutil,'which',return_value='C:/Python/python.exe'),
                     patch.object(self.module.threading,'Thread'),patch.object(Path,'is_file',return_value=True),
                     patch.dict(os.environ,{'BBB_MCP_HOST_ROLE':'editor'})]:
            item.start()
            self.addCleanup(item.stop)

    def test_manual_open_publishes_private_backend_and_starts_heartbeat(self):
        state=self.module.start_editor_mcp()
        self.assertEqual(state['status'],'starting')
        self.module.publish_host.assert_called_once()
        self.module.threading.Thread.assert_called_once()
        self.assertNotIn('process',self.module._startup)
        self.module.start_editor_mcp()
        self.assertEqual(self.native.start_private_backend.call_count,1)

    def test_service_port_and_external_python_are_explicit(self):
        self.unreal.SystemLibrary.get_command_line=lambda:'-BBBMcpServicePort=18100 -BBBMcpServicePython="C:/Python Runtime/python.exe"'
        result=self.module.start_editor_mcp()
        self.assertIn(':18100/',result['endpoint'])
        self.assertEqual(self.module._startup['python'],str(Path('C:/Python Runtime/python.exe').resolve()))

    def test_test_process_and_commandlet_have_owned_startup(self):
        for command in ['-BBBMcpHostRole=Test','-run=ResavePackages']:
            self.unreal.SystemLibrary.get_command_line=lambda command=command:command
            self.assertEqual(self.module.start_editor_mcp(),{'status':'skipped'})
        self.native.start_private_backend.assert_not_called()

    def test_native_rejection_preserves_editor_and_reports_cause(self):
        self.native.start_private_backend.return_value=json.dumps({'success':False,'error':'BACKEND_START_FAILED'})
        with self.assertRaisesRegex(RuntimeError,'BACKEND_START_FAILED'):
            self.module.start_editor_mcp()
        self.assertIsNone(self.module._startup)

    def test_reconnecting_state_is_logged_once_per_change(self):
        self.module.start_editor_mcp()
        self.module._startup.update(status='reconnecting',error='SERVICE_START_FAILED')
        self.module._report_state(0)
        self.module._report_state(0)
        self.unreal.log_warning.assert_called_once()


if __name__=='__main__':
    unittest.main()
