# Control Rig 动画编辑 MCP

## 2026-10-18 控制器批量写键

`configure_sequence_rig` 将同一无父级欧拉变换控制器的原始组件空间目标与显示帧数组交给既有 `BBBHandRetargetBatchToolset._set_component_keys`。运行时导入该公共写键辅助函数，按实际初始控制偏移转换后，直接写入九条原生 MovieScene 通道并展开跨越 ±180° 的欧拉角。各控制器保持输入分组顺序，不逐键切换预览时间。UE5.8 官方复数欧拉写键接口在真实 varying-key 验证中出现帧值重复，因此此入口统一使用已有通道写键路径。

每组写入后更新 Sequencer，再读取该组全部帧，并对扣除控制偏移后的局部目标验收；位置超过 0.01 cm、旋转差超出原阈值、返回帧数不足或实际通道键数不足均禁止保存。20 项序列生命周期检查通过，包含不同帧原始组件参数、控制偏移、第二帧错值拒存、读回缺帧、父级拒绝及模式切换。UE5.8 共享宿主真实写入并回读 2040 个变动关键帧通过，耗时 2.832 秒；帧 1 的根位置 X=0.0108119 cm、最大 X=0.09985 cm，未出现全部帧重复末值。

MCP 服务当前单次 HTTP 请求上限为 1048576 字节。提交大型键数组前，应计算完整请求 JSON 的 UTF-8 长度，包括批次、工具名、参数与协议外壳；按不超过 900000 字节分组并在提交前复核最终序列化结果。保持同一资产各批次顺序，保存回读后再提交下一组；不能将固定键数视为字节限制的证明。

已有目标动画的浮点曲线由目标自身维护 `bake_control_rig_animation` 在内存中保存目标曲线并在官方烘焙后完整还原插值与切线 没有目标曲线时才从源动作复制 内存快照使用 `/Game/__BBBControlRigBake` 临时包 不保存文件 并在成功或失败后清理

`inspect_control_rig_graph(asset_path)` 只读返回实际 RigVM 节点 引脚默认值与连接 用于检查制作控制器是否确实进入求解链 不执行求解 不保存资产

## 独立动作制作

`sample_animation_poses` 必须提供实际动画时长内的有限非负时间 每次至多六百项 越界时在采样前拒绝 避免引擎返回参考姿势而被误认成动画内容。

- `inspect_control_rig_reference` 读取实际导入骨架的局部与组件参考变换，用于选取求解轴向及初始化控制器；只读，不创建临时资产。

- `create_control_rig_sequence` 使用明确的时长和帧率创建只有目标网格的生成型序列，不添加源动画、不保存当前关卡，拒绝覆盖已有序列。
- `configure_sequence_rig` 向该序列加入控制绑定与显式关键帧。无父级和偏移的 `source_` 控制器采用局部接口并逐键验证。
- `bake_control_rig_animation` 使用官方 Sequencer 导出器，将指定序列唯一的网格绑定烘焙到明确的动画路径；已有目标必须取得写入权限。只保存目标动画，不创建诊断备份或改写来源。

`create_control_rig` 的 `graph` 与 `configure_control_rig_graph` 的 `request` 支持 `variables` 数组。每项使用 `name`、`type`、可选 `typeObject`、`default`、`node` 与 `position`，创建公开输入变量及读取节点。结构体例：`{"name":"TargetPosition","type":"FVector","typeObject":"/Script/CoreUObject.Vector","default":"(X=0,Y=0,Z=0)","node":"ReadPosition"}`。变量重名、类型缺失或节点创建失败立即报错；不静默复用未知变量。

动画迁移工具的 `configure_control_rig_anim_graph_node` 仅设置 Rig 和公开输入并重建引脚，保留已有 Alpha 类型、缩放偏差及姿势传递配置。需要 Float 权重时先通过 ObjectTools 设置 Node，再调用该工具生成 Alpha 引脚。不得隐式强制 Bool、反相 Alpha 或重置输入姿势。

`evaluate_rig_pose` 可选 `variables` 接受公开变量名到 Unreal 文本值的对象，如 `{"TargetPosition":"(X=1,Y=2,Z=3)","TargetRotation":"(Pitch=0,Yaw=0,Roll=0)"}`。在瞬态实例上、输入原动画姿势之后赋值，任一赋值失败立即报错。不保存或重定向源动画。

