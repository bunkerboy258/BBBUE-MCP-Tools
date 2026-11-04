# BBBUE MCP Tools

2026-11-05 骨轨复制入口新增 `match_source_timing` 显式选项 支持无曲线 通知及标记的同骨架动画原位同步源帧数与帧率 不删除资产或断开引用。保存前核对全部骨轨与元数据 实际资产回读结果见工具返回。不以此替代 PIE 视觉验收。接口说明见 [动画迁移](Docs/BBBAnimationMigrationMCP.md)。

2026-11-04 新增 `monster_gore.import_special_infected_gore`。按身体 内部组织 分批断点和配置四阶段交付已批准的 Blender 烘焙资源 保持原骨架与绑定。支持每变体共享图集父实例及八区制作遮罩 不修改玩法或动画配置。十一项毁伤入口边界检查通过 四种特感正式导入保存回读均为 ready 未执行 PIE 或战斗画面验收。见 Docs/BBBMonsterGoreMCP.md。

2026-11-04 材质不可达节点清理统一使用 `editor.prune_unused_material_expressions`. 原 `material.delete_unused_expressions` 不再公开. 仅遍历明确自有材质的输出依赖 解除不可达表达式及其图节点的根引用 从表达式集合移除并迁入瞬态包 避免 UE5.8 原生删除接口的根引用断言. 保留可达节点及全部输入连接 编译后保存并回读节点数量. UA 皮肤与衬衫分别清理 6 和 5 个不可达节点 已完成编译 保存及回读 未运行 PIE 或画面验收.

2026-11-04 新增 `runtime.apply_scene_quality`。在 PIE 通过实际 GameUserSettings 应用画质并回读设置类及渲染参数 不保存用户配置或资产。已同步入口 契约与工具基线。UE5.8 实机三档回读通过 项目设置类正确应用 TAA TAA TSR 和 1 1.5 2 毫秒动画预算 全部 33 个感染者表现网格接入预算。1080P 为输出尺寸 低中高内部渲染比例分别为 75 85 100。未以编辑器采样宣称打包帧率。

2026-11-04 几何表面采样路径校验支持中文资产目录和包名，保持明确 Game 包路径及任务临时输出限制；用于读取实际服装在正式持枪姿势下的蒙皮表面。语法检查通过，资产采样结果随调用回读。

UE5.8 编辑器工具与任务调度。固定入口默认 `http://127.0.0.1:8000/mcp`。

## 调用

| 入口 | 用途 |
| --- | --- |
| `manage_operator` | 登记任务、更新等级、结束会话 |
| `find_tools` | 搜索目标；首项提供参数 |
| `describe_tool` | 查询单项契约 |
| `submit_batch` | 提交一至十六项操作 |
| `inspect_tasks` | 查询占用、进度与结果 |
| `control_task` | 收尾、恢复与宿主管理 |

已知工具 ID 直接提交。新目标先搜索。短调用读取 `results` 与 `proof`；长调用按返回的 `next` 继续。`needs` 提供待修正字段与类型。`detail=true` 展开完整证据，`operators=true` 展开干员池。

```python
from MCP.mcp_call import McpSession

with McpSession(task="核对资产") as session:
    result = session.submit_batch([
        {"tool": "editor.inspect_dirty_packages", "arguments": {}}
    ])
    if result["status"] in {"queued", "running"}:
        result = session.wait_batch(result["batch"])
    print(result)
```

聊天通过独立 `conversation_id` 恢复归属。Codex 在提供 `task` 时采用 `CODEX_THREAD_ID`。登记任务为单行二十字以内，默认二级；零级最高，同级按提交顺序调度。会话结束使用 `manage_operator(action="finish")`。

## 执行

编辑批次自动校验、编译、保存、回读并释放资产。同一资产保持操作顺序，独立资产继续执行。故障范围由网关后台恢复；结果记录与资产占用独立维护。

测试批次使用 `environment="test"` 和 `test_options={"map":"/Game/Maps/Acceptance"}`。测试宿主直接读取原项目已保存资产，默认容量两组。后续批次携带返回的 `test_host`；完成后用 `control_task(action="close", batch=...)` 回收所属测试。

正常关闭共享编辑器使用 `control_task(action="shutdown_host")`。零级支持 `pause_operator`、`resume_operator`、`cancel_blocker` 和 `terminate_host`；暂停默认六十秒，上限三百秒。

## 启动与更新

环境为 Windows、UE5.8、项目编辑器模块、Python 与 `requests`。项目 Python 搜索路径指向本仓库 `Scripts`，由 `init_unreal.py` 接入独立常驻服务。

```powershell
.\Scripts\MCP\Start-BBBMcpService.ps1 -ProjectPath '<uproject绝对路径>' -InstallAtLogon

$hostInfo = & .\Scripts\MCP\Start-UE58OfficialMcpEditor.ps1 `
    -ProjectPath '<uproject绝对路径>' `
    -EnginePath '<UE5.8根目录>' `
    -PerformanceProfile Balanced
