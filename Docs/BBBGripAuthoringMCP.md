# 武器双手握姿正式制作流程

## 2026-10-19 人工逐把制作

同一 `grip.author_weapon` 入口新增 `manual_prepare` 和 `manual_apply`。实现为 `Scripts/BBBGripManualAuthoring.py`，复用型号正式 LS、Rig、AS，不创建副本。

- `manual_prepare` 从正式 AS 读取起始姿势，将型号 Rig 改为三十根指骨逐节 FK、右腕 FK、左腕 IK 与左肘方向控制器。手指控制器跟随父骨，右上臂和前臂没有编辑控制器。重复打开保留已经制作的内容，不重置。
- 前台在第 0 帧编辑。`fk_<指骨>` 只旋转；`fk_hand_r` 只调整腕部旋转；`hand_l_ik_ctrl` 调左手位置和角度；`elbow_l_pv_ctrl` 调左肘方向。武器绑定的 Transform 轨道调整挂接，编辑后在当前帧打键并保存 LS。
- `manual_apply` 必须在当前制作序列第 0 帧运行。读取实际 Rig 和已生成武器，保留手工控制值并统一静止帧，烘焙正式 AS，比较烘焙姿势及冻结的右臂，再写正式 DataAsset。手指位移被拒绝，左手位置偏移按 hand_r 空间换算，旋转按实际武器左手插槽换算。
- 手工模式拒绝 `solve/save/save_draft/adopt` 覆盖控制器。不会调用自动拟合，也不把烘焙回读等同于人体自然度、无穿模或运行验收通过。
- 每次只准备当前型号；人工说“应用”后才应用配置和推进下一把。挂接改变后，动作衔接需要依据新基准处理，不能从静态握姿应用推断动作已经完成。

人工应用的指骨及右腕平移检查直接读取 FK 控制器的实际平移增量。控制器关键帧保存的是相对 Offset 的增量 非零平移超过 0.01 厘米时拒绝应用 不能把初始零增量与骨骼局部位置直接比较 否则未移动的指骨也会被误报为 MANUAL_FINGER_TRANSLATED。

2026-10-19 首次真实人工应用已完成 Rifle01 的右拇指第二节约 17.3092 度修改 正式 AS 及第 0 与第 1 帧控制器回读一致 右上臂和前臂保持。Rifle02 的 manual_prepare 已实际完成 使用其现有正式握姿起步 未改写 Rifle02 的运行动画和配置。未运行 PIE 或额外测试 不将本次读回扩大为全部动作或运行验收。

入口：`grip.author_weapon`。实现位于 `Scripts/BBBGripAuthoringToolset.py`，离线数学位于 `Scripts/BBBGripAuthoring.py`，邻指几何位于 `Scripts/BBBGripFingerConstraints.py`，稳定手部截图位于 `Scripts/BBBGripCaptureTools.py`。它复用正式网格采样、Control Rig、Sequencer、动画烘焙和接触拟合工具。

## 2026-10-18 掌空间自然度方向约束

`matrix_quaternion` 严格要求有限的三乘三正交且行列式为一的纯旋转矩阵，拒绝四乘四齐次矩阵、缩放、剪切和镜像。临时共享卷曲原型曾误传完整局部矩阵，使目标组件姿势与输出四元数不同；求解器必须传入旋转子矩阵，并从最终输出旋转重新构造实际组件姿势参与全部方向与接触检查。新增拒绝错误矩阵及旋转往返回归，方向与制作专项共 30 项通过。

Rifle02 与 Rifle03 第一轮几何检查通过后，人工仍发现食指弯折、拇指向下及三指末端方向散乱。实际接触、无穿透和局部关节角不能代替掌空间方向检查。新制作输入可配置 `natural_pose.axes`，正式 `solve` 与烘焙后实际回读均通过同一 `palm_axis_audit` 检查，失败项进入 `palm_axis:<name>`，阻止运行配置写入。

