# 项目原生依赖边界

本仓库独立管理 Python 工具 客户端 启动器 常驻探针和第三方动作 实际操作由官方 UE5.8 MCP 插件与编辑器宿主执行 不包含 UE 引擎源码或游戏原生 C++

## 必需环境

- Windows 与 UE5.8 官方 ModelContextProtocol ToolsetRegistry PythonScriptPlugin EditorToolset
- 动画与控制器领域需要对应官方 AnimationAssistantToolset ControlRig Sequencer 工具
- 外部 Python 辅助客户端需要 `requests` 编辑器内部工具不依赖它
- 接入项目的 `Content/Python/init_unreal.py` 加载本仓库 `Scripts/BBBMcpBootstrap.py`

## 原生类

| 工具集 | 部分动作所需原生类 |
| --- | --- |
| BBBAnimationMigrationToolset | BBBBlueprintEditorLibrary BBBPIEInputEditorLibrary |
| BBBGenericEditorToolset | BBBBlueprintEditorLibrary BBBPIEWindowEditorLibrary BBBAssetThumbnailEditorLibrary BBBNiagaraEditorLibrary |
| BBBBlueprintGraphToolset | BBBBlueprintEditorLibrary |
| BBBControlRigAuthoringToolset | BBBBlueprintEditorLibrary |
| BBBLevelEditingToolset | BBBBlueprintEditorLibrary |
| BBBRigidPartToolset | BBBBlueprintEditorLibrary |
| BBBAssetMaintenanceToolset | BBBAssetRepairEditorLibrary BBBBlueprintEditorLibrary |
| BBBAnimationPreviewToolset | BBBBlueprintEditorLibrary BBBAnimationGraphEditorLibrary BBBMassValidationLibrary |
| BBBAnimationGraphToolset | BBBAnimationGraphEditorLibrary BBBBlueprintEditorLibrary |

以上是编辑器原生库的领域概览。实际符号清单由 `BBBMcpCapabilities` 从公开工具和可达辅助函数源码提取，`inspect_mcp_dependencies` 逐工具报告 `required_native_functions`、`missing_native_functions` 与类状态。类存在而所需函数缺失时不可执行，不能把 DLL 已加载视为接口版本匹配。工具中的项目枚举与游戏类型同样检查类存在；动态加载的业务类路径仍由业务预检负责。

第三方白名单动作按自身静态引用单独检查，不因一个动作不可用禁用整个领域。`list_available_actions` 的 `actions` 包含全部动作状态与实际参数，`domains` 仅包含可执行动作；旧 `MCPythonHelper` 不可用的动作明确拒绝，不为历史接口添加兼容原生类。

这些类由接入项目的编辑器模块提供 部分实现依赖该项目的游戏类型. 具体类 函数和源码位置以本机 `inspect_mcp_dependencies` 报告为准. 将本仓库接入另一项目后需要重新核对接口和业务依赖.

动画运动采样助手还依赖接入项目的装备类型 角色 蒙太奇 插槽和骨骼约定. 这些运行时业务对象不属于编辑器原生库的符号诊断范围. `native_dependencies_ready` 为真不代表项目专用流程已经通过业务预检.

`inspect_mcp_dependencies` 逐工具集返回 `required_native_classes` `missing_native_classes` `native_dependencies_ready` `registered` 和实际源码路径 原生类存在只说明符号可用 不保证任意资产符合业务约束 仍需遵守工具预检 类型 检出 编译与回读要求

缺失原生依赖时初始化明确警告 保留工具发现信息 使用者必须停止相关原生写入并报告缺失类 不静默跳过 不用任意 Python 执行绕过

## 默认资产维护工具

BBBAssetMaintenanceToolset 已纳入 BBBMcpBootstrap 默认注册集合 包含批量移动预览与执行 移动结果只读核验和精确维护入口 不再需要单独加载脚本 实际名称仍通过 list_toolsets 与 describe_toolset 发现 注册工具不代表授权调用其中的资产删除动作 当前宿主在正常启动或经过授权的统一重载后加载新代码 详细参数和边界见 BBBAssetMaintenanceMCP.md

## 第三方来源

GenOrca 动作来源为 `GenOrca/unreal-mcp` 修订 `f7986db239516aa4299ddc6f54d713253bd82631` 保留 Apache 2.0 许可证 `Scripts/MCP/ThirdParty/GenOrca/LICENSE.txt` 不上传缓存 不更改既有第三方注释
