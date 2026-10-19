# 双手握姿层配置

`editor.configure_hand_pose_layer` 为现有共享动画层增加逐装备的静态双手手指覆盖。它是编辑器制作能力，不增加运行时蓝图逻辑入口。

## 输入

- `main_path`：主动画蓝图。
- `base_path`：已有共享基础动画层。
- `interface_path`：包含旧单手层的动画层接口。
- `child_layer_paths`：本次明确编译保存的全部继承动画层，按父层在前排列。
- `old_layer_name`、`layer_name`：已有层与正式双手层名称。同名可用于完成部分配置，此时现有接口必须精确匹配握姿序列与双手权重三个参数。正式 Base 已有 6 节点且三个数据输入均已连接时，在任何修改之前以 `ALREADY_CONFIGURED` 拒绝重复配置，避免生成重复纯节点。
- `before_layer_name`：最终调用位置的直接下游骨骼控制层。
- `grip_getter_name`：主实例上返回 `UAnimSequence*` 的 `BlueprintPure`、`BlueprintThreadSafe` 函数。
- `left_disable_curve`、`right_disable_curve`：两条独立的握姿抑制曲线。
- `left_finger_roots`、`right_finger_roots`：左右手指分支起点；每个起点必须是相应腕骨的后代，禁止把腕骨、手臂或 IK 骨骼列为起点。

全部目标必须是已保存资产，PIE 期间拒绝执行。调用方应先核对上下游连线，确保指定位置位于主要动作 Slot、惯性混合之后，瞄准与左手 IK 之前。

## 行为

1. 验证唯一旧调用、基础层、接口与返回类型、线程安全元数据、左右手分支骨骼。
2. 将旧调用从原位置旁路，在原缓存链上恢复输入姿势；保留主图所有原节点 GUID。
3. 需要改名时重命名接口及基础层的原函数，配置 `GripPose`、`LeftGripAlpha`、`RightGripAlpha` 输入；接口编译后重新定位正式基础层图，防止向已被引擎替换的旧图写入。
4. 只重建这一基础层函数图：两个固定第 0 帧的 Sequence Evaluator 读取同一份资产，分别通过左右手指的骨骼分支混合。两个求值节点独立输出，避免动画姿势链接重复消费。
5. 两个混合节点都使用 `UseBasePose` 保留输入动作曲线，局部空间混合手指，保持身体、腕骨和根运动。
6. 主图显式暴露关联层的三个数据引脚，通过属性访问读取当前握姿快照，两条曲线分别计算 `Clamp(1 - Disable, 0, 1)`；空握姿将两边权重归零。
7. 将原调用节点移动到指定控制层之前，保留该位置的原上游节点及其它图表。
8. 原生配置后编译接口、基础层、主图并回读；Python 再按父层顺序编译所有明确目标，全部成功才开始保存。

不会新建 Montage Slot、Tick 或逐武器图分支，不会自动发现并修改其它资产。源输入姿势不依赖静态握姿中不存在的动作曲线。

## 验收与失败处理

返回值包含正式层名称、下游层、原上游节点、保留的主图节点数量、编译状态与保存清单。`runtimeAcceptance` 固定为 `pending`，表示静态图检查不能代替运行时曲线时序、低帧率、中断和切枪验收。

`GetCurveValue` 属于主实例的动画更新数据；节点插入位置不能证明曲线读取与当前姿势求值处于同一时刻。实际接入后应采样动作时间、Slot 权重、左右曲线和最终 Alpha，分别验证正常播放、中断、切枪及空配置完全透传。

原生函数本身不执行保存，Python 只在全部编译通过后调用保存。不过 MCP 的 `verified_save` 边界可能在异常协调时保存已经发生的明确目标编辑，必须以批次 `proof.saved`、`proof.dirty` 和实际图表回读为准，不能因 Python 报错就推断磁盘未改变。已保存的部分配置应通过同名正式配置完成，不恢复历史接口作为兼容路径。若仍有脏目标，先完成并行交接；工具拒绝在残留未保存修改上再次写入。保存中途失败会报告已经保存的清单，不能将部分保存报告为完成。

旧层被替换后，应另外核对原单左手专用变量与更新函数是否仍有引用。仅在引用确认后定向删除孤立定义，不能批量删除其它动画功能。

## 验证记录

本次新增了模拟宿主的 Python 行为测试，覆盖 PIE、脏资产、继承顺序拒绝写入、原生失败及编译失败不触发 helper 自身保存，以及全部编译完成后才开始保存。它不模拟 MCP 异常协调的自动保存行为。原生编译、真实动画图配置与自然运行时验收由具体使用任务记录。

