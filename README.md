# BBBUE-MCP-Tools

## 当前清理核验结果

用户已手动执行迁移清理脚本 实际复核清单内三十六个旧文件与二十个相关缓存均已删除 新仓库对应文件完整 源码检查通过 当前没有运行中的 UE 编辑器 所以清理后的实时 MCP 验证尚未进行

下文清理尚未完成的说明保留为迁移初期历史记录 当前状态以本节及 Docs/MigrationManifest.json 为准 不执行 Perforce Revert Submit 或 Get Latest

基于官方 UE5.8 ModelContextProtocol 与 ToolsetRegistry 的编辑器工具集

本仓库是 Python 工具和文档的唯一源码位置 不启动旧 socket 服务 不复制工具到游戏项目 不修改 UE 引擎安装目录

迁移清理尚未完成 当前编辑器和项目加载入口已经只使用本仓库 但清单内旧项目文件尚在磁盘上 删除命令被执行策略拒绝 后续不得将这些旧文件当作源码继续更新 实际清单与状态见 [迁移清单](Docs/MigrationManifest.json) 清理前仍需核对哈希和并行改动 不执行 Perforce Revert 或 Submit

## 架构与依赖

AI 客户端通过官方 MCP 入口发现和调用工具 编辑器在游戏线程处理工具 项目加载入口只导入本仓库的 BBBMcpBootstrap

通用工具与项目专用动作同时保留 部分动作依赖接入项目提供的 BBB 原生编辑器类 详见 [项目依赖](Docs/ProjectDependencies.md) 本仓库不包含这些游戏 C++ 不保证在任意项目中全部动作可用

编辑器需要官方 PythonScriptPlugin ModelContextProtocol ToolsetRegistry EditorToolset 动画领域还需要官方动画工具插件 外部命令行辅助客户端需要安装 requirements.txt 编辑器工具无需 requests

## 接入与启动

仓库本机位置为 E:\UE5.8\BBBUE-MCP-Tools 项目的 Content/Python/init_unreal.py 只将本仓库 Scripts 加入 Python 路径 导入 BBBMcpBootstrap 并调用 register_mcp_toolsets 注册前必须检查路径 缺失仓库时明确报错

项目已经有编辑器时不另开宿主 有未保存资产或并行任务时不擅自重启

```powershell
& E:\UE5.8\BBBUE-MCP-Tools\Scripts\MCP\Start-UE58OfficialMcpEditor.ps1 -ProjectPath E:\BBB_Evac\ABBB_Evac.uproject -EnginePath E:\UE5.8\UE_5.8 -PerformanceProfile Speed
```

启动器要求显式提供项目与引擎安装根目录 默认隐藏 NullRHI 单宿主 必须完成协议握手与性能回读才报告就绪 需要渲染时显式增加 EnableRendering 任务结束后关闭自己创建的隐藏宿主并确认退出

## AI 新会话入口

先确认当前宿主属于目标项目 然后调用 list_toolsets 在实际返回中找唯一类名为 BBBMcpRuntimeToolset 或 BBBMcpRuntimeToolset_0x 加八位十六进制哈希的工具集 使用完整返回名称 描述后调用 get_mcp_usage_guide 与 inspect_mcp_dependencies

指南返回真实文档路径 项目路径 当前档位与精确路由 依赖诊断返回实际源码位置 原生类缺失和注册状态 只描述需要的领域 不盲读全部工具 不缓存资产状态

完整入口与调用边界见 [MCP 指南](Docs/UnrealMcpCanonical.md) 的独立仓库接入章节 历史文档中的项目路径和注册名称不是迁移后的调用依据

现有工具无法解决时 先核对参数并尝试组合已有工具 确认能力缺口后优先拓展职责相符的旧工具 必要时新增最小通用工具 实现 注册 文档 指南与实际调用验证同步完成 不用临时 py 脚本绕过

## 性能与更新

Speed 默认 120 FPS 正常优先级 Balanced 为 60 FPS Economy 为 30 FPS GamingBackground 为 15 FPS 低于正常优先级 用户要求后台玩游戏时显式选择 GamingBackground 可覆盖为 10 FPS 不自动提速

帧率上限只约束持续调度 编译 导入 烘焙 截图仍可产生资源峰值 不保证固定功耗 游戏帧数或显存下降 配置后回读 matches_configured_settings 先协调设置漂移再恢复

BBBMcpBootstrap.reload_mcp_toolsets 使用官方重载生命周期 保留实际性能设置 不重启编辑器 更新后必须重新发现并实际调用 不直接重载仍注册的工具类

写入先预检并独占签出 传输或批量失败不自动重放 已完成写入不回滚 批量调用不是事务

## 验证与版本控制

```powershell
python -B Tests/test_repository.py
python -B Tests/verify_live_mcp.py --project-root E:\BBB_Evac
& Tests/Test-Startup.ps1
```

验证工具清单 参数结构 新会话指南 依赖位置 热更新 性能回读与单宿主约束 不使用游戏资产写入冒充冒烟验证

专用远程为 https://github.com/bunkerboy258/BBBUE-MCP-Tools.git 的 main 保留原有历史 正常快进推送 不强推 游戏项目接入改动仅本地提交 其他任务仍保持 UBBBNexus 默认推送规则

GenOrca 动作的来源修订与许可证见 ProjectDependencies.md 不上传缓存 日志 资产 构建产物 密钥或引擎源码

