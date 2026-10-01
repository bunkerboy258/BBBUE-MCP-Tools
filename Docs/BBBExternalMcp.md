# GenOrca 工具移植

本项目移植了 `GenOrca/unreal-mcp` 在提交 `f7986db239516aa4299ddc6f54d713253bd82631` 中的部分 UE Python 动作。

来源仓库：<https://github.com/GenOrca/unreal-mcp>

许可证：Apache-2.0，完整许可证保存在 `Scripts/MCP/ThirdParty/GenOrca/LICENSE.txt`。

## 接入方式

移植代码位于 `Scripts/MCP/ThirdParty/GenOrca/`，由 `Scripts/BBBExternalToolset.py` 通过官方 Toolset Registry 注册。

项目不安装来源仓库的 `UnrealMCPython` 插件，不启动来源仓库的外部 MCP 服务，也不依赖其 C++ `MCPythonHelper`。

## 工具入口

官方 MCP 工具集：`Game.Scripts.BBBExternalToolset.BBBExternalToolset`

- `list_available_actions`
- `animation(action, params_json)`
- `control_rig(action, params_json)`
- `data_table(action, params_json)`
- `editor(action, params_json)`
- `game(action, params_json)`
- `layer(action, params_json)`
- `level(action, params_json)`
- `retarget(action, params_json)`
- `level_sequence(action, params_json)`
- `vision(action, params_json)`
- `util(action, params_json)`

每个领域的 `action` 使用来源仓库去掉 `ue_` 前缀后的函数名。`params_json` 是动作参数对象的 JSON 字符串；无参数动作传入 `{}`。使用 `list_available_actions` 获取当前白名单和来源版本。

## 已移植动作范围

- Control Rig：创建、查询、添加骨骼、添加 Null、添加 RigVM 节点、重编译
- Animation：AnimSequence 信息、Notify Track、Notify、Sync Marker、曲线、骨骼、Socket 查询与有限编辑
- DataTable：行列查询、JSON/CSV 导出、行存在性检查、行删除和 JSON 写入
- Editor：选择资产、打开/关闭资产编辑器、资产替换、Actor 合并和代理 Actor
- Game：GameMode、Enhanced Input Action、Enhanced Input Mapping
- Layer：查询、创建、删除、添加 Actor、移除 Actor、查询 Layer Actor
- Level：创建/加载关卡、关卡 Actor 查询、World Settings、关卡保存
- Retarget：创建 IK Rig、添加重定向链、查询、创建 IK Retargeter、自动映射、批量重定向
- Level Sequence：创建、查询、播放范围、绑定、变换轨道、关键帧、Sequencer、相机、动画轨道、绑定转换
- Vision：视口、指定姿态、Actor 截图
- Util：输出日志、CVar、视口相机、PIE 状态/控制、项目与枚举信息、日志详细程度

来源仓库中与当前官方工具集重叠的 Actor、资产、材质、蓝图、静态网格、纹理等动作未重复移植。依赖来源仓库专用 C++ helper 的 UMG、Behavior Tree、动画蓝图等动作也未启用。

本次不接入 GAS 领域，避免扩大当前项目的功能范围。