每项明确 `name`、`hand`、`bone`、骨局部非零 `axis` 与 `maximum_degrees`。与已确认握姿比较时提供 `reference_in_hand` 三维方向；检查两根当前骨轴并排时提供 `other_bone`、`other_axis`。两种比较必须二选一。算法把当前骨轴转换至实际手掌空间，方向上限必须有限且小于 180 度。骨轴应按真实子骨位移或明确末节指腹语义点构造，不假设全部指骨的 X 轴指向指尖。

拟合阶段应使用共同卷曲平面和中末节共享参数，减少各骨独立扭转自由度；方向审核作为保存门槛，不替代接触、闭合体深度、实际面片交叉和指间表面间隙。Rifle01 原有已确认排列不等于完全平行，新枪的并排目标与相对参考偏角应分别声明，不能把同一姿势同时认定为两种互相矛盾的边界。新增四项方向回归与既有 25 项制作回归通过。真实 UE5.8 重新采样被人工否决的 Rifle03 动画，24 条方向约束中明确拒绝 14 条：拇指三节方向偏差约 64.635°、66.355°、68.581°，与离线候选复查一致；自然度修正版及人工复核继续进行。

## 2026-10-18 新建握姿 Rig 的骨数组契约

`_rig_graph` 使用现行 `/Script/ControlRig.RigUnit_SetTransformItemArray`，其 `Items` 是 `TArray<FRigElementKey>`，与生成的逐骨项目数组和 `Transforms` 一一对应。旧 `RigUnit_SetTransformArray` 的 `Items` 是包含 `Keys` 的 `FRigElementKeyCollection`；将裸数组字符串传入旧结构会让新建 Rig 的控制器有值、骨骼仍保持参考姿势。生成图回归核对节点类型、每根骨的项目、变换数组长度和逐项连线，不依赖已有 Rifle01 资产掩盖新建流程问题。

25 项制作回归通过。UE5.8 共享宿主原生替换 Rifle02 的 ApplyPose 后，正式保存及原生回读通过：姿势最大位置误差 1.11e-5 cm、角度误差 0.000254°、左腕目标误差 1.67e-5 cm，武器定义匹配且几何审计通过。这验证了现行节点的求解与烘焙；人工握姿外观另行确认。已有 Rig 的节点修正通过原生图工具执行并重新回读，不能将关键帧控制器读回成功视为骨骼求解成功。

## 低思考深度会话的执行约定

先读目标项目根 Law、Items Law 和本文。登记 MCP 干员，核对项目、宿主进程和端口，按正常 MCP 批次调用入口。

1. 对明确型号调用 `inspect`，只执行返回的 `next`。
2. `next.action` 是本入口的动作；保留 `weapon_root`、`recipe_path`，设置返回的动作即可。`solve`、`save`、`audit`、`adopt` 另提供已核验的 NumPy Python。
3. `next.type=edit_recipe` 表示需要完善正式制作配置。只调整返回字段中与失败对应的接触区、姿势或边界；输入不清楚时请人类指定，不自行扩大阈值，不将算法候选标成已审核。
4. `next.type=visible_editor_handoff` 表示数值宿主没有窗口或没有渲染。保存并交接共享资产编辑宿主后再执行 `review`。
5. 只有人类明确认可当前结果，才调用 `accept` 并原样记录意见。修改配置、依赖或制作资产后，原审核不能自动沿用。
6. `next=null` 且状态为 `ready_for_runtime_acceptance` 时，握姿制作阶段结束；主角色运行验收仍然是 `pending`。
7. 工具异常应核对批次保存证据及实际资产，再决定下一步。已经成功保存的操作不盲目重放。常规几何未通过属于明确结果，工具阻止接入配置。

后续会话可直接使用的指令：

