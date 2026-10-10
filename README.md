# BBBUE-MCP-Tools

让 AI 通过标准 MCP 接口读取和操作 Unreal Engine 5.8 编辑器的工具仓库.

你可以用它查看蓝图逻辑 整理节点和注释 编辑资产 检查动画 以及运行编辑器内的游戏测试.
AI 发出工具请求后 实际工作由 Unreal Editor 执行.

## 能做什么

| 你想完成的事情 | 从哪里开始 |
| --- | --- |
| 看懂蓝图的节点 引脚和连接 | [蓝图逻辑与注释](Docs/BBBBlueprintAnnotationsMCP.md) |
| 让蓝图按逻辑顺序排列 | [蓝图排版](Docs/BBBBlueprintLayoutMCP.md) |
| 添加区块说明和节点说明 | [蓝图逻辑与注释](Docs/BBBBlueprintAnnotationsMCP.md) |
| 读取属性 检查 PIE 中的角色和对象 | [通用编辑器工具](Docs/BBBGenericEditorMCP.md) |
| 编辑和检查动画蓝图 | [动画图表工具](Docs/BBBAnimationGraphMCP.md) |
| 检查动画姿势和运行效果 | [动画预览](Docs/BBBAnimationPreviewMCP.md) |
| 创建或检查 Control Rig | [Control Rig 工具](Docs/BBBControlRigAuthoringMCP.md) |
| 移动资产和检查维护结果 | [资产维护](Docs/BBBAssetMaintenanceMCP.md) |
| 检查受击表现 | [受击工具](Docs/BBBHitReactionMCP.md) |

部分工具需要接入项目提供原生编辑器接口.
把仓库放到另一款游戏项目里不代表所有工具都能使用.
调用前通过依赖检查确认目标工具需要的接口是否齐全.
详细说明见 [项目依赖](Docs/ProjectDependencies.md).

## 开始前准备什么

本仓库当前面向 Windows 和 UE5.8.

需要准备:

- 已安装的 UE5.8 和要操作的 `.uproject` 文件.
- 编辑器中的官方插件 `PythonScriptPlugin` `ModelContextProtocol` `ToolsetRegistry` 和 `EditorToolset`.
- 动画等专项操作所需的官方插件及项目原生接口.
- 可在 PowerShell 中运行的 Python.
- 项目中的 Python 加载入口.

在资源管理器中打开仓库根目录 然后在该目录打开 PowerShell.
安装外部客户端和网关的依赖:

```powershell
python -m pip install -r requirements.txt
```

这里的 Python 是电脑上运行客户端和网关的 Python.
UE 编辑器内部使用自己的 Python 环境.

### 项目如何加载工具

项目的 `Content/Python/init_unreal.py` 将本仓库的 `Scripts` 目录加入 Python 搜索路径.
随后导入 `BBBMcpBootstrap` 并调用 `register_mcp_toolsets()`.

工具源码统一放在本仓库.
项目加载入口只负责找到源码和注册工具.

项目加载入口使用的仓库位置由接入项目配置.
换电脑或移动仓库后先核对该配置.

## 第一步: 启动或复用编辑器

在仓库根目录的 PowerShell 中执行以下命令.
按提示输入本机的实际位置和为该宿主选择的端口:

```powershell
$projectFile = (Resolve-Path -LiteralPath (Read-Host '输入项目 .uproject 文件的完整路径')).Path
$engineRoot = (Resolve-Path -LiteralPath (Read-Host '输入 UE5.8 安装根目录')).Path
$publicPort = [int](Read-Host '输入为该宿主选择的本机 MCP 端口')
$hostInfo = & .\Scripts\MCP\Start-UE58OfficialMcpEditor.ps1 -ProjectPath $projectFile -EnginePath $engineRoot -Port $publicPort
$hostInfo = $hostInfo | ConvertFrom-Json
$env:BBB_MCP_URL = $hostInfo.Endpoint
```

默认行为:

- 使用隐藏窗口的 UE 编辑器.
- 使用 `-NullRHI` 关闭图形渲染 适合资产和逻辑操作.
- 使用 `-Multiprocess` 减少启动时与构建锁的争用.
- 从空 Entry 地图启动 测试任务取得占用后再加载需要的地图.
- 检查同项目现有编辑器并优先复用符合条件的宿主.
- 核对连接 项目 进程 性能设置和任务保护后返回 `Ready`.