工具文件：`Scripts/BBBControlRigAuthoringToolset.py`。Bootstrap 统一注册，通过 `find_tools` 搜索 `control_rig`，描述选中工具后提交批次。

- `inspect_authoring_api` 查询当前引擎反射 API。
- `set_background_budget` 限制编辑器帧率；后台使用唯一隐藏 NullRHI 编辑器，进程优先级 BelowNormal，不操作用户前台。
- `create_control_rig` 接受目标网格、控制器 JSON、官方 RigVM 节点与连线 JSON。导入实际网格参考骨架，显式检查每个引脚和连接，拒绝覆盖已有绑定。
- `evaluate_rig_pose` 在实际网格评估的源动画姿势上调用官方 Rig 求解，不保存动画，返回源及求解后的骨骼变换。
- `prepare_animation_sequence` 创建独立 Level Sequence、生成型角色和原动画轨道，不保存当前关卡，拒绝覆盖已有序列。

此次目标资产：`/Game/BBBC_UA/Rigs/CR_BBB_Rifle_01_ReloadHandIK` 和 `/Game/BBBC_UA/Equipment/Rifle/Rifle_01/LS_BBB_Rifle_01_ReloadHandEdit`。原动画作为底层，Rig 仅调整手臂，零权重必须保留全部原始骨骼姿势。

未通过验收的全身模块 Rig `CR_BBB_UE4_Mannequin` 已删除。旧 `bake_animation_arm_trajectory` 和 `audit_arm_motion_trajectory` 已清除，旧配置 `Docs/Rifle01ReloadTrajectory.json` 已删除。`BBBAnimationTrajectoryTools.py` 仅保留复制动画、蒙太奇引用替换和固定轨道等通用资产操作，不再包含自制 IK 求解或轨迹烘焙。

原始 Lyra 动画、现有通知和运行时数据保留。当前工作尚未视觉验收。Scripts、Docs 和二进制资产不参与默认内层 Git 推送。

## 2026 09 30 握持与掌推验收

本节记录后续完成状态 上文未验收状态属于早期记录

- `build_pose_control_keys` 从实际角色网格取得父骨骼映射 修改局部旋转后使用官方 `MathLibrary.compose_transforms` 按层级重新合成组件姿势 不从已修改 AnimPose 的缓存读取子骨骼组件变换 保留原局部位移与缩放
- `configure_sequence_rig` 对无父级无偏移的 `source_` 原姿势控制器使用官方局部 Euler Transform 接口写键 每个关键帧立即读回 位置误差超过 0.01 厘米或四元数差超过阈值时直接报错 其它控制器仍使用对应的官方控制器接口
- `apply_baked_bone_deltas` 逐帧拒绝允许列表以外的骨骼差异 然后只合入授权旋转及 `ik_hand_l` 位移 原动画其它轨道和曲线保留
- `play_pie_montages` 仅用于动画与通知验证 返回 `animationOnly` 不代表装备业务输入验收 真实输入应使用 `run_pie_input_sequence` 并核对业务日志及运行时采样

当前编辑源为 `CR_BBB_Rifle_01_ReloadHandIK` 与 `LS_BBB_Rifle_01_ReloadHandEdit` 官方烘焙结果为 `ANI_BBB_Rifle_01_ReloadHandBake` 运行时使用独立 `ANI_BBB_Rifle_01_CharacterReload` 与 `_Additive` 原始共享 Lyra 动画保持作为底稿

持匣时拇指与四指对握 插入后在 1.2 秒结束手持显示并交接到枪上 手掌随后下移并在第 44 帧再次抬起推压 不能将这段下移抬起删成连续握持

验收记录见 `Docs/Rifle01ReloadValidation.md` 本轮真实输入 正侧面截图 中断清理报告位于 `Saved/Diagnostics/AnimationMotion/ReloadControlRig_GameplayVerification` `ReloadControlRig_GripVerified` 和 `ReloadControlRig_InterruptVerified`
# 独立控制轨道首次建立

`prepare_animation_sequence` 和 `create_sequence_attachment` 复用 Sequencer 自动建立的唯一生成轨道 不再添加重复轨道 起止关键帧负责生成与销毁临时演员

`add_pose_controls` 必须显式传入 `solve_node_name` 指定原有求解执行入口 隐藏原姿势控制器先恢复底稿的组件姿势 手部位置仍由 IK 控制器编辑 不依赖特定节点名称

