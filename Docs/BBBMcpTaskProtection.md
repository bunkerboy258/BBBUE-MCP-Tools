# 调度与恢复

## 归属与推进

原项目使用一个共享资产编辑宿主。独立测试宿主读取同一项目的已保存资产，采用受限权限、独立端口和输出目录。

批次登记维护客户端、声明范围和实际完成数量。队列优先派发可执行工作；异步等待让出执行槽。范围相互独立的编辑继续推进，只读查询共享实际状态。

短调用在提交响应中返回结果。长调用按自身版本等待。执行槽随执行与核实边界释放；已完成记录进入有界重放保留。

## 需要处理的状态

| 状态码 | 处理动作 |
| --- | --- |
| `TARGET_ALREADY_DIRTY` | 所属任务保存目标内容 |
| `RESULT_REVIEW_REQUIRED` | 所属任务核实受影响范围 |
| `WRITE_SCOPE_CHANGED` | 核对实际新增范围与声明目标 |
| `PIE_OWNED` | 沿所属世界继续，独立测试使用 `test` |
| `ACTIVITY_RUNNING` | 按批次版本等待活动完成 |
| `TEST_HOST_WAITING` | 等待测试容量，继续编辑或准备 |
| `TEST_INPUT_CHANGED` | 按新输入版本重新测试 |
| `GATEWAY_RESTARTED` | 使用原身份核实中断批次 |
| `HOST_EPOCH_CHANGED` | 回读新宿主与相关资产，完成核实 |
| `HOST_DRAINING` | 读取身份与占用，安排交接 |

## 核实

1. `inspect_tasks(batch=..., detail=true)` 读取实际完成范围。
2. 通过领域工具回读，保存或处理本批次内容。
3. `control_task(action="review", batch=...)` 获取当前确认。
4. `control_task(action="resume", batch=..., confirmation=...)` 完成核实。

确认绑定宿主和本批次相关状态。原客户端凭证可恢复归属；任务租期结束后，其他客户端通过明确核实接管。

## 验收

隔离测试覆盖连接、丢失响应、重启恢复、范围、等待与保存边界。`benchmark_mcp_workflows.py` 记录固定语料发现率、契约可用性、公共轮次和上下文量；真实任务时间线提供综合耗时。

`verify_mcp_workflows.py` 验证短查询、嵌套参数、保存回读和双客户端交接。`verify_mcp_parallel_tests.py` 验证两组测试与编辑同时推进。验收输出位于指定任务目录，完成交付后逐项清理。
