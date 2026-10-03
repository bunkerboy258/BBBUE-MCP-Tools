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

这些类目前由 BBB 项目的 ABBB_EvacEditor 模块提供 部分实现直接引用 UBBBNexus 游戏类型 本次迁移没有修改原生模块或游戏运行时代码 不宣称将本仓库接入任意项目后全部动作都能直接执行

动画运动采样助手还直接引用 `/Script/ABBB_Evac.BBBRifleEquipment` 并依赖项目角色 蒙太奇 插槽和骨骼约定 这些运行时业务对象不属于编辑器原生库的符号诊断范围 不能将 `native_dependencies_ready` 为真理解为所有项目专用流程已经通过业务预检

`inspect_mcp_dependencies` 逐工具集返回 `required_native_classes` `missing_native_classes` `native_dependencies_ready` `registered` 和实际源码路径 原生类存在只说明符号可用 不保证任意资产符合业务约束 仍需遵守工具预检 类型 检出 编译与回读要求

缺失原生依赖时初始化明确警告 保留工具发现信息 使用者必须停止相关原生写入并报告缺失类 不静默跳过 不用任意 Python 执行绕过

## 默认资产维护工具

BBBAssetMaintenanceToolset 已纳入 BBBMcpBootstrap 默认注册集合 包含批量移动预览与执行 移动结果只读核验和精确维护入口 不再需要单独加载脚本 实际名称仍通过 list_toolsets 与 describe_toolset 发现 注册工具不代表授权调用其中的资产删除动作 当前宿主在正常启动或经过授权的统一重载后加载新代码 详细参数和边界见 BBBAssetMaintenanceMCP.md

## 第三方来源

GenOrca 动作来源为 `GenOrca/unreal-mcp` 修订 `f7986db239516aa4299ddc6f54d713253bd82631` 保留 Apache 2.0 许可证 `Scripts/MCP/ThirdParty/GenOrca/LICENSE.txt` 不上传缓存 不更改既有第三方注释