`configure_sequence_rig` 会核对并切换已有轨道的叠加模式 非叠加模式关闭源动画轨道 需要由原姿势控制器完整提供底稿 禁止将绝对 IK 结果再次叠加到原姿势

`build_pose_control_keys` 在没有姿势修正请求时通过官方 AnimPose 接口直接读取组件姿势 避免重新合成源姿势 不改变原始位置 朝向或缩放 单次拒绝超过 600 帧

`build_pose_control_keys` 必须显式传入包含首尾的 `first_frame` 与 `last_frame` 每批最多 120 帧 返回关键帧保留源动画的绝对帧号 长动画分批完成 不重复提交仍在执行的请求

原姿势控制器使用官方 Euler Transform 数组接口按控制器批量写键 随后对全部关键帧回读校验 不省略位置与朝向误差检查

独立序列创建器的编辑演员使用官方 `transient=True` 只提供生成型模板 不成为测试关卡的持久内容

`capture_attachment_pose` 的骨骼附件允许显式设置 `animation_time_seconds` 秒值 用于按各自时间轴检查角色与机构动画 不设置时使用角色采样时间 超出动画时长直接报错 不自动循环或截断

骨骼附件指定 `hidden_bones` 时必须同时指定动画 隐藏后重新完成瞬态组件求值 使截图使用已更新的骨骼可见性 不能将尚未刷新的一帧误当成弹匣显隐失败

`configure_sequence_attachment_animation` 在唯一附件动画片段上设置起止显示帧和固定播放速度 使用 UE5.8 官方 TimeWarp 接口并回读校验 起始帧包含 结束帧不包含 显式范围内不得超过一遍源动画 修改只保存对应序列

已有骨骼附件尚无机构动画轨道时 该入口在验证时间范围后创建唯一轨道与片段 已有多个轨道或片段时拒绝修改

通用工具 `retime_single_action_montage` 仅处理各插槽从零开始并只播放一次的单段动作 调整片段速度后用官方数据控制器更新蒙太奇帧率与长度 不修改源序列 调用后按新的动作时间轴显式配置通知

`remap_animation_bone_times` 对自有无通知无曲线的机构序列按明确时间对应点重映射指定骨骼 其它轨道等比例播放 全部源姿势在修改前读取 使用官方数据控制器保留骨骼局部位置 朝向与缩放 不修改角色动画或第三方资源

`source_animation_path` 必须明确指定独立源动画 禁止源与目标相同 源姿势含有的变换修正曲线统一烘焙到目标骨骼轨道 目标旧变换修正曲线通过官方控制器删除 避免播放时重复叠加 修改后必须同时回读原始轨道与实际求值姿势

`sample_sequence_controls` 支持明确指定的欧拉变换控制器 包括 `hand_l_ik_ctrl` 返回控制器局部通道值 不将它误称为骨骼组件空间目标 该读取不会改写控制器关键帧

`capture_attachment_pose` 的 `file_name` 必须为 `任务目录/唯一文件.png` 输出仅落入 `Saved/temp/任务目录/` 拒绝父目录跳转 目录链接和覆盖已有文件 动画与附件均在瞬态 PIE 对象上求值 不保存资产

手部近景使用固定手动曝光与中性环境光 近景补光强度为 2000 避免在五十厘米左右的拍摄距离将皮肤与手持物照至纯白 验收须能辨认物体边界与手指接触位置

首次建立控制绑定轨道时先用 `configure_sequence_rig` 提交空关键帧数组 待这次调用结束后再分批写键 官方 Sequencer 的新实例需要经过真实编辑器帧注册修改事件 同一调用内建轨后立即写键可能不产生通道关键帧 工具的实际回读与数量检查不能省略

`sample_animation_poses` 经项目编辑器库一次批量读取 UE5.8 官方 RAW 姿势 `GetAnimPoseAtTimeIntervals` 与 `AnimPoseExtensions` 公开接口均在 C++ 中调用 避免逐骨 Python 反射复制 骨名按 UE 的不区分大小写语义匹配 缺少骨骼或空姿势直接报错 不使用单位变换伪造结果

末帧秒值跨 Python 反射进入 C++ 时允许至多一微秒的舍入误差 仅该误差范围内使用实际动画末帧 返回时间为实际求值时间 其它越界请求仍拒绝