启动器返回的 `Endpoint` 是客户端应连接的本机地址.
上面的命令将它写入当前 PowerShell 的 `BBB_MCP_URL` 环境变量.
随后在这个 PowerShell 中运行命令行客户端会使用该地址.
AI 客户端也要将自己的连接配置设为同一个 `Endpoint`.
端口相同不代表宿主相同 还要核对目标项目和进程身份.

需要截图或其他渲染操作时在启动命令后增加 `-EnableRendering`.
启动器仍使用隐藏窗口.
已有宿主的渲染模式或性能设置不匹配时先协调所属任务.

### 如何选择性能档位

| 参数值 | 默认帧率上限 | 适合的情况 |
| --- | --- | --- |
| `Speed` | 120 FPS | 希望工具请求响应较快 |
| `Balanced` | 60 FPS | 日常使用 |
| `Economy` | 30 FPS | 降低持续资源占用 |
| `GamingBackground` | 15 FPS | 后台执行任务时还要玩游戏 |

用 `-MaxFPS` 可以明确指定帧率上限.
低帧率也会增加工具请求的等待时间.
导入 编译和截图仍可能短时占用较多资源.

## 第二步: 找到工具再调用

AI 客户端按这个顺序操作:

1. 调用 `list_toolsets` 查看当前实际注册的工具集.
2. 找到 `BBBMcpRuntimeToolset` 对应的完整名称.
3. 调用 `describe_toolset` 查看它的工具名和参数.
4. 调用 `get_mcp_usage_guide` 获取当前项目的使用指南.
5. 调用 `inspect_mcp_dependencies` 检查工具和原生接口.
6. 根据任务选择目标工具集 查看参数后调用具体工具.

工具集名称可能包含 `_0x` 和八位十六进制字符.
应使用发现结果中的完整名称.
更新工具注册后需要重新发现.

### 最简单的连接检查

在完成启动配置的同一个 PowerShell 中执行:

```powershell
python -B .\Scripts\MCP\mcp_call.py call list_toolsets
```

正常情况下会打印工具集列表.
这能确认连接和发现接口可用.
具体工具是否可用还要检查依赖和参数.

命令行客户端可以通过环境变量 `BBB_MCP_URL` 指定其他明确授权的连接地址.

## 第三步: 取得任务占用后执行写操作

多个 AI 可以连接同一个宿主.
多个任务可以同时登记 分析期间不独占写权限.
需要连续编辑时单独申请编辑阶段 同一时刻只有一个阶段取得写权限.
其他任务可以执行经过审核的只读查询.

典型流程:

```text
查询任务状态
    -> 登记任务并分析
    -> 申请编辑阶段
    -> 执行操作并回读实际结果
    -> 结束本任务的 PIE 和采样
    -> 结束编辑阶段并让出写权限
    -> 继续分析或释放本任务登记
    -> 全部任务结束后请求关闭宿主
```

通过 `list_toolsets` 查找 `bbb_task` 并描述它.
任务接口为:

| 工具 | 什么时候用 |
| --- | --- |
| `inspect_editor_tasks` | 查看当前操作 等待原因 可执行工作 或等待状态变化 |
| `acquire_editor_task` | 开始任务前登记 不自动取得写权限 |
| `renew_editor_task` | 续期任务登记 |
| `begin_editor_write` | 持续排队 按顺序领取编辑阶段 |
| `cancel_editor_write` | 取消本任务的排队申请 |
| `renew_editor_write` | 续期或凭原阶段凭证显式恢复 |
| `end_editor_write` | 完成编辑阶段后让出写权限 |
| `release_editor_task` | 结束已经让出写权限的任务登记 |
| `shutdown_editor_host` | 全部任务和活动结束后请求退出 |

申请成功后得到 `task_token`.
它是本任务的登记凭证.
申请编辑阶段后另得到 `write_token`.
后续写操作必须携带两份凭证.
不要把凭证写入仓库或交给其他任务.

Python 客户端 `McpSession` 提供任务登记和编辑阶段的方法.
命令行客户端通过 `BBB_MCP_TASK_TOKEN` 和 `BBB_MCP_WRITE_TOKEN` 环境变量携带凭证.
具体参数和示例见 [共享宿主任务保护](Docs/BBBMcpTaskProtection.md).