> 阅读 Docs/BBBGripAuthoringMCP.md。对我指定的武器调用 grip.author_weapon，先 inspect，按 next 执行。使用该型号正式制作源和已确认的接触区域，完成数值检查与制作交接；人工反馈前保持审核待定。报告工具未通过或不能确定的项目。

## 输入和动作

| 参数 | 用途 |
| --- | --- |
| `weapon_root` | 明确自有武器型号包目录，编辑范围限定到这一型号 |
| `recipe_path` | 项目相对路径，必须直接位于本型号 `Source/Animation`，以 `.json.source` 结尾 |
| `action` | `initialize`、`inspect`、`solve`、`save`、`audit`、`review`、`accept`、`adopt` |
| `python_executable` | 已安装 NumPy 的外部 `python.exe`，工具以参数数组启动正式脚本，不使用 shell |
| `review_note` | `accept` 使用的人类明确复核意见 |
| `definition_path` | 仅新建制作源时使用的明确武器定义 |
| `character_mesh_path` | 仅新建制作源时使用的实际运行角色网格 |
| `reference_animation_path` | 仅新建制作源时使用的公共绝对参考动画 |

当前已核验的数学运行环境：

```text
C:/Users/silencgai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe
Python 3.12.14 / NumPy 2.3.5
```

`C:/Python314/python.exe` 负责当前 MCP 服务，但没有 NumPy，不能用作数学工作器。环境变更后重新核验解释器，不临时在编辑器内安装依赖。

### 已有 Rifle01 的只读检查

```json
{
  "weapon_root": "/Game/_Project/Characters/BBBC_UA/Items/Equipment/Rifle/Rifle_01",
  "recipe_path": "Content/_Project/Characters/BBBC_UA/Items/Equipment/Rifle/Rifle_01/Source/Animation/Rifle01_HandGrip_Authoring.json.source",
  "action": "inspect"
}
```

调用 `audit` 时使用相同参数并提供 `python_executable`。审计不修改资产和制作源。

### 初始化新型号

下面给出 Rifle02 的参数形式。只有实际任务已明确包含该型号时执行。

```json
{
  "weapon_root": "/Game/_Project/Characters/BBBC_UA/Items/Equipment/Rifle/Rifle_02",
  "recipe_path": "Content/_Project/Characters/BBBC_UA/Items/Equipment/Rifle/Rifle_02/Source/Animation/Rifle_02_HandGrip_Authoring.json.source",
  "action": "initialize",
  "definition_path": "/Game/_Project/Characters/BBBC_UA/Items/Equipment/Rifle/Rifle_02/DA_ModernWeapons_Rifle_02",
  "character_mesh_path": "/Game/_Project/Characters/BBBC_UA/BasicOutfit/Meshes/SK_UA_BasicArms",
  "reference_animation_path": "/Game/_Project/Characters/BBBC_UA/Animation/Lyra/Rifle/MM_Rifle_Idle_Hipfire"
}
```

初始化只产生一份制作源，读取当前武器网格、偏移与公共参考动作中的三十根手指种子，不创建运行时资产。接触组和邻指约束保持待填写；不从 Rifle01 复制另一把枪的面片编号。文件已经存在时拒绝初始化覆盖。

## 唯一制作源

文件是标准 JSON。`.source` 阻止 UE 自动导入器把资料误当成 DataTable。当前格式为 `format=BBBGripAuthoring`、`schema=1`，没有历史格式兼容执行分支。

| 字段 | 内容 |
| --- | --- |
| `definition`、`character_mesh`、`weapon_mesh`、`reference_animation` | 明确资产路径 |
| `rig`、`sequence`、`animation` | 本型号 `Animation/work` 与 `Animation/Sequence` 正式输出 |
| `attachment_socket`、`left_socket` | 实际挂接及左手目标插槽 |
| `calibration` | 挂接、左手偏移、固定或求解的掌面配置 |
| `pose` | 固定或拟合模式及三十根手指绝对局部四元数 |
| `fitting` | 十指明确接触组及搜索范围 |
| `neighbors` | 左右各三对相邻手指的关节间距与实际指面约束 |
| `neighbor_refinement` | 可选明确骨骼的有界局部旋转修正 |
| `checks` | 本型号实际验收门槛 |
| `solution` | 当前有效完整姿势、偏移、几何结果和输入摘要 |
| `validation` | 实际动画与制作底稿的回读及输出摘要 |
| `review` | 人类审核意见及其对应的输出摘要 |