## 正式层离线求值

`editor.audit_hand_pose_layer` 接收 `mesh_path`、`base_animation_path`、`grip_animation_path`、`base_path`、`interface_path`、`layer_name` 和 `alphas`。通常采用 `[0, 0.5, 1]`。基准和握姿都必须是同骨架的绝对序列，正式 Base 和接口必须已编译。PIE 期间拒绝执行。

该工具创建瞬态动画蓝图，继承 Base 的原生父类，通过外部 Linked Anim Layer 调用正式 Base 的生成类。不会复制或重新实现正式握姿层的骨骼混合。预览组件在 `EditorPreview` 世界中实际 Update、Evaluate，并严格验证执行的关联实例类型等于正式 Base 生成类。

参考姿势分别由真实 SingleNode 求值取得 Base、Grip 第 0 帧。常规双手权重之外，自动执行左手独立、右手独立和空握姿门控场景。空握姿场景明确使用零权重，验证主图已声明的非空资产门控之后的 Base 行为，不声称 Base 在空序列且权重一时会自行识别空输入。

每场景输出所有骨骼的局部位置、四元数和缩放，并分别核对手指与非手指。默认零、半、一权重分别应得到原姿势、局部球面中点和目标握姿；左右隔离不应改变另一侧。验收阈值为位置 `0.001 cm`、旋转 `0.02°`、缩放向量距离 `0.0001`。`gripDifferenceDegrees` 用于确认输入握姿相对基准确有可观察变化，避免把相同输入当成有效混合证据。

组件和预览场景通过作用域清理销毁，临时蓝图位于瞬态包，不保存资产、生成报告或在当前关卡创建 Actor。Python 比较调用前后项目脏包集合，发现变化即报错。

返回的 `mainGameplayEvaluated` 固定为 `false`：离线求值证明正式 Base 手指层的混合结果，不能代替主动画图、装备事实发布、曲线读取时序或运行时动作交接的验收。

### 2026-10-18 样板图检查

正式层已配置为 `HandPose_OverrideState`，主图原有 31 节点全部保留，调用位于 `RotateRootBone` 与 `FullBody_SkeletalControls` 之间。Base 的 6 个节点、左右各 5 个手指分支、固定第 0 帧、`DoNotSync`、`UseBasePose` 和三个明确输入引脚均已真实回读。

接口、Base、Rifle、Shotgun、Pistol、Unarmed 和主图共 7 个蓝图全部通过 `warnings_as_errors` 编译。Base 中旧左手覆盖的三个变量及 `SetLeftHandPoseOverrideWeight` 函数已在全图引用检查后删除，正式函数表中没有旧层或 `OnNewFunction_1`。主图与 Base 共 149 条属性访问没有错误。

首次真实离线求值使用 BasicArms 网格、`MM_Rifle_Idle_Hipfire` 第 0 帧与 Rifle01 的 `AS_Rifle_01_HandGrip`。批次 `9e51c4d524a5cc34` 的 6 个场景全部通过：68 根骨骼中左右手指各 15 根，输入握姿相对基准有约 `30.2600°` 的可观察变化，最大位置误差 `0 cm`、旋转误差约 `0.00000171°`、缩放误差 `0`，非手指保持不变。每个场景执行的关联实例均严格为正式 Base 生成类，项目脏包集合未变化。该结果证明层混合，不包含后续几何精修后的最终握姿或 Main 曲线时序验收。

最终握姿经独立制作序列正式烘焙后，在批次 `1000c1e28139e824` 重复全部 6 个场景，结果仍全部通过。最终输入相对基准的手指最大差异约 `30.7312°`，位置和缩放误差均为 `0`，最大旋转误差约 `0.00000242°`，非手指最大旋转误差约 `0.00000171°`。该结果仍只证明正式 Base 手指层，不代表 Main 曲线同帧或 PIE 验收。

负例批次 `df0f1a05e964e645` 对已成功的正式图重复配置，按预期以 `ALREADY_CONFIGURED` 拒绝，未产生脏包或保存。前后回读批次 `2fd3186bd5b23b14` 证明主图仍为 41 节点、34 连线，Base 握姿图仍为 6 节点、9 连线，两个 `logicSignature` 完全不变。模拟宿主测试最终共 12 项通过。
# 右腕握持增量