首次创建控制绑定轨道时，先以 `keys="[]"` 调用 `configure_sequence_rig`，让编辑器完成轨道初始化，再在下一次调用写入真实关键帧。只打开序列不能代替轨道初始化。

`create_control_rig_sequence` 接受不存在的资产包，也接受当前工作区已经打开添加但尚未创建的包；两种情况都重新验证 Perforce 状态，拒绝其它工作区持有或无效的状态。重复生成轨道会影响官方烘焙器建立临时演员，创建器使用唯一生成轨道和明确的开始、结束关键帧。

`create_sequence_attachment` 按挂接骨骼或插槽查找唯一的骨骼演员模板 不依赖绑定列表顺序 多个匹配或没有匹配时在创建附件之前拒绝操作
# 烘焙曲线保留

`inject_pie_action(action_path, value, controller_path="")` 注入一帧标准增强输入 留空时使用当前 PIE 的第一个本地玩家 指定时必须是 PIE 世界内的本地 PlayerController 路径 可用于明确操作监听主机或客机 不允许对镜像控制器注入 输入仍由项目既有玩家输入适配层处理

MCP 调用须显式传入 `controller_path` 使用默认玩家时传空字符串

`bake_control_rig_animation` 从角色绑定的原始动画轨道读取源动作 即使该轨道已停用也保留其浮点曲线来源 原生复制完整关键帧 插值和切线 烘焙位置修正不会丢失 `DisableLHandIK` 或 `DisableAimIK` 控制曲线 多个不同源动作时拒绝保存 实际需要复制浮点曲线时原生接口仍要求源与结果同长

固定短握姿样板可以直接调用该正式烘焙入口 源动作没有浮点曲线时不调用曲线复制 因此不额外要求源动作与短样板同长 同时回读目标不得新增任何浮点曲线 发现意外曲线时明确拒绝保存 有曲线时保留原生复制失败的保存阻断

## 实际角色动作轨迹

`start_pie_montage_motion_capture` 记录本地角色的实际动画姿势与全部装备基类派生实例 不再仅采样步枪 没有 `Magazine_joint` 的装备输出空弹匣变换 不用组件原点代替缺失骨骼

启动采样后通过项目正常输入触发对应动作 工具不替代装备业务输入 使用 `get_pie_montage_motion_capture_status` 等待完成 完成时恢复原时间缩放和后台节流 每批使用新的任务临时目录前缀

`replace_animation_float_curve` 的操作备份写入 `Saved/temp/AnimationCurveEdit_<时间标记>/` 返回原资产备份和关键帧报告的精确路径 调用任务应登记这些文件并在验收完成后清理 不再写入 `Saved/Diagnostics`

轨迹记录将角色最终 `bones` 与动作自身的 `rawBones` 和 `compressedBones` 分开采样 用相同目标网格与时刻比较 原始轨道与压缩数据的位置差异不能直接归因于 IK 或重定向 骨骼缺失则采样失败 不用参考姿势填充

`rawBones` 和 `compressedBones` 是角色组件空间 `bones` 是场景世界空间 使用记录中的 `meshTransform` 转换后再比较 位置单位为厘米 旋转为 `[x y z w]` 四元数 不按欧拉角读取

`sample_weapon_handling_runtime` 的持枪采样使用正式公共动画层并包含其派生层 开火序号从装备动画基类读取 不把手枪 霰弹枪等实例误判为没有开火

`capture_pie_character_pose` 的 `file_name` 必须填写 `任务目录/文件.png` 输出限定在 `Saved/temp/任务目录/` 已有文件拒绝覆盖 使用实际角色和帧号检查背侧及低角度 不修改正式场景

姿势截图以 `focus_bone` 为画面中心 默认 `spine_03` 与动作轨迹采样共用固定曝光和临时补光 `exposure_compensation` 与 `fill_light_intensity` 可调 截图完成销毁临时相机和补光 不写入正式场景

动作轨迹的 `views` 可指定一到八个命名取景 例如 `[{"name":"reverse","offset":[0,-130,-30]},{"name":"under","offset":[100,60,-50]}]` 偏移相对关注骨骼使用世界空间厘米 名称只允许英文数字和下划线且不得重复 留空使用正面和侧面 每个采样时刻依次通过同一截图实现输出全部取景 报告保留视角名称和实际偏移 不用原始动画的预览图代替角色最终姿势

