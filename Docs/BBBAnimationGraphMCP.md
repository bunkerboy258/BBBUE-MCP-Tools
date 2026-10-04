# 显式时间动画过渡图

## 动作变体与预算载体扩展

`create_mass_presentation_variant` 从已验证载体、定义与实体配置复制三个不存在的新资产，绑定完整同骨架合并网格，重新连接定义与 MEC 以及表现 Trait；严格检查各一个装配、编译保存。必须先确认模块外观组合，不自动提交资产。

`audit_animation_tracks` 读取明确序列全部根骨关键帧，核验平移、旋转和缩放，同时报告所指定局部骨骼首末差异。输出为 Saved/Diagnostics/AnimationAudits 中唯一 JSON；局部接缝摘要不能代替组件空间与视觉接缝检查。

`create_merged_skeletal_asset` 仅创建不存在的自有骨骼网格。明确同骨架模块，读取 LOD0 的导入 MeshDescription，保留材质和 UV，按骨骼名称重映射蒙皮，追加导入几何后提交源描述并通过 UE Build 和 RegenerateLOD 构建三层 LOD。没有源描述、材料或对应骨骼时拒绝保存。不使用运行时 FSkeletalMeshMerge 的临时渲染数据充当可重新构建的资产；返回成功仍需要 Perforce binary+l 登记、重载和视觉检查。

`configure_fact_action_variants` 在基础事实图上配置攻击、受伤、死亡三个变体组。参数 `variant_paths` 按组展开，`counts` 给出各组数量。原生构图生成 `BlueprintThreadSafeUpdateAnimation`：只读取事实，缓存上次动作身份，在身份或进入时间改变时翻转姿势槽。每组通过表现对象身份与动作编号选择变体，按事实进度计算采样时间。AnimGraph 只读取派生变量，使用双组静态序列求值器及标准惯性混合；重启相同动作也切换槽，不在原生动画实例维护播放器。必须独占持有、无警告编译、保存并实际验收，构图成功不代表视觉通过。

`reparent_presentation_blueprint` 将明确的表现载体蓝图改为指定原生载体父类，严格编译并回读实际默认网格类型。用于将指定僵尸改为 `BBBMonsterBudgetPresentationActor`，不批量修改其它测试体。新载体使用引擎 `SkeletalMeshComponentBudgeted`，自动按视距计算重要性，不新增玩法 Tick，仍由 Mass 维护行动与伤害。预算开关、质量和群体测量必须用真实运行时数据验收。

`rebuild_sequence_crossfade_blueprint` 用于撤销本工具生成的 FactDrivenActions 图，恢复原父类的六个查询驱动的标准双通道图。调用方必须先备份并独占签出；原生入口拒绝无关手工图，编译无警告后只保存指定资产，不回退 C++ 或替换磁盘包。

## 事实驱动状态机构图

迁移可明确传入 `parent_class_path`，使用 UE 原生 ReparentBlueprint 切换至事实动画实例后重建图；不设置时保持原父类。新父类须继承 AnimInstance 且包含指定只读事实属性。

`create_speed_blend_space` 只创建不存在的一维混合资产。输入同骨架序列、严格递增的厘米每秒速度与速度轴平滑秒数，首个速度必须为零。原生能力使用 UE AddSample、ValidateSampleData 和 ResampleData 构建运行时数据，不直接伪造样本数组。调用前必须验收循环与 In-place；保存后须将新资产登记为 binary+l 并核验真实样本和引用。

`rebuild_fact_driven_state_machine` 重建明确动画蓝图的 Locomotion、Attack、Hurt、Dead 四状态图。调用方必须先备份目标及引用者并取得 Perforce 独占签出或待添加状态。三个事实属性依次为行为枚举、实际速度、归一化动作进度；三个动作枚举值必须递增，移动行为值必须小于首动作值。当前标准图只接受每类一个序列，不声称支持动作变体、起步或同状态惯性过渡。

移动使用同骨架 BlendSpace；三个单次动作使用显式求值器，按进度乘序列长度采样，禁用通知推进。死亡状态没有出口。原生构图只修改内存，不编译或保存；Python 入口严格编译成功后仅保存目标资产。参数或编译失败保留诊断现场，不自动回退旧图。构图成功不是实际姿势或性能验收通过。

跨状态过渡采用标准 Inertialization，输出端放置惯性节点，过渡停止求值旧状态，避免旧动作读到新动作进度后先跳姿势。时间仍由事实决定；同状态新编号的惯性请求尚不在当前构图能力内，不能宣称已验收。

原生依赖为 `BBBAnimationGraphEditorLibrary::BuildFactDrivenStateMachineGraph`。执行前应确认项目模块已经编译且宿主加载最新版本。该能力可复用于符合枚举布局的其它表现蓝图，不依赖任何小怪 C++ 类型。

通过官方发现查找 BBBAnimationGraphToolset，先核对原生 BBBAnimationGraphEditorLibrary 已加载。

create_sequence_crossfade_blueprint 只创建不存在的资产。提供动画实例父类、同骨架预览网格和序列，以及六个只读查询：甲序列、乙序列、甲时间、乙时间、乙启用、混合时间。原生实现连接两个 Sequence Evaluator 和 Blend Poses by Bool，不保留旧播放路径，不使用蒙太奇通知驱动玩法。求值器开启显式时间跳转，禁用通知推进和根运动提取。标准布尔节点零号通道是真、一号通道是假，不能凭编辑器排列误接。

蓝图必须无警告编译通过才保存，已有已制作的动画图拒绝覆盖。创建失败不自动重试，先检查是否存在脏资产。

configure_actor_animation_blueprint 将已编译的同骨架动画蓝图绑定至演员蓝图指定默认组件属性。演员蓝图须事先 Perforce 独占签出；工具验证骨架、编译后回读并仅保存这一资产。新建 UE 二进制资产仍须按项目要求登记为 binary+l，不自动 Submit。

完成绑定后必须重新加载资产验证持久化，并使用真实运行时采样确认切换、同状态新动作和显式进度。创建成功不代表动画视觉验收通过。

Perforce 待添加的新演员资产也允许配置，必须由当前工作区持有且没有其它工作区占用；调用方需先回读文件类型为 binary+l。待添加不等于 IsCheckedOut，不能为了满足检查而自动 Submit。

当前生成图使用标准纯函数节点直接连接六个只读快照查询，不依赖属性访问缓存。bind_sequence_crossfade_getters 可对明确独占持有的标准双通道图重连输入；原生实现要求一个输出、一个布尔混合及两个序列求值器，拒绝含其它逻辑的已制作图。旧属性访问节点被整体移除，不保留兼容播放路径。必须检查实际求值器资产和权重，而非仅动画实例查询结果。

程序创建 UAnimGraphNode 后必须执行 PostPlacedNewNode，初始化绑定并请求编译扩展。缺少此步骤时连线和编译状态可能正确，实际求值器仍取空资产；本工具创建和重连均执行该步骤。原生依赖位于项目 Source/ABBB_EvacEditor/Public 与 Private 下的 BBBAnimationGraphEditorLibrary，单独分发本 Python 模块不能替代项目原生编译。
