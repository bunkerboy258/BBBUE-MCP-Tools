import pathlib
import re
import unittest


class AudioLauncherOverrideTests(unittest.TestCase):
    def test_background_volume_uses_engine_section_syntax(self):
        source = (pathlib.Path(__file__).resolve().parents[1] / "Scripts/MCP/Start-UE58OfficialMcpEditor.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("$arguments += '-ini:Engine:[Audio]:UnfocusedVolumeMultiplier=1.0'", source)
        self.assertNotIn("$arguments += '-ini:Engine:Audio:", source)

    def test_reuse_requires_the_valid_section_override(self):
        source = (pathlib.Path(__file__).resolve().parents[1] / "Scripts/MCP/Start-UE58OfficialMcpEditor.ps1").read_text(encoding="utf-8-sig")
        match = re.search(r"\$EnableAudio -and \$commandLine -notmatch '([^']+)'", source)
        self.assertIsNotNone(match)
        pattern = match.group(1)
        self.assertRegex("-ini:Engine:[Audio]:UnfocusedVolumeMultiplier=1.0 ", pattern)
        self.assertNotRegex("-ini:Engine:Audio:UnfocusedVolumeMultiplier=1.0 ", pattern)

    def test_editor_background_gate_is_enabled_only_by_process_argument(self):
        source = (pathlib.Path(__file__).resolve().parents[1] / "Scripts/MCP/Start-UE58OfficialMcpEditor.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("$arguments += '-ini:EditorPerProjectUserSettings:[/Script/UnrealEd.LevelEditorMiscSettings]:bAllowBackgroundAudio=True'", source)
        self.assertIn("$EnableAudio -and $commandLine -notmatch '(?i)-ini:EditorPerProjectUserSettings:", source)


if __name__ == "__main__":
    unittest.main()
