# BBB MCP 共享宿主任务保护

## 入口和适用范围

通过 `Scripts/MCP/Start-UE58OfficialMcpEditor.ps1` 启动或复用一个可写项目宿主.
客户端使用启动器返回的 `Endpoint` 可通过 `BBB_MCP_URL` 配置地址.
官方 UE MCP 后端使用独立本机端口和每次启动生成的私有路径.

声音验收使用启动器的 `EnableAudio` 开关 新宿主启用音频混音器 并仅通过进程参数将后台音量系数设为一 避免隐藏窗口录到静音 不修改项目配置 参数须使用 UE 配置节语法 `-ini:Engine:[Audio]:UnfocusedVolumeMultiplier=1.0` 缺少方括号不会覆盖 Audio 配置节 默认宿主仍禁用音频 复用时必须匹配原宿主音频模式及后台声音参数 活动任务期间不切换模式 音频录制和实际输出必须回读 不将发声请求视为已经听到声音

隐藏编辑器还有独立的后台声音门控 启动器仅为音频模式增加 `-ini:EditorPerProjectUserSettings:[/Script/UnrealEd.LevelEditorMiscSettings]:bAllowBackgroundAudio=True` 不保存用户设置 不能只检查系统后台音量系数 实际 PIE 的应用音量与设备主音量也必须非零.

启动器核对项目 进程 渲染模式 性能设置和网关身份.
同一项目的旧式直连宿主须在原任务结束后退出才能切换.
有活动任务时不重启网关 不丢弃已有凭证.
公开入口检查项目工具 官方工具和直接工具名称调用.

私有路径用于防止误连后端.
具有本机进程访问权限的程序仍可发现后端地址 手动操作 UE 或终止进程.
本机制不提供操作系统权限隔离.

## 任务登记和写权限是两个阶段

任务登记表示该任务仍需要宿主 不自动取得写权限.
多个 `read` `editor` 和 `pie` 任务可以同时登记.

- `read` 任务只能执行已审核的只读查询.
- `editor` 和 `pie` 任务可以申请编辑阶段.
- 同一宿主同时只允许一个编辑阶段.
- 一组连续编辑操作及结果回读完成后结束阶段.
- 分析 等待回复和准备下一组操作期间保留登记并让出写权限.
- PIE 录制和采样期间保留所属任务的编辑阶段.

完整流程:

```text
登记任务
    -> 分析和准备
    -> 申请编辑阶段
    -> 执行连续操作并核实实际结果
    -> 结束 PIE 和采样 处理本阶段未保存内容
    -> 结束编辑阶段
    -> 继续分析或释放任务登记
```

多步骤编辑中需要保持连续性的操作放在同一个阶段.
结束阶段会要求宿主没有实际活动和未保存内容.
当前按整个宿主检查这些条件.

## 九个网关工具

通过 `list_toolsets` 找到 `bbb_task` 然后描述该工具集.
也可以通过 `tools/list` 发现这些工具.
只提供固定发现接口的客户端可用 `call_tool` 且不填写 `toolset_name` 调用它们.

| 工具 | 参数 | 行为 |
| --- | --- | --- |
| `acquire_editor_task` | `task_id` `description` `mode` 可选 `ttl_seconds=300` | 登记任务 返回 `task_token` |
| `renew_editor_task` | `task_token` 可选 `resume=False` | 续期任务登记 |
| `begin_editor_write` | `task_token` 可选 `ttl_seconds=120` `wait_seconds=0` `stage_label` | 申请或领取编辑阶段 返回 `active` 与 `write_token` 或 `queued` 与状态 |
| `cancel_editor_write` | `task_token` | 取消本任务排队申请 保留登记 唤醒本任务等待请求 |
| `renew_editor_write` | `task_token` `write_token` 可选 `resume=False` | 续期或显式恢复原阶段 |
| `end_editor_write` | `task_token` `write_token` | 让出写权限 保留登记 |
| `release_editor_task` | `task_token` | 结束没有编辑阶段的任务登记 |
| `inspect_editor_tasks` | 可选 `task_token` `after_revision` `wait_seconds=0` | 查询占用 当前工具 阻塞原因和下一步 或等待状态版本变化 |
| `shutdown_editor_host` | 无 | 所有任务 请求 活动和脏包清零后请求退出 |

任务有效期为三十至三千六百秒.
编辑阶段有效期为三十至九百秒.
单次申请最多等待六十秒.
单次等待结束后返回 `status=queued` 并保留原顺序.
队列按申请顺序排列 队首任务主动领取阶段.
再次调用 `begin_editor_write` 复用本任务的申请与原阶段参数.
任务每次保持一份申请 同时保持一个领取请求.
取消申请或任务有效期结束后释放队列位置.
长时间准备期间使用 `renew_editor_task` 保持任务与申请有效.
编辑阶段从领取成功后开始计时.