长度单位为厘米，角度单位为度，旋转四元数顺序为 XYZW。十项变换依次为位置三项、四元数四项、缩放三项。三十根指骨采用 `thumb/index/middle/ring/pinky`、`01/02/03`、`l/r` 命名。

输入摘要同时覆盖制作配置、角色与武器网格、公共参考动作文件、实际插槽链和数学工具源码。输出摘要覆盖 Rig、Sequencer、运行握姿和武器配置中的实际引用及偏移。判断依赖内容，不凭文件名或上一次会话结论。

制作源在 `Saved/temp/GripAuthoring_<唯一编号>/` 中写好后原子替换唯一正式文件；不创建旧文件副本。每次工作器调用的请求、采样、结果自动删除。

## 掌面和腕部校准

`calibration.mode=fixed` 使用明确保存的现有偏移。`mode=fit` 先求右掌对应的枪体平移，再求左腕相对枪体的平移。旋转使用明确已有值；这一阶段不自动猜测手腕朝向。

运行时链始终包含：

```text
角色 hand_r
→ 挂接插槽局部变换
→ SpawnOffset
→ 武器插槽父骨组件变换
→ LeftHand 插槽局部变换
```

左手位置在 `hand_r` 空间加 `LeftHandIKOffset`，左手旋转在插槽旋转之后乘 `LeftHandIKRotation`。工具直接读取父骨和局部变换，不能将插槽局部位置当成武器组件位置。

`mode=fit` 的 `right_palm` 与 `left_palm` 都需要：

```json
{
  "vertex_ids": [1001, 1002],
  "weapon_triangle_ids": [2001, 2002],
  "surface_normal_sign": -1,
  "target_gap_cm": 0.06,
  "clearance_cm": 0.02,
  "translation_limits_weapon_cm": [[-1, 1], [-1, 1], [-1, 1]]
}
```

上例编号仅说明字段形式，必须替换为当前采样中已确认的掌面顶点及目标部件面片编号。校准顶层另设 `steps_cm`，例如 `[0.2, 0.05, 0.01]`。平移范围在武器组件轴中定义，必须根据当前枪体确认。需要更大变化时先检查接触区和挂接方向。

左臂采用解析双骨求解，只改上臂、前臂和腕骨旋转。目标不可达或弯曲平面退化时明确失败，禁止拉长骨骼。辅助 IK 骨匹配手腕位置和朝向。

## 指腹接触与邻指约束

`fitting.contacts` 使用 [BBBGripPoseFitting.md](BBBGripPoseFitting.md) 的明确顶点、面片、法向和局部关节范围。十组必须完整覆盖三十根手指骨且不能重复。触发手指等特殊部位可明确设置本组 `minimum_contact_patch_vertices`；不要为满足统一接触数量把它吸向握把。

`selection_reviewed` 是接触点选择的人工审核标记。已有最终握姿的外观认可不等于逐个候选顶点的语义已经审核，保留两者的真实状态。

`neighbors` 至少明确六组：每侧食指—中指、中指—无名指、无名指—小拇指。常规选中中节、末节，避免把相邻的掌蹼误纳入独立指面。

```json
{
  "name": "ring_pinky_r",
  "first_bones": ["ring_02_r", "ring_03_r"],
  "second_bones": ["pinky_02_r", "pinky_03_r"],
  "minimum_weight": 0.5,
  "surface_gap_cm": [0.02, 1.5],
  "joint_pairs": [
    {"first": "ring_02_r", "second": "pinky_02_r", "distance_cm": [1.5, 2.1]},
    {"first": "ring_03_r", "second": "pinky_03_r", "distance_cm": [2.2, 2.8]}
  ]
}
```

