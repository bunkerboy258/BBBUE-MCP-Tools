# 动画原始骨轨恢复

## 2026-10-30 SG550 同源曲线样例

完整 FloatCurve 文本先导入引擎并重新导出，再做语义比较，避免用户显式的零值在引擎保存时省略默认字段而误报恢复失败；保留负值、插值、有效切线、颜色和注释。SG550 四条换弹曲线已按 FAL 当前人工版本应用。

首尾对齐对保留中段使用归一化四元数夹角，输出最大位置和角度误差；位置上限 0.001 cm、旋转上限 0.001 度，缩放仍为 0.00001。120 fps 的 Sequencer 数据模型写回中段实际位置差约 0.000101 cm、旋转差约 0.000389 度；不宣称字节一致。检查时间由实际帧数和时长换算，短动作指骨采样排除越界帧；指骨修复后同步最终输出摘要。

SG550 正式样例对齐统一 FAL 参考，入口 0～24、出口 224～264，共 265 键；定向桥接五根指骨的反向区间，没有执行指根整体归零。原位规范成品名称并更新蒙太奇引用，旧重定向器数量为零。专用正式 LS 使用 FAL 枪模、WeaponGrip_R 以及当前 FAL SpawnOffset 展示该统一基准。样例待人工审阅，未展开其余武器，也未运行 PIE 或自动化验收。

## 已有动作首尾对齐保留曲线

`BBBNativeRetargetActions` 正式源可设置 `preserve_curves=true`。现有 `control_rig.process_dual_arm_body_pose` 的 `finalize` 仍按明确首尾窗口对齐参考姿势并验证中段不变，但不创建或重写四条动作接管曲线；写入前后检查完整曲线语义，异常则拒绝保存。用于用户已手调曲线的正式动作，不能为姿态对齐覆盖曲线。

自动保存参考读取在返回前调用引擎 `fully_load_packages`，让包完成加载并释放原文件的读取锁，便于清理任务自身建立的只读参考硬链接。没有删除原自动保存或保存参考资产。

2026-10-30 实际应用：两份手雷动画由历史目标骨架自动保存恢复，各 68 骨轨、30 键，曲线与加法配置保持。持枪投掷以当前公共 Rifle01 持枪基准首尾对齐，入口 0～4 帧、出口 22～29 帧，中段保持；组件空间首尾位置误差小于 0.000069 cm。磁盘重载后的曲线完整文本保持。九份历史包重新读取后临时硬链接全部可移除，原自动保存保留。未运行 PIE 或自动化验收。

## 动画手调曲线与预览元数据

`control_rig.process_dual_arm_body_pose` 接收型号 `Source/Animation/*_AnimationMetadata.json.source` 正式制作源，格式 `BBBAnimationMetadata`。逐项使用 `job_index`、唯一 `write_paths` 与 `inspect` 或 `bake`。每项明确 `animation`，可选完整 `float_curves` 字典及同骨架 `preview_mesh`。省略曲线字段表示保持现有曲线，空字典表示明确清空，不能把缺失历史数据填成统一曲线。

`float_curves` 保存 UE 原生 FloatCurve 完整文本，包含键、插值、有效切线、颜色、注释及标记；按引擎大小写不敏感名称语义回读，忽略线性键无效的切线缓存。应用前校验路径、索引、唯一输出、网格与骨架；仅允许自有 AnimSequence，PIE 期间拒绝写入。逐项比较全部骨轨摘要、通知及加法等设置，保持一致后保存。

ManualAction 制作源通过 `animation_metadata_source` 明确引用此正式源。已有成品重新烘焙时保留其当前手调曲线及预览，不再复制公共身体输入的曲线，并检查曲线完整语义未变；新建成品时才从正式元数据源初始化。显式曲线恢复仍由上述 metadata bake 执行，后续人工改曲线后应同步正式元数据源，避免显式恢复旧制作值。未配置此字段的其他制作任务保持既有行为。

2026-10-30 FAL：读取现存历史 Autosaves，恢复装备四条曲线及换弹两条有历史依据的曲线；换弹左右姿势覆盖仅保留当前值并明确缺少历史原件。用户确认关心完整烘焙后，九份角色动画最终改用同骨架完整角色 Sk_CombinedMesh 预览，三份枪体动画保持原骨架与曲线。另从正式 LS 恢复空轨 UseReturn_Grip。十二份动画磁盘重载后九份各 68 骨轨、三份各 4 骨轨，元数据保持；装备与换弹曲线写后回读通过。未运行 PIE 或自动化验收，动作观感待用户审核。正常 ManualAction 再烘焙的保留分支仅完成语法与代码检查，未再次导出动作。

## 明确幅度的加法重建

control_rig.process_dual_arm_body_pose 的 bake 支持正式 BBBDualArmBodyPose 制作源中的 scaled_additive 任务。明确 source、output、base_animation、source_reference_frame、amplitude 和可选 rotation_space；制作源 mesh 提供同骨架层级。source_reference_frame 为有效原始帧，负一读取有效 ref_pose_seq 及其参考帧；拒绝无效范围、空骨轨、错误骨架、非单位旋转及含事件曲线的输出。rotation_space 为 source、mesh 或 local。

按指定旋转空间提取最短弧变化量，幅度作用于角度和局部位置、缩放差。输出使用当前基准的 Local Space Additive。写后逐帧重建组件姿态核对倍数，检查位移与缩放并保存，制作源记录输出骨轨摘要。零变化必须使用显式单位四元数，不能使用 Python Quat 默认零值。

