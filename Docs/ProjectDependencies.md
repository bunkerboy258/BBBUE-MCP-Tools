# 项目依赖

## 环境

- Windows 与 UE5.8 官方 ModelContextProtocol、ToolsetRegistry、PythonScriptPlugin、EditorToolset。
- 动画、Control Rig、Sequencer 操作使用对应官方工具与项目编辑器模块。
- 外部 Python 客户端使用 `requests`。
- 项目 `Content/Python/init_unreal.py` 加载本仓库 `Scripts/BBBMcpBootstrap.py`。

## 按目标核验

发现并描述目标工具后，提交：

```json
{"tool":"runtime.inspect_mcp_dependencies","arguments":{"tool":"blueprint.inspect_blueprint_graph"}}
```

结果包含 `process_id`、`project_root`、`required_native_classes`、`required_native_functions`、缺失符号和 `native_dependencies_ready`。

`BBBMcpCapabilities` 从目标函数与可达助手提取符号。工具执行前再次检查。原生符号齐全后，具体资产继续核验类型、独占、编译和实际回读。

项目专用装备、角色、枚举、插槽和骨骼由接入项目提供。跨项目接入时按目标重新核验这些业务约定。

## 第三方来源

GenOrca 动作来源：`GenOrca/unreal-mcp`，修订 `f7986db239516aa4299ddc6f54d713253bd82631`。保留 Apache 2.0 许可证：

`Scripts/MCP/ThirdParty/GenOrca/LICENSE.txt`。

实际公开动作通过 `find_tools` 搜索 `external.<领域>.<动作>`，通过 `describe_tool` 获取明确参数。
