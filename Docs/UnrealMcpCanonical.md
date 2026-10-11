# MCP 调用契约

## 五个公开接口

| 接口 | 参数 | 返回 |
| --- | --- | --- |
| `find_tools` | `query`，可选 `limit=8` | ID、用途、权限 |
| `describe_tool` | `tool` | 单项参数结构、权限、世界约束 |
| `submit_batch` | `operations`，可选 `label`、`environment`、`test_options` | 批次编号和状态 |
| `inspect_tasks` | 可选 `batch`、`detail`、`after_revision`、`wait_seconds` | 当前占用或本客户端批次 |
| `control_task` | `action`，可选 `batch`、`confirmation` | 控制结果 |

`operations` 为一至十六项 `{"tool":"领域.函数","arguments":{}}`。网关先验证全部参数，再接收批次。

`action` 为 `cancel`、`review`、`resume`、`close`、`shutdown_host`。取消适用于尚待派发的批次。

`environment` 默认为 `editor`。`test` 使用原项目受限宿主，接受读取与运行世界操作。首次批次返回 `test_host`；PIE 或采样活动期间，后续批次携带该身份继续操作。测试流程结束后回收宿主。

首次启动的 `test_options` 必须提供 `map`，可选 `rendering=false`、`audio=false`、`players=1`、`net_mode="standalone"`。网络模式还支持 `listen`、`client`，玩家数量一至八。后续提交使用 `test_host`，沿用启动设置。测试端口和输出由网关分配。

## 默认读取

`inspect_tasks()` 返回 `revision`、`host`、`status`、`available`、`queued`、`pie`、`activities`、`dirty`、`tests` 和 `next`。

存在占用时，`occupant` 给出批次、用途、状态与 `mine`。当前客户端还有活动批次时，`batch` 给出状态及等待原因。详细证据通过 `detail=true` 展开。

同一业务版本可等待最多六十秒。SDK 单次等待最多三十秒；心跳保持客户端身份，业务变化更新版本。

## 结果

| 状态 | 含义 | 下一步 |
| --- | --- | --- |
| `queued` | 参数通过，等待执行或活动完成 | 等待状态版本 |
| `running` | 正在派发 UE 操作 | 等待结果 |
| `starting` | 正在初始化所属测试宿主 | 等待结果 |
| `finishing` | 正在核验输入并回收测试宿主 | 等待结果 |
| `completed` | 全部调用完成，需等待的活动结束 | 读取结果和领域完成证据，关闭批次 |
| `rejected` | 明确拒绝，带原因与证据 | 修正参数或前置条件 |
| `review` | 部分执行、结果待核实或存在本批次待保存包 | 回读、处理并确认 |
| `cancelled` | 派发前取消 | 关闭记录 |
| `closed` | 核实流程完成 | 关闭记录 |

结果按操作顺序排列。`completed` 数字表示调用完成数量，异步工具的 `requested` 表示请求已发起。采样状态、有效文件、测试日志、编译或资产回读负责确认实际业务结果。

测试详情提供 `process_id`、`input_version`、`input_stable`，运行期间按需回读 `host_state`。输入范围为地图的包依赖闭包、参数中的显式资产路径与项目代码配置。版本使用文件身份、尺寸和时间记录；范围内变化标记 `TEST_INPUT_CHANGED`，下一步重新提交测试。

`host_status` 表示测试宿主阶段。测试输出交付后对首次批次使用 `close`，结束所属测试世界并清理对应目录；后续批次分别关闭结果记录。测试结果待验证时保留证据，资产编辑继续调度。

传输中断后，连接层使用原凭证重连并查询已提交批次。重连后的结果用于决定后续操作。

## 连接和权限

连接初始化返回私有 `bbb/client_key`；长连接每三十秒续期。客户端超时为三百秒。凭证属于连接层，AI 使用公开工具即可完成调度。

官方 UE MCP 在随机私有地址执行具体工具。公开目录使用稳定 ID，注册类哈希由后端解析。

权限按实际副作用分为 `read`、`write`、`pie`。世界约束为 `any`、`editor`、`pie`。预览参数与状态查询按本次参数解析权限。资产修改继续通过 `BBBAssetWritePolicy` 检查实际源控状态与独占归属。

## 开发与验收

`BBBMcpBootstrap` 统一注册。`BBBMcpCapabilities` 维护路由、参数契约、读写分类、明确写入目标与原生依赖。`MCP/mcp_jobs.py` 维护单宿主批次归属；`mcp_test_hosts.py` 协调项目测试，`mcp_test_process.py` 提供 Windows 进程权限与回收。

异步流程使用 `register_activity(id, status_callback, blocking=True, wait=True)`，回调返回实际状态。有限采样等待完成后续跑；持续录音与常驻探针使用 `wait=False`，由所属客户端显式结束。文件导出可登记为 `blocking=False`，并继续提供文件完成证据。

扩展同步更新 `Tests/tool_schema_baseline.json` 与所属领域文档。隔离测试先验证分类、排队、恢复与结果边界，再执行 `verify_live_mcp.py` 和 `verify_mcp_task_protection.py`。

依赖诊断使用 `runtime.inspect_mcp_dependencies({"tool":"目标 ID"})`。复杂领域参数读取对应专用文档。