**当前验收状态:** 共享任务保护已通过隔离测试与真实 UE 三客户端 PIE 验收. 已核实持续排队 批次交接 共享查询 重连保护和旧凭证失效 验收结束时任务 队列 后台活动与脏资产清零.

等待结果为 `status=queued` 时 原排队顺序继续有效.
AI 可继续查询和准备参数 通过 `inspect_editor_tasks` 的状态版本等待变化.
返回的 `summary.caller` 告诉当前任务能做什么以及下一步调用.
阶段用途 当前工具和实际耗时帮助其他任务理解占用.
凭证有效期表示权限有效时间 完成时间以实际结果为准.
已经准备好的一组请求可通过 `McpSession.run_write_batch` 完成排队 执行和交接.

### 共享宿主时要记住什么

- 关闭 HTTP 连接不会释放任务占用.
- 阶段超时且没有实际活动 未保存内容或不确定结果时安全回收写权限.
- PIE 采样或请求尚未结束时保留归属 不自动停止或转让.
- 查询发现其他任务正在编辑时按顺序等待.
- 只读任务可登记为 `read` 使宿主在任务期间保持运行.
- `editor` 和 `pie` 登记均可并存 写权限按编辑阶段独占.
- 写操作和异步活动实际完成后结束阶段 分析期间让出写权限.
- 任意 Python 脚本和控制台执行在共享入口被拒绝.
- 批量调用使用 `call_many` 每项操作都单独检查权限.
- 现有 PCG 异步生成缺少活动状态探针 共享入口拒绝 `generate=True`.

任务保护作用于经过网关的请求.
手动操作 UE 或从操作系统终止进程仍可能打断任务.

## 第四步: 检查结果并安全结束

### 资产操作

需要写入资产时先完成目标检查和版本控制要求.
受控资产通常需要 Perforce 独占签出.
工具是否编译或保存由该工具的说明决定.

例如蓝图注释和排版工具默认支持 `dry_run` 预览.
预览表示计算修改方案.
实际写入后仍要回读逻辑和布局结果 并按任务要求明确编译和保存.

请求成功表示该请求已被处理.
PIE 启动 世界退出和后台采样是否完成要以实际状态为准.

### 调用失败

检查返回中的协议错误 工具 `isError` 以及业务结果 `success=false` 或非空 `error`.
Python 调用方可使用 `MCP.mcp_result.decode_tool_result` 解析返回包装并检查业务失败.

写请求超时或连接中断时先查询实际状态.
不要直接重发.
批量请求中已经完成的操作不会因为后面失败而自动撤销.

### 结束任务

结束自己的 PIE 和采样并处理本阶段未保存内容后结束编辑阶段.
继续分析时保留任务登记 整个任务结束后释放登记.
其他任务还在使用宿主时保留宿主.

全部任务 请求和后台活动结束后才能请求退出.
有未保存资产时先由所属任务处理.
收到 `shutdown_requested` 后还要核实对应编辑器 PID 和网关进程已经退出.

## 常见问题

| 现象 | 怎么处理 |
| --- | --- |
| 启动器发现旧式直连宿主 | 等原任务结束并关闭旧宿主后再启动受保护宿主 |
| 端口已被其他进程占用 | 核对项目和进程归属 先协调现有任务 |
| 工具列表里没有目标工具 | 重新发现并检查注册和依赖报告 |
| 缺少项目原生类或函数 | 在接入项目补齐接口并编译后验证 |
| 返回 `status=queued` | 保留顺序 继续查询与准备 按状态变化领取阶段 |
| 返回 `EDITOR_TASK_REQUIRED` | 先登记可写任务 |
| 返回 `EDITOR_WRITE_REQUIRED` | 登记后还需申请编辑阶段 |
| 返回 `WRITE_RECOVERY_REQUIRED` | 核实实际状态后凭两份原凭证显式恢复 |
| 释放或退出被拒绝 | 检查未完成请求 PIE 采样或未保存资产 |
| 逻辑工具可用但截图失败 | 核对宿主是否启用了渲染及工具所需插件 |

## 代码和文档放在哪里