`inspect_editor_tasks` 中 `writer_task_id` 表示当前写入者.
`write_queue` 表示等待顺序.
每个任务的 `write` 为当前阶段状态或空值.
`last_write_state` 表示阶段完成 超时回收或预检失败.

## AI 如何理解当前占用

`inspect_editor_tasks` 返回完整快照 `summary` 提供精简解释:

| 字段 | 含义 |
| --- | --- |
| `revision` | 实际状态版本 |
| `writer` | 当前任务说明 阶段用途与正在执行的工具 |
| `writer.write.elapsed_seconds` | 阶段实际耗时 |
| `writer.operations` | 执行中的工具名称 权限分类与操作耗时 |
| `blockers` | 占用 PIE 采样 未保存资产和恢复要求 |
| `caller` | 本任务可读 可准备 可写 可领取及下一步调用 |
| `observation_age_seconds` | 最近实际宿主观测距今秒数 |

`remaining_seconds` 表示凭证有效期.
实际耗时由 `elapsed_seconds` 表示 完成时间以实际结果为准.

标准调用响应和工具发现结果在 `result._meta["bbb/editor_state"]` 中附带精简状态.
`list_toolsets` 的文字结果和 `get_mcp_usage_guide` 的业务结果也展示当前占用.
SDK 将最近收到的状态保存在 `session.editor_state` 中.
发现缓存保存工具结构 占用摘要使用最近收到的状态并累加观测年龄.
准备写入或确认新变化时调用 `inspect_editor_tasks` 获取当前快照.

传入任务凭证后 `caller` 对应本任务 SDK 自动携带登记凭证.
`caller.can_claim_write=true` 时调用 `begin_editor_write` 领取阶段.
等待期间可执行 `shared_read` 查询 分析结果和准备下一批完整参数.
查询结果反映该次调用时的实际状态 连续读取时结合状态版本和当前操作理解结果.

已有 `revision` 时调用 `inspect_editor_tasks(after_revision=revision, wait_seconds=30)`.
版本变化时及时返回 达到等待上限时返回当前状态.
状态版本属于当前网关宿主 连接到新宿主后重新获取.
网关合并同时进行的宿主探测 等待期间共享一秒观测窗口.
实际编辑授权与阶段结束继续执行现场状态检查.
`metrics.probe_count` 与 `metrics.probe_seconds` 用于比较探测数量和耗时.

工具描述中的 `_meta["bbb/access"]` 与附加文字标明 `shared_read` `editor_write` `pie_write` `conditional` 或 `blocked`.
唯一权限分类来源为 `Scripts/MCP/mcp_access_policy.py`.
`bbb_task` 描述和使用指南提供共享查询清单及参数条件.
经过审查的资产搜索 对象属性查询 蓝图快照和动画通知查询可以与其他任务的编辑阶段并存.

## 两份凭证

`task_token` 证明任务身份.
`write_token` 证明当前编辑阶段的权限.
写操作必须同时携带两份凭证.

`call_tool` 最外层参数示例:

```json
{
  "toolset_name": "<实际发现的工具集完整名称>",
  "tool_name": "<目标工具名称>",
  "arguments": {},
  "task_token": "<任务凭证>",
  "write_token": "<当前编辑阶段凭证>"
}
```

协议客户端也可通过 `params._meta` 中的 `bbb/task_token` 和 `bbb/write_token` 传入.
网关检查后剥离凭证 再将业务参数发给 UE.

凭证不写入公开文档 仓库 日志或其他任务.
被结束或回收的阶段凭证不能控制后续阶段.

## Python 和命令行客户端

从仓库 `Scripts` 目录导入客户端 并先配置 `BBB_MCP_URL`.

```python
import os
from MCP.mcp_call import McpSession

with McpSession(os.environ["BBB_MCP_URL"]) as session:
    task = session.acquire_task("editing-task", "编辑与分析", "editor", 900)
    stage = session.begin_write(ttl_seconds=120, wait_seconds=30, stage_label="已准备的编辑批次")
    if stage["status"] == "queued":
        state = session.inspect_tasks(stage["state"]["revision"], wait_seconds=30)
        print(state["summary"])
        if state["summary"]["caller"]["can_claim_write"]:
            stage = session.begin_write()
    if stage["status"] == "active":
        session.renew_write()
        session.end_write()
    session.cancel_write()
    session.renew_task()
    session.release_task()
```

示例只演示生命周期.
目标编辑操作放在 `begin_write` 和 `end_write` 之间.
结束前核实实际结果并处理本阶段的未保存内容.
较长阶段主动调用 `renew_write`.
没有编辑阶段的长时间分析主动调用 `renew_task`.

