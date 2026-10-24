# 公开调用契约

## 入口

| 工具 | 输入 | 返回与继续方式 |
| --- | --- | --- |
| `manage_operator` | `task`、`level=2`、`action=join`；可指定 `operator` | 登记、更新或结束逻辑会话 |
| `find_tools` | `query`；`limit=3` | 首项完整契约，其余候选简述 |
| `describe_tool` | `tool` | 参数、默认值、权限、范围、依赖、完成条件与版本 |
| `submit_batch` | `operations`；`await_seconds=2` | 已完成结果或待继续的批次 |
| `inspect_tasks` | `batch`、`after_revision`、`wait_seconds`；`detail=false`、`operators=false` | 占用、进度、结果与唯一下一步 |
| `control_task` | `action`、`batch`、`operator`、`lease_seconds`、`host` | 批次收尾与零级定向管理 |

会话先登记单行二十字以内任务，默认二级。零级支持主动登记与面板授予，权限持续至逻辑会话结束。`manage_operator(action="finish")` 结束登记。`inspect_tasks(operators=true)` 返回干员池。调度按等级及同级提交时间执行，编辑操作在保存回读边界让行，同一资产保持操作顺序。

操作格式：`{"tool":"领域.函数","arguments":{}}`，每批一至十六项。参数校验一次覆盖完整批次。对象和数组直接提交；对象引用使用路径字符串。

短等待范围零至十秒。`queued`、`running` 按批次版本等待；`completed` 直接读取 `results` 和 `proof`；`rejected` 根据最多十六项字段问题一次修正；`failed` 读取实际执行范围、错误和资产故障。

## 完成条件

编辑批次自动校验、执行、编译、保存、回读并释放资产。执行槽随实际操作结束释放，结果记录独立保留。修改范围由契约目标、本批次新增脏包以及引用改写操作的实际引用者确定。

异常结果由网关自动核实。原操作保留执行边界与错误；已知修改完成保存后发布结果。保存或回读故障登记在具体资产，后台退避恢复，独立资产继续执行。客户端离线和结果交付均保持后台收尾。
普通结果保留用于短期重放；完成记录自动回收。文件、PIE 和持续活动沿所属任务交付。测试输出交付后对首次批次使用 `close`。

`inspect_tasks()` 返回紧凑占用。`inspect_tasks(batch=...)` 的 `revision` 属于该批次；项目总览的版本覆盖项目活动。`detail=true` 展开错误、范围、版本与分段耗时。所有终态交付已完成操作结果；普通进度保留状态摘要，保存与回读完整证据在终态交付。

## 资产协调

`ASSET_BUSY` 返回实际冲突包、占用阶段和原因；队列在资产交接后自动继续。`asset_occupancy` 提供有界摘要，`detail=true` 展开完整范围。`phase="fault"` 表示资产保存或回读故障，网关自动重试。

目标范围已有脏包时，服务核对资产占用，定向编译、保存与回读后执行原批次。`proof.prepared` 记录前置保存的包，`proof.saved` 记录保存结果。其他活动批次持有的资产按原归属交接，故障资产沿后台恢复流程处理。占用响应默认提供八项包摘要，`detail=true` 返回完整证据，内部保存始终使用完整范围。

`ASSET_SCOPE_REQUIRED` 在派发前指出范围缺失的工具。地图演员按地图及外部 Actor/Object 包协调；当前地图改变时返回 `EDITOR_WORLD_CHANGED`。

`ARGUMENT_INVALID` 的 `needs` 返回具体字段路径、操作序号与准确字段契约。校验阶段实际修改为零的批次立即结束；部分成功的批次保存已知修改并保留 `failure`。执行结果不确定时，自动核实证据写入 `proof.reconciled`，原执行状态继续标为 `unknown`。

`control_task` 使用 `cancel`、`close`、`shutdown_host`。零级可用 `pause_operator`、`resume_operator`、`cancel_blocker`、`terminate_host` 定向管理；暂停默认六十秒，上限三百秒，到期恢复。宿主终止按进程代际核验并记录审计，未保存内存修改随进程退出丢失。`close` 交付结果及所属测试输出；资产收尾由网关独立完成。读取结果和保留结果记录均保持资产可用。

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

常驻服务运行于当前用户会话，固定入口默认 `http://127.0.0.1:8000/mcp`。多项目使用 `/projects/<project_key>/mcp`，项目身份由 `mcp_host_registry.project_key` 计算。协议版本为 6，公开工具保持六项。

`Start-BBBMcpService.ps1 -ProjectPath <uproject> -InstallAtLogon` 配置登录启动与监督进程。监督进程持续核验服务；SDK 在本机连接失败时自动拉起已配置服务。直接 HTTP 客户端通过登录任务维持服务在线。

`Content/Python/init_unreal.py` 注册工具后调用 `BBBMcpEditorStartup.start_editor_mcp()`，启动当前编辑器私有后端，并写入 `Saved/McpState/hosts` 的用户私有登记文件。后台心跳持续更新登记；服务恢复后重新接入。`BBBMcpServicePort` 与 `BBBMcpServicePython` 指定入口与外部 Python。

服务通过项目路径、PID、进程创建时间与程序路径核验身份。系统扫描发现全部 UE，私有登记提供可操作连接。额外编辑器显示 `waiting_assignment`；资产宿主归属保持稳定。测试宿主通过批次身份与受限 Job 重新核验。

