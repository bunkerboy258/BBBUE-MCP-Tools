# 公开调用契约

## 入口

| 工具 | 输入 | 返回与继续方式 |
| --- | --- | --- |
| `find_tools` | `query`；`limit=3` | 首项完整契约，其余候选简述 |
| `describe_tool` | `tool` | 参数、默认值、权限、范围、依赖、完成条件与版本 |
| `submit_batch` | `operations`；`await_seconds=2`；`completion="save"` | 已完成结果或待继续的批次 |
| `inspect_tasks` | `batch`、`after_revision`、`wait_seconds`；`detail=false` | 占用、进度、结果与唯一下一步 |
| `control_task` | `action`、`batch`、`confirmation` | 取消、核实、接续、输出交付与宿主收尾 |

操作格式：`{"tool":"领域.函数","arguments":{}}`，每批一至十六项。参数校验一次覆盖完整批次。对象和数组直接提交；对象引用使用路径字符串。

短等待范围零至十秒。`queued`、`running` 按批次版本等待；`completed` 直接读取 `results` 和 `proof`；`rejected` 根据字段位置修正；`review` 回读并处理实际执行范围。

## 完成条件

编辑默认采用验证保存。保存范围由契约声明的目标与本批次新增脏包确定。编译、回读或范围核验需要处理时，证据保留在 `review`。分阶段编辑显式设置 `completion="review"`。

普通结果保留用于短期重放；完成记录自动回收。文件、PIE 和持续活动沿所属任务交付。测试输出交付后对首次批次使用 `close`。

`inspect_tasks()` 返回紧凑占用。`inspect_tasks(batch=...)` 的 `revision` 属于该批次；项目总览的版本覆盖项目活动。`detail=true` 展开错误、范围、版本与分段耗时。

## 保存冲突恢复

`DIRTY_ASSETS` 返回 `pending_save.packages` 与 `hint`。AI 使用 `editor.save_assets` 保存这些明确包路径，再检查原批次；脏包清空后该批次自动完成。

`RESULT_REVIEW_REQUIRED` 返回占用批次、归属与冲突包。`mine=true` 时先读取原批次的 `failure`；同一客户端可提交仅包含当前脏包的 `editor.save_assets` 批次解开自身保存阻塞。保存后调用 `control_task(action="review")` 检查回执，再以回执的 `confirmation` 调用 `control_task(action="resume")` 确认关闭原审阅批次，然后用新批次继续。`mine=false` 时等待所属客户端完成保存与核实。

`TARGET_ALREADY_DIRTY` 提示 AI 等待当前修改所属任务保存，并继续只读准备。`ARGUMENT_INVALID` 保留字段路径并提示调用 `describe_tool` 查看完整参数定义。失败批次若处于 `review`，先保存返回的脏包，再对原批次执行 `review` 与 `resume` 完成核实，最后用新批次提交修正后的操作。

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

# PIE 临时对象范围

`/Game/.../UEDPIE_<编号>_<地图>` 是测试宿主中的临时包 其 Actor 与组件路径不作为磁盘资产或源控写入目标 正式地图通过测试配置继续参与资产版本检查。

测试批次所有操作已经执行且只因完成证据暂时未核实时 可用 `control_task review` 获取凭证并用 `resume` 重新核实 该路径不重放任何动作 未执行完的失败批次与输入资产已变化的批次仍须重跑。