`editor.sample_hand_handling_surface` 只读运行瞬态包装图 `SequenceEvaluator -> 正式 HandPose_OverrideState -> 按正式配置复制的原生 ModifyBone`。参数明确给出 `mesh_path` `main_path` `base_path` `interface_path` `animation_path` `grip_path` `time_seconds` `right_hand_offset` `equipment_enabled` `left_grip_alpha` `right_grip_alpha` `selected_bones` `minimum_selected_weight` `material_indices`。`right_hand_offset` 顺序为俯仰 偏航 滚转 单位度 双手指权重是本次明确快照 不自动冒充主图曲线实测。

瞬态实例继承正式主图的原生父类 不执行其玩法图；正式握姿层生成类必须与实际关联实例完全一致 右腕节点配置必须来自已保存正式基础层且验证相同骨骼 模式 空间 旋转查询和装备门控。输出 `localBones` `componentBones` 为实际求值姿势 `sourceRightHandLocal` 来自同一动作同一秒数的原生 SingleNode 求值 `parentSpacePreMultiplyErrorDegrees` 对照父空间左乘语义。`surface` 复用既有原生 LOD0 导入顶点和真实权重 CPU 线性蒙皮 不包含 morph cloth 或 deformer。采样结果可供既有彩色三视图直接渲染 无引擎截图 无 PIE 无正式资产保存 并检查项目脏包集合保持。

本接口未注入真实玩法装备实例和枪口目标 `aimIKEnabled=false` `leftHandIKEnabled=false` `mainGameplayEvaluated=false` `fullBodyLayerEvaluated=false`。输出记录 `nativeNodeConfigurationSource` 和复制配置。它证明实际已编译握姿与右腕增量链及当前输入下表面 不代表整套主图运行验收；动作换弹阶段由调用方传入实际曲线对应权重 不能把全部时间权重一当作最终动作。

2026-10-19 原生验收在已保存正式节点配置上完成五个场景：零增量 装备禁用 非交换 `[Pitch17 Yaw23 Roll-11]` 于动作 `0.9s` 同增量于 `1.1s` 左指 `0.5` 右指 `1` 混合。父空间左乘角误差均 `0°` 零增量与装备禁用的完整组件姿势相同 非交换样本若后乘会偏 `46.8736036°` 两个秒数的源腕姿势不同。每场景产生 `2716` 个实际手部顶点 项目脏包集合保持。此结果只验收正式握姿层与正式配置的原生 ModifyBone 不包含整套骨骼控制层或主图玩法。

装备公共配置 `RightHandGripRotationOffset` 是父骨骼空间的旋转增量 默认零。角色 AnimationSystem 在游戏线程采集到事实快照 再发布到主动画实例 链接层通过线程安全 `GetRightHandGripRotationOffset` 和 `HasRightHandGripRotationOffset` 读取 不在工作线程访问装备或 DA。无装备时清零 只有装备类别有效且增量非零才启用该节点 门控不依赖左右手指的 Disable 曲线。

`editor.configure_right_hand_grip_rotation(base_path, child_layer_paths, main_path, graph_name, before_node_guid)` 在指定既有 AimIK 的组件姿势输入前插入 `Transform Modify Bone` 只对 `hand_r` 使用 `AddToExisting` 与 `ParentBoneSpace` 平移与缩放均 Ignore。节点使用独立 bool 门控且混入混出时间为零 由动作已有过渡保持姿势连续 避免固定挂接反补偿与腕偏移使用不同混合时间。工具拒绝已有右腕变换节点 不重复叠加；基础层 继承层和主图全部编译通过才逐一保存 不修改动画层接口或手指蒙版。

制作四元数采用 `q_out(t)=D*q_source(t)` 因而参考姿势增量为 `D=q_target_ref*inverse(q_source_ref)`。静态握姿和制作 LS 可以展示该增量 运行时动作 AS 必须保留源右腕 否则会重复叠加。挂接反补偿使用同一参考姿势下的实际腕变换完整求解 不只调整欧拉角。真实原生节点的乘法次序与零偏移通过条件须另行实测 不能将离线公式当作真实动画图验收。

离线 `test_right_hand_grip_configuration.py` 的四项门控检查覆盖目标有未保存修改 原生失败 继承层编译失败和精确目标保存顺序。原生图编译与真实蒙皮预览仍待实际引擎验收。既有末尾 `CR_BBB_MannequinFootPlant` 不读写手部辅助骨 不能假定它会将 `ik_hand_r` 或 `ik_hand_gun` 同步到偏移后的真实右腕。