此数值仅用于解释 Rifle01 的配置形式。扳机食指与中指的分离应按真实持枪结构独立设置。

指面审计用三角形分离轴检查，包含共面分离轴；距离包含边与边的最短距离，不只检查顶点。输出交叉数量、原始面片编号和关节间距，便于定位。约束是制作边界，不是人体解剖证明。

可选 `neighbor_refinement` 包含 `bones`、`limits_degrees` 和 `steps_degrees`。范围形状为每骨三轴各一对上下界，必须包含零。修正同时保持明确指腹接触和完整闭合清除区域的代价；最终仍独立重算全部接触、实体包含与邻指交叉。

## 保存和验收顺序

`solve` 只更新制作源。`save` 严格执行：

1. 求解几何门槛通过，依赖摘要仍一致，目标没有未交接脏包。
2. 创建或更新可编辑 Rig 与 Sequencer。所有组件姿势控制器使用官方数组设置节点，输入为独立公共参考动作，源轨不参与最终静态输出。
3. 在第 0、1 显示帧写入相同完整组件姿势，按 30 FPS、两个显示帧范围正式烘焙，得到三个相同采样。
4. 回读运行动画的首、中、尾姿势，回读实际控制器关键帧，并包含控制器初始偏移的合成。
5. 数值通过后保存武器握姿引用、挂接和左手偏移，再核对实际配置。
6. 记录当前验证结果，等待人工审核。重复执行已通过且摘要未变化的保存返回 `unchanged=true`。

姿势、控制器和装备配置的旋转回读统一先归一化四元数，再计算忽略符号的最短角度差；浮点存储导致的长度偏差不作为姿态误差。2026-10-18 的真实配置回读曾在未归一化时误报约 0.02239 度，归一化后约 0.00000171 度，原 0.02 度门槛保持不变；23 项制作回归和实际烘焙资产回读通过。

静态握姿必须是无 Root Motion 的绝对 AnimSequence，没有曲线和通知。正式编辑器骨架、插槽和偏移不由截图反推。默认门槛在新建配置中明确写出，可以按当前制作需求审核调整。

完整表面检查使用所有选中的真实手部顶点及整枪面片，并对闭合连通组件进行独立包含查询。开放或非流形部位保持不确定。`wholeWeaponSolidPenetrationProven=false` 和 `runtimeAcceptance=pending` 不因制作流程完成而变成已通过。

`adopt` 用于把已经存在、人工确认要保留的握姿输出及底稿纳入当前流程：读取真实姿势并执行同一审计，不重新拟合或烘焙。输入一致时再次采纳保持不变；输入改变时需要明确重新采纳或求解。

## 固定观察与亮度

`review` 在带窗口的编辑器打开本型号 Sequencer 并停在第 0 帧。NullRHI 宿主返回明确的窗口交接要求。

打开底稿使用 `LevelSequenceEditorBlueprintLibrary.open_level_sequence` 并检查布尔返回值；失败时报 `GRIP_REVIEW_OPEN_FAILED`。2026-10-18 已在前台 HighThroughput 宿主通过正式 `review` 入口真实打开 Rifle01 底稿，几何失败状态保持原值，打开预览不改变审核结果。

需要图像时复用 `control_rig.capture_attachment_pose`。该入口新增：

- `target_bone`：默认 `hand_l`，右手用 `hand_r`。
- `exposure_bias`：默认 0，允许 -6 到 +6 档；提高到 1 或 2 可增加亮度。相机采用固定手动曝光，以 `2^exposure_bias` 的线性场景颜色倍率应用补偿，避免项目关闭眼适应时原生曝光补偿失效；返回值包含实际倍率。
- `action`：默认 `start`，跨帧预热并返回完整的 `next` 状态查询参数；批次完成后按 `next` 调用 `status`，确认状态为 `completed` 且 `temporaryActorsDestroyed=true` 后使用图像。