| 目录或文件 | 用途 |
| --- | --- |
| `Scripts/` | UE 编辑器里的工具实现和注册 |
| `Scripts/MCP/` | 启动器 客户端和任务网关 |
| `Docs/` | 各领域的工具参数和使用边界 |
| `Tests/` | 源码检查 隔离测试及真实宿主验证 |
| `requirements.txt` | 外部 Python 依赖 |

继续阅读:

- [MCP 调用与开发说明](Docs/UnrealMcpCanonical.md)
- [项目原生依赖](Docs/ProjectDependencies.md)
- [共享宿主任务保护](Docs/BBBMcpTaskProtection.md)

部分专项文档保留了历史记录.
工具名称 参数和依赖以当前宿主的实际发现结果为准.
共享入口的权限及生命周期规则以任务保护说明为准.

## 修改工具的人需要做什么

1. 阅读目标项目及所属目录的 `Law.md`.
2. 查看已有工具是否能完成任务.
3. 在 `Scripts/` 中实现并注册职责清楚的工具.
4. 同步更新对应使用文档和 `Tests/tool_schema_baseline.json`.
5. 完成源码检查和必要的实际调用验证.
6. 保留其他并行任务的改动 提交已经验证的本任务内容.

常用验证入口:

```powershell
python -B Tests/test_repository.py
python -B -m unittest discover -s Tests -p test_mcp_contracts.py
python -B -m unittest discover -s Tests -p test_mcp_task_gateway.py
python -B -m unittest discover -s Tests -p test_mcp_task_recovery.py
& .\Tests\Test-Startup.ps1
python -B Tests/verify_mcp_task_protection.py --url $hostInfo.Endpoint --project-root ([System.IO.Path]::GetDirectoryName($projectFile))
```

最后一项需要受保护的目标项目宿主 并会实际开始和结束 PIE.
运行前确认宿主空闲且没有未保存资产.
全工具契约验证入口为 `Tests/verify_live_mcp.py` 其中部分调用尚需适配共享网关的权限限制.
选择与改动有关的检查 并如实报告未通过或未执行的验证.

项目规则文件保持只读.
提交目标和分支以接入项目的版本控制规则为准.
提交前用 `git remote -v` 和 `git branch --show-current` 在本机核对.
按项目规则提交并正常推送已经完成和验证的改动.

## 对外分享信息前

文档示例使用相对路径和运行时配置.
分享日志 截图或诊断结果前会隐藏本机用户名 绝对路径 项目私有资产路径及账号信息.
任务凭证 私有后端地址和访问密钥只供本机任务使用 不写入公开文档或版本库.

第三方 GenOrca 动作的来源和许可证见 [项目依赖](Docs/ProjectDependencies.md).

## 更新日志

### 2026-10-10

- 原项目宿主按真实目录统一网关归属 所有端口共用生命周期锁 移除 IndependentHost 例外. 占用查询展示同项目编辑器与其他网关 多宿主冲突保留任务归属并阻止资产写入. 截图预检与空射线返回明确执行证据 清理失败保留结果核实流程. 移除整项目复制模块 测试副本队列 五个公共接口 SDK 方法与测试宿主启动分支. PIE 隔离方式按实际需求另行确定.


- 补齐地图重定向器残留文件测试的原生对象枚举测试桩 保留残留文件时拒绝成功的检查

- 写入诊断记录执行证据与未保存包变化 SDK 编辑阶段自动续期 失联接管通过具体清单的用户确认完成 旧凭证撤销后由接手任务核实并收尾

- `delete_asset_redirectors` 清理蓝图包内未注册为资产的骨架类重定向对象 防止主重定向器删除后留下旧文件和脏包

- `inject_pie_action` 支持明确指定同一宿主内的本地 PIE 玩家控制器 用于客机输入验收 拒绝编辑器对象与远端镜像控制器
- 占用报告显示当前阶段 工具 耗时 等待原因和本任务下一步.
- 排队顺序在等待结束和重连后保持 支持主动取消和任务到期清理.
- 等待者共享宿主观测 按状态版本等待变化 编辑授权时核对实际状态.
- 工具发现展示权限分类 新增共享资产搜索 对象查询 蓝图快照和动画通知查询.
- SDK 提供 `run_write_batch` 失败时保留已完成结果及所属阶段.
- 完成三客户端 PIE 验收 同时覆盖批次交接和共享查询.