$env:BBB_MCP_URL = $hostInfo.Endpoint
```

默认档位为 60 FPS、Normal。手动打开项目共用 `BBBMcpEditorStartup.start_editor_mcp()` 接入链。

源码版本变化返回 `TOOLSET_UPDATE_REQUIRED`。`restart` 指出待更新的 `service` 或 `host`；先交接已接收批次，再重启对应进程，回读 `source.current=true` 后继续。源码巡检间隔一秒，注册前后执行完整核验。

## 参考

- [公开契约](Docs/UnrealMcpCanonical.md)
- [调度与恢复](Docs/BBBMcpTaskProtection.md)
- [项目依赖](Docs/ProjectDependencies.md)
- [第三方动作](Docs/BBBExternalMcp.md)

## 本轮更新

2026-11-04：新增独立弹窗通道与原生模态循环桥，control_task 支持 inspect_dialog/respond_dialog；提示选项按快照、归属及等级提交，原批次继续保存回读。九项弹窗契约检查及原生编辑器模块编译通过；真实共享宿主已回读模态窗口，公开服务与宿主源码版本一致。

2026-11-03：全目录与缓存统一校验范围声明；参考回放补齐会话范围。声明错误在发布前独立记录，参数范围错误返回补参字段；当前地图单独核验已保存包，打开地图合并当前与目标范围并支持 Entry 和临时空地图。源码及原生目录静态覆盖、专项契约检查通过。

2026-11-03：复用目录版本、精确 ID 直达、源码指纹增量巡检、客户端身份轻量加载；版本失配返回明确重启范围，状态版本包含源码变化。地图查询与打开分别统一为 `scene.get_current_level` 和 `scene.load_level`；补齐写入范围并移除编辑器目录中的技能管理与文件写入入口。静态语法、范围覆盖与引用检查完成。

2026-11-04 普通关卡构建: 新增保留源材质的原生 HLOD 单簇构建 光照有效性检查 纹理流送组件构建和反射捕获入口 模块编译通过 DeadCity 已完成 CPU Production 整图光照与反射捕获 保存重载后光照及非空体积光照有效 未构建对象和纹理流送组件均为 0 全部 17 簇有效 官方 Slate 短时 PIE 角色截图已核对 尚未进行 2K120 性能验收 详见 Docs/BBBLevelBuildMCP.md

2026-11-04 `editor.configure_inner_outline_material` 原位构建自有后处理材质 双模板组分别提供白色与橙色可见内侧轮廓 独立宽度和强度参数 支持新增或更新后处理材质 不创建兼容入口 工具语法核对通过 实际材质已保存且六个标量及橙色参数回读一致 完整材质再次编译后无新增编译错误 未运行游玩或画面验收。

GPU 分析改为 prepare、等待至少 60 帧、连续 capture、最后 restore；避免将绘制标记切换触发的预阴影缓存重建误判为稳定开销。流程和实测边界见 [BBBGpuProfileMCP](Docs/BBBGpuProfileMCP.md)，专项回归检查通过。

动作左手基准使用现有 Control Rig 求解，仅修改左臂并保留原手指及右臂。FAL 装备、换弹及 Mossberg 三段装填已原位烘焙保存，公共握持端点位置误差小于 0.005 厘米，逐发装填手指接缝误差小于 0.00004 度，插入段人工关键帧文件哈希保持；未运行 PIE，观感待人工审核。制作契约见 [BBBActionLeftHandAlignmentMCP](Docs/BBBActionLeftHandAlignmentMCP.md)。

2026-11-04 僵尸行为步态: `animation_graph.configure_fact_movement_styles` 分别接收 `patrol_style_paths` 和 `chase_style_paths` 两组各三套速度混合 巡逻与追击不再由同一组输入构图。三份待机与固定移动风格共用索引 起步和停步使用分开的速度门槛 原地转身限定在接近静止时。原生编辑器构建通过 两份正式动画蓝图均无警告编译保存 采样骨盆及手臂腿部的移动循环首尾误差低于 0.03 cm 和 0.08 度 现有十项动画图工具检查通过。未启动 PIE 未进行视觉验收。接口说明见 [BBBAnimationGraphMCP](Docs/BBBAnimationGraphMCP.md)。

2026-11-04 僵尸动画工具按原始秒数采样普通与爬行攻击及死亡。移除动作时间重映射参数。移动周期按原片段长度配置并支持三风格速度向量。Mass 行为探针可选择安全的原生状态机读取与八骨轨迹采样。入口边界回归覆盖源时间参数与拒绝旧重映射参数。

工具入口回归 16 项通过。两轮正式场景各约 10 秒采到 33 只僵尸的真实行为与骨骼事实。两种普通攻击的采样时间斜率均为 1.000 并在原始接触时刻判伤。循环倍率未超出 0.8 到 1.2。设定 60 fps 上限时探针下实际约 32 到 35 fps 此数据不作为稳定帧率或性能基准。

换弹制作预览可独立同步正式枪体片段速度和显隐通知；隐藏区间覆盖首尾插值帧，避免临时弹药与原模型同时显示。已刷新12把上线枪械的14段预览并回读隐藏区间，全部Control Rig与变换关键帧保持。未运行PIE；契约见 Docs/BBBActionLeftHandAlignmentMCP.md。
