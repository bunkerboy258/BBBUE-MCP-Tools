# 公开调用契约

## 入口

| 工具 | 输入 | 返回与继续方式 |
| --- | --- | --- |
| `find_tools` | `query`；`limit=3` | 首项完整契约，其余候选简述 |
| `describe_tool` | `tool` | 参数、默认值、权限、范围、依赖、完成条件与版本 |
| `submit_batch` | `operations`；`await_seconds=2` | 已完成结果或待继续的批次 |
| `inspect_tasks` | `batch`、`after_revision`、`wait_seconds`；`detail=false` | 占用、进度、结果与唯一下一步 |
| `control_task` | `action`、`batch` | 取消排队、交付输出与宿主收尾 |

操作格式：`{"tool":"领域.函数","arguments":{}}`，每批一至十六项。参数校验一次覆盖完整批次。对象和数组直接提交；对象引用使用路径字符串。

短等待范围零至十秒。`queued`、`running` 按批次版本等待；`completed` 直接读取 `results` 和 `proof`；`rejected` 根据字段位置修正；`failed` 读取实际执行范围、错误和资产故障。

## 完成条件

编辑批次自动校验、执行、编译、保存、回读并释放资产。执行槽随实际操作结束释放，结果记录独立保留。修改范围由契约目标、本批次新增脏包以及引用改写操作的实际引用者确定。

异常结果由网关自动核实。原操作保留执行边界与错误；已知修改完成保存后发布结果。保存或回读故障登记在具体资产，后台退避恢复，独立资产继续执行。客户端离线和结果交付均保持后台收尾。
普通结果保留用于短期重放；完成记录自动回收。文件、PIE 和持续活动沿所属任务交付。测试输出交付后对首次批次使用 `close`。

`inspect_tasks()` 返回紧凑占用。`inspect_tasks(batch=...)` 的 `revision` 属于该批次；项目总览的版本覆盖项目活动。`detail=true` 展开错误、范围、版本与分段耗时。

## 资产协调

`ASSET_BUSY` 返回实际冲突包、占用阶段和原因；队列在资产交接后自动继续。`asset_occupancy` 提供有界摘要，`detail=true` 展开完整范围。`phase="fault"` 表示资产保存或回读故障，网关自动重试。

`ASSET_SAVE_REQUIRED` 表示目标包在任务开始前已有编辑器修改；核实归属后以 `asset.save_assets` 保存明确包。其余资产继续推进。同一客户端对故障范围提交修正操作时，已登记修改随新批次完成验证保存。

`ASSET_SCOPE_REQUIRED` 在派发前指出范围缺失的工具。地图演员按地图及外部 Actor/Object 包协调；当前地图改变时返回 `EDITOR_WORLD_CHANGED`。

`ARGUMENT_INVALID` 返回具体字段位置。校验阶段实际修改为零的批次立即结束；部分成功的批次保存已知修改并保留 `failure`。执行结果不确定时，自动核实证据写入 `proof.reconciled`，原执行状态继续标为 `unknown`。

`control_task` 使用 `cancel`、`close`、`shutdown_host`。`close` 交付结果及所属测试输出；资产收尾由网关独立完成。读取结果和保留结果记录均保持资产可用。

## 世界与测试

权限：`read`、`write`、`pie`。世界：`any`、`editor`、`pie`。预览和状态动作按实际参数解析权限与依赖。

`environment="editor"` 使用共享资产编辑宿主。`environment="test"` 使用原项目的受限测试宿主；首次提供 `test_options.map`，可选渲染、音频、玩家数量与网络模式。后续提供首次响应中的 `test_host`。

测试结果记录输入版本，版本变化返回 `TEST_INPUT_CHANGED`。源码、配置与资产保留各自归属，输出由批次目录维护。

## 读取视图

`blueprint.inspect_blueprint_graph`：

- `view="overview"`：节点与原有注释总览。
- `view="logic"`：完整选定节点、引脚与按输出记录的连线。
- `view="geometry"`：实际显示边界。
- `node_guids` 选择节点；`offset`、`limit` 分页；后续页携带 `expected_snapshot`。