截图固定姿势预热 60 帧，等待多个真实渲染帧后导出，关闭动态全局照明、反射和运动模糊以稳定比较。首个请求返回 `pending` 是正常状态，MCP 会等待登记活动结束；状态查询负责确认真实图像和清理结果。先使用 `app.StartPIE` 启动 PIE 或 Simulate，再提交截图；`environment=test` 本身不会自动开始 PIE。

跨帧活动期间，外层批次可能返回 `queued/ACTIVITY_RUNNING`。按外层 `next` 继续 `inspect_tasks`，等批次 `completed` 后再执行截图返回的状态查询，不重新提交原截图。正式客户端 `McpSession.wait_batch` 已处理这种继续方式。

左右手分别固定前侧、侧面和下侧视角，`camera_offset` 相对目标腕骨。附件必须使用当前武器网格、实际插槽和已校准 SpawnOffset。输出包含目标骨和曝光值，文件必须使用 `任务目录/图名.png`，位于 `Saved/temp`。该截图入口需要带渲染的 PIE；不用 NullRHI 图像充当验收。

## Rifle01 当前验证边界

2026-10-18 用户认可了右手小拇指修正后的握姿外观。本流程扩大到六对邻指后，另外检测到左手食指—中指、中指—无名指的局部面片交叉，保留原始面片编号。数值门槛因此保持失败，工具阻止再次写入运行配置；已认可的现有姿势不在此工具整理任务中自动重做。

右手无名指—小拇指间距检查通过。完整制作底稿含 68 个控制器、136 个关键帧，回读比较包含参考偏移。动画层与正式主角色动作的运行验收按后续任务安排。

## 本轮工具验收

- 75 项数学、拟合、保存门槛和相关制作检查通过；15 项 MCP 契约与结构化参数检查通过。
- 真实资产连续采纳返回 `unchanged=true`，未通过邻指门槛时保存返回 `geometry_not_passed`、`assetsModified=false`。
- 角色姿势、Rig、Sequencer 和装备配置组合摘要保持 `6e2257627600542eca2d01905df3085f0f6c8d116eaf8fba60bff857a783c950`。
- 控制器最大位置误差约 `0.00007215 cm`，最大旋转误差约 `0.00010268°`；静态帧间顶点位移为 0。
- 渲染实测用相同姿势及相机执行补偿 0、+1、0：前景平均亮度约 `70.57 → 79.82`，约 `99.86%` 的前景像素增亮。同参数重复图像的平均与最大 RGB 像素差均为 0。
- 三个截图任务均返回 `completed` 与 `temporaryActorsDestroyed=true`，模拟已结束。图像与试算文件按 Law 在本轮交付前清理，不成为长期验收输入。
- 没有新增曲线备份资产或旧路径兼容。既有通用烘焙工具的 `CurveSnapshot_*` 分支仍存在，静态握姿不走该分支；此工作不删除其它任务的历史制作资料。

## 分节指腹接触检查

握把接触可明确配置 `pad_groups`，按骨名列出实际指腹顶点编号，同时设置 `minimum_pad_contact_vertices` 和 `pad_contact_distance_cm`。每个分组独立检查接触数量，避免整根手指少数顶点接触掩盖中节或末节悬空。顶点必须存在、唯一，并对所命名骨具有至少 0.5 权重；不符合时拒绝配置。

未满足的分节接触返回 `contact_pad:<接触名>:<骨名>`；完整实体包含与邻指交叉仍独立检查。该检查不把算法选点变成人工认可，`selection_reviewed` 仍须如实保存。24 项制作回归包含中节接触而末节悬空，以及错误骨权重的拒绝验证。