2026-10-30：14 份现用近战通过原有官方序列烘焙恢复，骨轨各 68，元数据及三条控制曲线保持。3 份原始 Lyra 射击输入重定向并转换至有效当前基准，再生成 14 份三倍专属角色后坐力，逐帧幅度回读通过；无 PIE 动态验收。

入口属于 animation_graph。只处理明确自有资产，通过原位写入保持运行引用，不建立兼容路径或备份资产。

- restore_saved_grip_pose：读取型号 Source/Animation 内已通过的 BBBGripAuthoring 解，仅向缺少原始骨轨的两至三键静态 AnimSequence 写入保存的完整 local_pose。拒绝覆盖非空输出、跨型号来源与不完整制作解。回读位置及旋转后保存。
- restore_animation_bone_tracks：从同骨架、同帧数、同帧率且有原始骨轨的明确源复制到空轨目标，不改目标曲线、通知或加法参考。逐帧回读位置、旋转、缩放后保存。允许公共身体后震源本来不含手指骨轨的情况，不伪造手指运动。
- rebuild_weapon_aim_additive：使用现有 BBBWeaponAimEditorLibrary.build_aim_additive 原位重建已有加法与无曲线参考，拒绝空骨轨输入，保存两个正式目标。

control_rig.process_dual_arm_body_pose 的 bake 在输出已存在但骨轨为空、元数据与制作输入完全一致时，恢复原始输入并继续烘焙已批准控制姿势；非空已有输出仍拒绝覆盖，已记录的输出指纹仍需一致。

正式 ManualAction 原生导出后要求源骨轨非空且全部包含在导出结果内。轨道比较拒绝空预期姿势，避免空集合循环被误报为零误差成功。

稳定端枪配置排除 hand_l/hand_r 分支，脊柱混合不覆盖已经应用的专属腕部及手指姿势。

2026-10-29 实际静态编辑：恢复 14 装备、16 换弹、28 静态握姿、14 后坐力，重建 8 举枪资产和手枪/重物基础姿势。85 份目标磁盘重载回读无空轨；另外 45 份 Lyra AimOffsets 采样重定向恢复后各 68 条骨轨。手枪 49 帧后坐力原有静态求值器通过；公共及五个装备子层编译保存。未执行自动化动态验收。


## 13 武器统一 FAL 基准的原位制作

2026-10-30 用户通过 SG550 样例后批量应用。BBBNativeRetargetActions 的 capture 支持明确 in_place_alignment 输入，记录非空骨轨指纹，不重新重定向；finalize 先完成全部未对齐输出，再执行已批准的定向手指修复，重复调用核对最终指纹。

分段装填使用单侧 entry_frames / exit_frames；preserve_internal_pose 允许两侧都为空以保持插入段。finger_repair 的 repair_boundary_extension 只用于相邻分段：将反向翘曲边界按同一参考上限桥接，正常骨节、局部位置和缩放保持，必须额外核对接缝。无异常时记录 checked_no_anomaly，不改骨轨。

job 可明确 reference_animation 与 reference_frame。局部加法副层回到自身参考帧使增量归零，绝对主层仍回到统一 FAL；不能把 FAL 绝对姿势直接写入以另一姿势为参考的加法层。

playback_frame_range 仅支持从零开始的明确实际播放范围，拒绝含曲线或通知的裁切。运行 UseReturn 蒙太奇只播放 0～0.2 秒，正式输出保留七键并在实际出口对齐，完整制作 LS 不裁切。

AnimationMetadata 曲线按目标 AnimationSequencerDataModel 的原生 tick_resolution 量化时间，再导入、逐项比较键和有效插值；允许序列化一微秒误差，不忽略有效值或切线差异。2026-10-30 已对 68 份角色成品执行完整元数据保存回读，未运行 PIE 或自动化验收。

分段内部接缝可单独制作源显式引用插入段的首帧或末帧。保存验证和 inspect 都记录实际 reference_animation / reference_frame，手指比较与腕部轨迹使用同一指定参考帧，不把加法归零或内部接缝误报成FAL绝对端点。


## 角色动作按曲线对齐

BBBNativeRetargetActions 的 finalize 逐采样调用 AnimationLibrary.get_float_value_at_time，以现有 DisableLeftHandIK（或明确 blend_curve）读取真实插值值。原动作权重为 clamp(curve,0,1)，参考权重为一减该值；不再读取固定 entry_frames / exit_frames，也不另外使用 SmoothStep。原曲线、有效切线、颜色、通知及动画设置保持。曲线满权重样本回读核对原动作；无此曲线时保留原输入，不合成过渡。加法层混合自身有效参考姿势，使增量归零，不能把绝对FAL姿势写进另一加法基准。

输入必须先从正式LS或有完整骨姿的制作记录恢复，再 capture 登记指纹后 finalize；旧输出指纹或曲线发生变化会明确拒绝，避免对已处理成品二次混合。inspect 回读骨轨及曲线摘要。没有额外的全段手指角度压制阶段。

同型号的完整组件姿态记录可由 job.component_snapshot 明确指定 record、record_sha256、group、expected_target_digest；只接受本型号 Source/Animation 里的唯一同名动画、全部连续采样和完整骨名。使用记录网格的父骨层级原生转回局部姿态，保持元数据，写后回读。此阶段只在未登记 retarget_digest 时执行，不接受其他型号的动作替代。