已经准备好完整参数时使用 `session.run_write_batch(calls, stage_label, ttl_seconds=120, wait_seconds=60)`.
`calls` 使用 `call_many` 的请求数组结构.
该方法先检查整批结构 再排队等待领取 执行逐项检查 回读结果并交接.
等待期间按状态版本监听 每二十秒保持任务有效.
PIE 和采样需要阶段归属覆盖整个活动 使用手动阶段流程管理开始 结束和实际状态检查.

`McpWriteBatchError.phase` 标明 `queue` `execute` 或 `handoff`.
`completed_results` 保留已完成请求 `__cause__` 保留原始错误与失败位置.
排队总等待结束后申请继续有效 可继续领取或显式取消.
执行或交接受阻时保留阶段凭证 原任务核实结果和实际活动后继续处理.
资产保存和采样停止由所属任务明确执行.

`close()` 只关闭 HTTP 会话.
重连时创建 `McpSession(url, task_token=task["task_token"], write_token=stage["write_token"])`.
分析阶段重连只需要任务凭证.

命令行通过 `BBB_MCP_TASK_TOKEN` 和 `BBB_MCP_WRITE_TOKEN` 携带凭证.
批量操作使用 `call_many` 或 `batch` 每个实际操作都经过网关检查.
批量调用不回滚已完成的操作.

## 超时和安全回收

有实际请求在执行时保留编辑阶段.
请求完成后刷新阶段有效期.

编辑阶段超时后仅在以下条件全部成立时回收:

- 没有该任务的实际请求.
- 没有 PIE 世界 开始或结束的未确认请求.
- 没有后台采样或其他已跟踪活动.
- 没有未保存内容.
- 没有执行结果不确定或宿主身份变化.

回收只撤销写权限 不停止 PIE 不保存资产.
仍有效的任务登记可重新申请阶段.
没有请求 编辑阶段或不确定结果的失联登记也会被回收.
任务凭证已失效时重新登记.

存在活动或不确定结果的阶段标记为 `orphaned` 并保留权限归属.
原任务先读取实际状态 再凭两份原凭证调用 `renew_editor_write(resume=True)`.
未生效的 PIE 请求不能通过续期清除.
不确定的资产写入不自动重试.

客户端收到明确的凭证失效错误后清除对应本地凭证.
传输失败和活动未结束时保留凭证.

## 实际活动和重载

`BBBMcpTaskToolset.inspect_editor_activity` 返回宿主身份 PIE 世界代次 暂停世界 后台活动和脏包.
当前活动包括动画运动采样 音频录制 动画截图 群体基准 受击采样 后坐力采样和原生输入序列.
原生输入释放失败也保留活动保护.

宿主身份和世界代次保存在同一 UE Python 进程中.
正常工具重载不会重新生成宿主身份或重置代次.
真正的宿主身份变化仍阻断旧凭证.
重载后重新发现工具参数和实际注册名称.

已有活动或未保存内容没有当前阶段归属时不自动接管.
未知工具默认需要编辑阶段.
已审核的只读清单位于 `mcp_access_policy.py`.
`inspect_mass_inspection_population(pause_game=True)` 需要编辑阶段.
任意 Python 脚本和控制台执行被拒绝.
PCG 异步生成尚无活动状态探针 共享入口拒绝 `generate=True`.
新增异步工具必须同时提供完成状态的实际回读.

## 宿主退出和验证

按用户批准的共享生命周期规则 单个任务结束后释放自己的登记.
有效任务 编辑阶段 等待申请和实际请求都会阻止宿主退出.
全部清零后调用 `shutdown_editor_host`.
返回 `shutdown_requested` 后仍需核实对应编辑器和网关进程已退出.
宿主退出后本网关自行退出 不终止其他进程或删除其他任务文件.
项目 `Law.md` 保持只读.

隔离验证入口为 `Tests/test_mcp_task_gateway.py`.
真实宿主验证入口为 `Tests/verify_mcp_task_protection.py`.
真实验证检查三个客户端 两个任务交替编辑 第三个任务共享查询 持久排队 批次交接 旧凭证失效和 PIE 保护.
真实验证不修改或保存项目资产.
独立游戏或服务器进程属于后续运行测试隔离阶段.

SSE 返回使用 `HTTPResponse.read1` 按可用字节块读取 再组合完整 UTF-8 行 小事件不等待连接关闭 大姿势消息不逐字节重复复制 整个实际请求完成前仍保持任务占用 传输中断不视为调用完成

### Perforce 票据路径

登录脚本 命令行与 UE 必须使用同一份 `P4TICKETS` 文件 Windows 用户环境与 Perforce 用户设置应保持一致 启动脚本读取已持久配置的用户票据路径 并清空当前启动进程中可能过期的 `P4PASSWD` 不将密码或票据放进命令行参数 不放宽资产写入检查