`object.list_properties`：`query` 过滤反射字段；`offset`、`limit` 分页；后续页携带 `expected_version`。属性写入先校验实际反射结构，再回读声明值。

## 连接与恢复

连接层独立维护传输会话、客户端归属与任务租期。HTTP 会话引用保留客户端身份；SDK 定期续期并使用原身份恢复连接。

稳定请求身份由连接层生成。响应丢失时重放原结果。恢复存储保存单向客户端标识、请求结果与执行边界；中断写入进入按范围核实。恢复状态缺少原请求依据时，客户端先读取实际状态。

## 开发

领域输入声明位于对应模块的 `MCP_INPUTS`。`MCP/mcp_contracts.py` 编译唯一契约；`BBBMcpCapabilities` 提供发现、校验、范围与依赖；`MCP/mcp_clients.py` 维护归属、重放和恢复存储。

测试外层保留已完成批次的结果 内层队列可以回收历史记录 已完成结果不再重复依赖内层记录的存在 同一测试宿主继续接收后续批次 不因历史结果回收退出 PIE

异步流程通过 `register_activity` 登记实际状态。隔离测试、固定任务语料和真实 UE 验收分别验证契约、调度与执行结果。任务总耗时评估分开记录发现、公共轮次、排队、UE 操作与收尾；模型决策耗时使用实际客户端时间线。

## 独立服务与编辑器接入

常驻服务运行于当前用户会话，固定入口默认 `http://127.0.0.1:8000/mcp`。多项目使用 `/projects/<project_key>/mcp`，项目身份由 `mcp_host_registry.project_key` 计算。协议版本为 5，公开工具保持五项。

`Start-BBBMcpService.ps1 -ProjectPath <uproject> -InstallAtLogon` 配置登录启动与监督进程。监督进程持续核验服务；SDK 在本机连接失败时自动拉起已配置服务。直接 HTTP 客户端通过登录任务维持服务在线。

`Content/Python/init_unreal.py` 注册工具后调用 `BBBMcpEditorStartup.start_editor_mcp()`，启动当前编辑器私有后端，并写入 `Saved/McpState/hosts` 的用户私有登记文件。后台心跳持续更新登记；服务恢复后重新接入。`BBBMcpServicePort` 与 `BBBMcpServicePython` 指定入口与外部 Python。

服务通过项目路径、PID、进程创建时间与程序路径核验身份。系统扫描发现全部 UE，私有登记提供可操作连接。额外编辑器显示 `waiting_assignment`；资产宿主归属保持稳定。测试宿主通过批次身份与受限 Job 重新核验。

`inspect_tasks` 的 `service` 表示服务状态，`connection` 使用 `offline`、`connecting`、`ready`、`unresponsive`。`hosts` 返回脱敏进程清单；`stale=true` 表示资产与活动来自最近快照。编辑器离线时提交返回 `EDITOR_OFFLINE` 或 `EDITOR_CONNECTING`，按 `retry_after_seconds` 与 `inspect_tasks` 等待后重新提交。响应中的 `batch` 才代表批次已被接受。

上次核验的工具目录保存在 `Saved/McpState/catalog.json`，编辑器暂离线时继续支持发现；首次接入后建立目录。客户端身份与结果存储持续保留，编辑器切换后按原归属查询。

服务重启后核验原测试进程，已派发且结果缺失的操作标记 `TEST_EXECUTION_UNCERTAIN`，实际 PIE 与后续批次沿原测试宿主接续。编辑器进程变化后保留原写入证据，重新回读当前资产。

服务配置与有界日志位于当前用户 `%LOCALAPPDATA%/BBBMcp`。私有后端地址保存在用户私有登记目录，公开状态返回脱敏身份。`/health` 仅供本机服务核验。临时验收使用独立配置目录与端口。

# PIE 临时对象范围

`/Game/.../UEDPIE_<编号>_<地图>` 是测试宿主中的临时包 其 Actor 与组件路径不作为磁盘资产或源控写入目标 正式地图通过测试配置继续参与资产版本检查。