持枪探针的 `ammoEvents` 按游戏时间记录当前实际装备的弹量 容量与换弹状态变化 包含实例身份 用于验证逐发装入 满弹收束和换枪中断 `samples` 按 `sampleColumns` 读取 无弹量接口的装备输出空值 不把 MCP 查询完成时刻当作动画通知发生时刻

# 序列源动作替换

`configure_sequence_rig` 的变换键统一使用角色组件空间，仅接受无父级的欧拉变换控制器。写键先扣除控制器真实初始偏移，再调用官方局部欧拉通道批量接口并逐帧回读；不再经过预览演员世界变换，避免编辑器预览位置引入固定握把误差。带父级控制器明确拒绝，不能按无父级姿势静默保存。源动作重建须按序列显示帧率生成秒值调用 `sample_animation_poses`；`build_pose_control_keys` 的帧号属于源动画原生采样率，不能直接当作不同帧率的序列帧号。

`control_rig.configure_sequence_animation_source(sequence_path, animation_path, mesh_path)` 原位替换角色唯一源动作 要求源动作与网格骨架一致 播放区间和原全长片段随源长度更新 已有控制器与局部附件区间保留 非叠加 Rig 的源姿势控制器需要随后按新动作重写 再烘焙回读 禁止将只替换源片段视为完成矫正

## 只读序列烘焙审计

`control_rig.export_sequence_pose_audit(sequence_path, source_path, mesh_path, sample_times, report_name)` 保持原调用参数。`report_name` 必须为仅含英文数字、下划线和短横线的唯一 JSON 文件名，例如 `Rifle02_ReloadRigAudit.json`；输出位置为 `Saved/temp/Rifle02_ReloadRigAudit/Rifle02_ReloadRigAudit.json`。已有报告拒绝覆盖，目录链接与父目录跳转拒绝使用，交付后由任务清理该精确目录。

工具通过 UE 官方 `SystemLibrary.duplicate_object` 将完整序列和源动画复制到 `/Engine/Transient` 下的独立瞬态容器，仅在副本上调用 `SequencerTools.export_anim_sequence`，明确关闭序列动画链接。不建立正式动画包，不修改或保存正式序列、动画、生成轨或关键帧。官方入口无法处理瞬态副本时直接失败，不改用正式资产目录。

目标网格必须具有唯一已有生成绑定、唯一启用且覆盖完整播放区间的生成片段，生成通道必须从开始持续启用。缺少轨道、多个轨道、播放中途关闭时直接失败，不自动创建生成轨或补键。源动作与目标网格要求同骨架；采样秒数必须有限且位于源动作及实际烘焙结果内，不截断时间、不循环。

成功与失败路径均在 `finally` 中释放副本及其内含对象的 Python 引用并运行引擎垃圾回收。UE 的动画控制器或序列系统仍持有瞬态对象时，已完成的对照结果保留，并如实输出 `cleanup.state="pending_host_shutdown"`、具体 `retained` 路径和 `transientObjectsReleased=false`；调用者须在之后正常关闭所属宿主并核实 PID 已退出，才能完成这一生命周期检查。全部对象已即时回收时输出 `cleanup.state="released"`。工具不删除瞬态包、不修改引擎控制器根引用，也不将宿主缓存误报为已经释放。`differentBones` 是实际原生 RAW 局部姿势的厘米与四元数角度差异，不代表视觉通过或运行时动画层验收。

离线回归使用 `python -B -m unittest discover -s Tests -p test_control_rig_sequence_audit.py -v`，覆盖副本隔离、缺失生成轨、官方导出失败、姿势读取失败、宿主持有瞬态对象的待关闭状态、已有报告保护、无效时间与文件名、复制失败。真实 UE 验收需记录调用前后正式 LS 文件 SHA256、生成轨关键帧及资产 dirty 状态；分别检查成功与失败调用没有新增内容资产、没有改变正式 LS，按报告的清理状态记录即时回收或后续宿主 PID 退出证据。离线替身测试不能代替这一真实验收。

## 仅替换已有片段动画引用

