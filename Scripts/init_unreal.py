import sys

import unreal


_previous_bytecode = sys.dont_write_bytecode
sys.dont_write_bytecode = True
try:
    from BBBMcpEditorStartup import start_editor_mcp

    start_editor_mcp()
except Exception as error:
    unreal.log_error("[BBBMcpEditorStartup]自动接入失败 {}".format(error))
    raise
finally:
    sys.dont_write_bytecode = _previous_bytecode
    del _previous_bytecode
