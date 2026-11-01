# 关卡导航与前台审查

所有操作要求明确 `expected_level` 与当前编辑器关卡一致，PIE 期间拒绝编辑和编辑器导航检查。

- `level.place_actor_from_class` 已可创建 `/Script/NavigationSystem.NavMeshBoundsVolume`；原生演员工厂生成有效的 200cm 立方刷体。设置其变换后回读实际范围。不要用空 Actor 或可视盒体冒充导航体积。
- `level.refresh_navigation_bounds(expected_level, volume_paths)` 通知导航系统处理边界变更，返回真实体积范围与 `building_or_locked`。请求成功并不代表构建完成；使用下一个入口核验结果。
- `level.inspect_navigation_route(expected_level, points, context_actor_path="", endpoint_tolerance_cm=100)` 对二至二百五十六个必经世界坐标逐段寻路。`points` 是厘米三元数组的数组。可明确指定 RecastNavMesh、Pawn 或 Controller 导航上下文，空值使用世界默认代理。只在导航就绪时执行；每段必须有效、非 partial、具有至少两个路径点且首尾误差不超容差，才能令 `all_segments_valid=true`。返回所有真实路径点、分段长度和当前 Recast 代理尺寸。线性关卡应同时查询起点到终点的全局最短路径和必经点分段路径，检查是否存在绕过必经区域的捷径。导航结果不能证明真实玩家通行或相机表现。
- `level.set_review_view(expected_level, camera_actor_path, location, rotation, ortho_width_cm=0, view_mode="Lit")` 使用明确的当前世界 CameraActor 驾驶前台视口。相机被设为编辑器专用。`rotation` 为俯仰、偏航、滚转角度；负九十度俯仰与正交宽度组合用于顶视。`view_mode` 支持 `Lit`、`Unlit`、`PlayerCollision`。回读相机投影、实际视口模式和驾驶关系。
- 截图使用官方 Slate Snapshot 配合 `editor.capture_editor_screenshot` 获取真实视口。`external.vision.capture_viewport` 会建立独立透视 SceneCapture，不能拿它证明正交或 PlayerCollision。
- 壳体碰撞复用 `editor.configure_static_mesh_surface_collision(mesh_path, apply_changes=true)`：启用 ComplexAsSimple、双面碰撞及所有 LOD 分段碰撞。只对本次自有壳体调用；原始第三方网格不批量改写。
- GameMode 复用 `external.game.set_game_mode(game_mode_class_path)`。方向光、天空光、锚点、审查相机复用 `level.place_actor_from_class`，类分别为 `/Script/Engine.DirectionalLight`、`/Script/Engine.SkyLight`、`/Script/Engine.TargetPoint`、`/Script/Engine.CameraActor`。

工具加入现有 `BBBLevelEditingToolset` 注册类，需通过正常宿主交接加载新函数。本次还增加了服务端 `TOOL_POLICIES` 项，常驻服务通过模块导入持有该字典；仅重启 UE 会刷新工具目录，但不会重新导入服务进程内的策略。须在无作业且原 UE 宿主正常关闭的边界，核验服务 PID 与监听端口后重新启动常驻服务，再启动前台宿主。官方启动脚本的 `--ensure` 会复用仍健康的旧服务，不能将其当成源码重载。

`inspect_navigation_route.ready` 只表示导航系统和 Recast 对象存在且当前没有构建或锁定，不能证明导航瓦片覆盖请求坐标。路线通过依据是 `all_segments_valid` 与分段返回值。边界刷新也不等价于完整构建；必要时通过官方 Slate Snapshot 定位当前编辑器的 Build 菜单，使用 `slate_inspector_toolset.Click` 执行 Build Paths，再回读局部和完整路线。构建菜单执行成功仍不能替代路线结果。

仅修改现有函数实现且契约未变时，无需重启常驻服务，但仍须正常交接并重启 UE 宿主。`BBBMcpBootstrap.register_mcp_toolsets` 对已加载的同源模块使用 `importlib.import_module`，不热重载注册工具类。UE 反射数组必须转换为 Python 原生列表再写入 JSON；若末尾序列化失败，先回读已发生的编辑和保存结果，勿直接重放整批。

不执行临时 UE Python 脚本，不在旧宿主上冒充新接口已部署。源码静态解析通过；边界刷新与路线检查已在前台宿主执行，路线检查正确拒绝未覆盖坐标，并在地面变换修正后通过局部和教学楼路线。宿主正常重启后，透视 Lit 视图返回有效 JSON，反射数组序列化修复实测通过。正交与 PlayerCollision 的视觉验收及全关卡通行仍由关卡任务单独核验，未运行自动化套件。