`control_rig.replace_sequence_animation_references(sequence_path, replacements, dry_run=true)` 接受旧动画路径到新动画路径的显式字典，检查每项在已有骨骼动画轨道内至少出现一次，源目标必须为等长同骨架的 AnimSequence。未匹配或条件不符时整批在写入前拒绝；停用片段同样会匹配，适合整理仍需保留的制作源引用。

正式应用只设置匹配片段的 `params.animation`，保留片段其他参数、启停状态、时间区间和现有控制器及附件轨道，不同步播放长度，不创建轨道，不重烘焙。写入后用原生参数结构完整导出文本核对其他参数，再保存目标序列。此入口只处理引用等价替换；动作内容的等价性仍需调用者另行原生采样确认。Python 实现参数名为 `replacements_json`，MCP 调用使用结构化 `replacements`。

`python -B -m unittest discover -s Tests -p test_control_rig_sequence_references.py -v` 的 6 项独立检查覆盖预检无写入、停用偏移片段保留、共享原生结构体视图回读不反写、遗漏映射整批拒绝、骨架或长度差异拒绝、保存失败不报成功。真实 UE 验收还须对照制作序列的片段参数、播放区间、控制器关键帧、附件配置与实际引用，离线替身不能代替原生验证。

## 前臂扭转驱动与主图绑定插入

`control_rig.create_twist_driver(asset_path, mesh_path, chains)` 创建参考姿势相对的 Swing/Twist 四元数图。每条显式链包含 parent、driver、twist、variable、fraction；驱动骨与无子骨的 twist 必须同属 parent。初始局部姿势按实际网格统一，轴来自驱动骨的参考位移。输出为 `Slerp(Identity, Twist(CurrentHand * Inverse(ReferenceHand)), Fraction) * ReferenceTwist`，使用绝对局部旋转覆盖，不累加。

`control_rig.audit_twist_driver(asset_path, mesh_path, chains, cases, fractions, output_name)` 是可选只读工具。按原生骨名映射 Rig 姿势，执行正式 RigVM，采样实际 CPU 线性蒙皮，比较边长应变和面积，检查非目标旋转、位置、缩放及重复执行。`output_name` 为 `Task/Name` 且不带扩展名。分数只代表明确样本和几何指标，不代表自然观感或全局最优。Morph、Cloth、材质与完整玩法未执行。

`control_rig.insert_post_process_rig(main_path, asset_path, after_node_guid, before_node_guid, output_bones, input_values)` 在唯一直接相邻姿势连接之间插入正式节点。明确公开浮点值，传递全部输入姿势和曲线，不重置输入姿势，参考姿势来自当前网格，仅回写指定骨骼，编译保存并保留原节点标识。UE5.8 私有节点配置通过反射属性设置。

`control_rig.sample_post_process_rig(main_path, mesh_path, node_guid, animation_path, time_seconds, output_name)` 提供正式单节点的瞬态原生 AnimGraph 求值入口，不执行主图玩法。本轮用户要求停止测试后未执行此入口，不把它声称为已在真实宿主验证。

2026-10-19：原生编辑器构建成功；正式双侧 Rig 创建及主图插入保存完成。用户停止测试前，48 场景、7 档比例的 RigVM/CPU 蒙皮调用已完成，非目标局部旋转最大误差 0.000002415 度，位置/缩放误差为零，无累积。按用户最新要求不继续测试或优化，实际节点左右均采用 0.5 基准比例，观感待用户检查。此前3项离线几何检查通过；未执行完整运行时验收。

## 指定FK骨骼恢复参考旋转

control_rig.restore_sequence_fk_reference(sequence_path, animation_path, mesh_path, controls, frames) 将指定FK控制器对应骨骼的局部旋转恢复到参考动画第0秒。controls为控制器到骨骼映射，要求控制器直接归属于目标骨骼的父骨，FName按不区分大小写核对。保留控制器平移/缩放及所有其它欧拉控制器的逐帧值，写键后从关键帧重新加载控制值并执行Forwards Solve核验实际骨局部旋转，不能将延迟的Sequencer显示值当作已求解骨姿态。操作使用单次编辑器事务并保存原LS，不修改Rig资产、正式AS或装备配置。

2026-10-20在SMG03人工握姿序列真实应用右拇指三节，第0/1帧与MM_Rifle_Idle_Hipfire局部旋转最大误差0.00000342度，其它控制器完全一致。未运行PIE或额外测试。实现位于BBBControlRigReferenceTools.py，既有工具集注册并热加载实现。