`inspect_tasks` 的 `service` 表示服务状态，`connection` 使用 `offline`、`connecting`、`ready`、`unresponsive`。`hosts` 返回脱敏进程清单；`stale=true` 表示资产与活动来自最近快照。编辑器离线时提交返回 `EDITOR_OFFLINE` 或 `EDITOR_CONNECTING`，按 `retry_after_seconds` 与 `inspect_tasks` 等待后重新提交。响应中的 `batch` 才代表批次已被接受。

上次核验的工具目录保存在 `Saved/McpState/catalog.json`，编辑器暂离线时继续支持发现；首次接入后建立目录。客户端身份与结果存储持续保留，编辑器切换后按原归属查询。

服务重启后核验原测试进程，已派发且结果缺失的操作标记 `TEST_EXECUTION_UNCERTAIN`，实际 PIE 与后续批次沿原测试宿主接续。编辑器进程变化后保留原写入证据，重新回读当前资产。

服务配置与有界日志位于当前用户 `%LOCALAPPDATA%/BBBMcp`。私有后端地址保存在用户私有登记目录，公开状态返回脱敏身份。`/health` 仅供本机服务核验。临时验收使用独立配置目录与端口。

# PIE 临时对象范围

`/Game/.../UEDPIE_<编号>_<地图>` 是测试宿主中的临时包 其 Actor 与组件路径不作为磁盘资产或源控写入目标 正式地图通过测试配置继续参与资产版本检查。

## 可选对象的写入范围

范围字段中的可选空引用不构成写入目标。新增蓝图成员变量时 `blueprint` 确定实际包范围，省略或设为 null 的 `graph` 不会使范围失效；新增局部变量时同时保留蓝图和图表证据。没有任何实际目标的编辑器写入仍拒绝执行，必填参数继续由契约校验。

## 嵌套蓝图图表节点

`blueprint.create_blueprint_graph_node` 通过目标图表自身的原生编辑器创建节点，支持状态转换等非直属图表。`node_type_id` 必须精确匹配该图可用类型；返回实际节点路径与引脚索引，后续使用 `blueprint_base.connect_pins` 连接。目标先经过项目资产写入校验，批次仍执行编译、保存与回读。

## 精简继续调用

`next` 为 `{tool, arguments}` 或 `null`，对象包含下一次公开调用的完整参数。`needs` 表示待补充字段；图表快照变化给出重新读取逻辑的调用，AI 按新快照重新分析后应用。

SDK 缓存发现首项的完整契约，按响应 `catalog_version` 失效。工具详情按目标提供短用途、区别与完成条件；属性配置、蓝图注释、武器验收附带短路线。

普通进度省略中间大结果，终态保留完整结果与保存回读证据。`owned_activities` 只列当前会话所属活动；`host.verified` 标明实际连接已核验。采样启动与采样活动分别完成，SDK `wait_activity("weapon:probe", batch=test_host)` 等待所属采样，之后读取采样状态事实。

## 干员生命周期

一次 McpSession 覆盖完整任务，包括批次等待、PIE 与证据交付。最后一个所属传输连接关闭时自动发起释放，显式 finish 同样进入收尾；收尾中的登记返回 OPERATOR_DRAINING，现有工作继续完成保存与归属交接。

干员池仅展示有效登记及 releasing 状态。五分钟空闲租约到期自动回收；连接心跳只续传输，活动中的工作保留所属登记。失联且仍有工作时自动收尾，完成后从池中删除。审计与批次证据独立保留。新任务重新登记，默认二级。

## 权限处置

服务以干员等级、实际归属和完整资产范围判定执行。二级与一级按优先级排队，零级管理调用直接校验权限和目标身份并记录审计。已授权任务的定向保存、排队、后台恢复与零级管理由服务完成。客户端按返回的 `next` 继续；业务内容选择由任务输入确定。

## 批量收尾与恢复调度

共享宿主每组最多128包，批量读取类型与编译状态，仅编译需要更新的蓝图，批量重存后按包回读。批量重存失败保留已保存包和逐包故障证据，正式结果记录实际成功范围。到期资产恢复与普通候选按干员等级和原提交顺序选择，故障退避控制重复恢复频率。

参数校验覆盖整批，`needs` 最多十六项，分别给出操作字段路径、类型及修正规则。`INTERNAL_ERROR` 提供诊断编号，服务日志记录对应原因；所属已接受批次继续通过 `inspect_tasks` 核实。

干员目标的发现首项标注 `direct=true` 并提供公开 `call`；AI 直接执行该公开入口。宿主默认 `Balanced`，即60 FPS、Normal，显式性能参数决定本次配置。

## 故障批次接续

`control_task(action="recover", batch=...)` 接受当前客户端所属故障批次及零级接管的其它会话故障批次，在原范围内重新安排恢复。处于 releasing 的身份通过该入口完成交接，权限维持二级收尾语义。SDK 初始化保留传输连接，并在 `session.recovery` 返回登记收尾原因与完整继续调用；新编辑继续要求有效登记。

资产故障的 `retry_at=null` 表示自动恢复预算耗尽或实际状态需要核验。迁移专用证据在 `proof.move_recovery` 交付，原操作失败事实独立保留，资产已完成交接时响应明确提示后续可继续。

零级干员使用 `control_task(action="recover", batch=...)` 接管其它会话的故障批次。服务核对终态、故障占用及所属活动，原子转移批次归属并记录原干员与接管干员。原客户端控制权限随归属转移；恢复沿原迁移证据核验、保存及释放资产。
