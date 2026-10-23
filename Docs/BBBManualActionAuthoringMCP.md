# 武器装备与换弹动作的人工制作

## 本轮实现范围

`control_rig.process_dual_arm_body_pose` 的 `action=prepare_action` 准备一把武器的完整装备或换弹序列。实现为 `Scripts/BBBManualActionAuthoring.py`，入口通过现有正式工具加载。它只准备人工编辑输入，尚未提供本流程的应用操作；不得将准备完成当作正式动画已经更新。

正式制作要求放在本型号 `Source/Animation/*_ManualAction.json.source`。`format=BBBManualWeaponAction`、`schema=1`，显式列出 `weapon_root`、`definition`、`mesh`、`animation`、`sequence`、`rig`、`arm_graph_source`、`action`、`approval`、`status`。只允许 `equip` 和 `reload`。LS 与 Rig 在本型号 `Animation/work`，正式动作在 `Animation/Sequence`。换弹若有枪体显隐通知，另外显式提供 `preview_animation`，同样在本型号 `Animation/Sequence`。

`write_paths` 必须恰好列出制作 LS、Rig，以及存在时的 `preview_animation`。运行配置、正式角色动作、枪体动作及其蒙太奇均不属于准备写入范围。

## 准备入口与保存阶段

```json
{
  "tool": "control_rig.process_dual_arm_body_pose",
  "arguments": {
    "action": "prepare_action",
    "recipe_path": "Content/_Project/Characters/BBBC_UA/Items/Equipment/Rifle/Rifle_01/Source/Animation/Rifle01_CharacterEquip_ManualAction.json.source",
    "write_paths": [
      "/Game/_Project/Characters/BBBC_UA/Items/Equipment/Rifle/Rifle_01/Animation/work/LS_Rifle01_CharacterEquip",
      "/Game/_Project/Characters/BBBC_UA/Items/Equipment/Rifle/Rifle_01/Animation/work/CR_Rifle01_ActionEdit"
    ]
  }
}
```

首次准备会原位整理明确列出的 LS，清除其中旧绑定。因此仅能在人工编辑开始前使用 `prepare_approved`。按返回状态顺序重复同一请求：

1. `track_created`：建立角色及 Rig 轨道并保存，让编辑器完成轨道注册。
2. `keys_written`：写入源动作完整轨迹及逐节手指 FK 关键帧并保存。
3. `previews_created`：逐通道回读所有关键帧，以独立 Rig 验证全帧，以官方纯瞬态烘焙验证实际序列全帧，再建立枪械和弹匣预览。
4. `manual_edit_ready`：原生回读枪体、旧弹匣、新弹匣实际挂接位置后，打开第 0 帧供人工编辑。

制作已进入 `manual_edit_ready` 后，重复请求只打开序列，不重建控制器、不覆盖人工关键帧。若正式动作的骨轨摘要已变化，明确报错并保留手调序列。首次建立 Rig 后，可用 `reuse_rig=true` 为同一角色的另一动作复用此 Rig；仍会执行源姿势一致性检查。

## 人工操作

- `hand_l_ik_ctrl`、`hand_r_ik_ctrl`：左右手完整位置和角度。
- `elbow_l_pv_ctrl`、`elbow_r_pv_ctrl`：左右肘方向。
- `clavicle_l_ctrl`、`clavicle_r_ctrl`：左右肩部。
- `fk_thumb/index/middle/ring/pinky_01/02/03_l/r`：手指逐节旋转，后续关节跟随父节。保留手指原始长度，不手动移动或缩放手指。
- `source_*` 是完整源动作的隐藏输入，不作为人工修改对象。

动作在每个源帧已有关键帧。只改一个时间点只会影响该点及相邻曲线；需要持续修正一段时，应调整该段关键帧。先保留动作的进入、离手操作和回握节奏，再处理必要部位。调整完成后保存 LS，由用户明确通知应用，再实施正式动作烘焙及引用核对。

枪体沿当前配置 `SpawnOffset` 挂接到 `WeaponGrip_R`。换弹时，`OldMagazine` 与 `NewMagazine` 是可单独选中的预览对象，挂接、变换和显示时段来自当前角色通知实例，直接使用原生通知起止时间。它们用于确定手持位置；不在 Sequencer 模拟抛匣物理。将来应用时，手持弹匣的结果应写回各自通知实例的 `HandMagazineTransform`，不引入武器代码侧弹匣语义。

枪体动作按当前装备、角色蒙太奇片段速度比同步；当前准备入口仅接受从 0 开始、不裁切、不循环的单正向片段，复杂分段必须先明确时间映射，不能猜测。枪体显隐通知通过明确的制作预览 AS 显示，正式枪体动画和蒙太奇保持原状。预览 AS 被 LS 实际引用，是必要制作输入，不是历史副本。

## UE 5.8 实现注意

使用 `LevelSequenceEditorSubsystem.add_spawnable_from_instance` 及 `MovieSceneBindingLifetimeTrack`；建立绑定前必须先打开目标 LS。旧 `MovieSceneSpawnTrack` 写法不能作为新自定义生成绑定的有效性证明。编辑器会自动添加默认 Transform 轨，附件建立时只保留一个明确的 Transform 轨，避免默认零变换与配置各占一半权重。

`MovieSceneSkeletalAnimationParams.play_rate` 使用 `MovieSceneTimeWarpExtensions.make_time_warp`。批量 `get_local_control_rig_euler_transforms` 在此次场景返回当前缓存姿势，不能作为保存关键帧的回读依据；当前实现直接比较实际通道时间和值，并通过官方纯瞬态烘焙独立核验结果。瞬态对象不保存到 Content，不调用带 `CurveSnapshot_*` 分支的通用烘焙工具。

## 2026-10-20 原生验证

Rifle01 装备 51 帧、换弹 67 帧全部通过源姿势对照。实际序列烘焙最大组件位置误差分别为 0.000257、0.000148 厘米。逐节 FK 修改专项确认左右食指后节跟随且骨长误差小于 0.000004 厘米。枪体及两枚手持弹匣实际挂接偏差小于 0.000001 厘米，保存边界无脏包。用户尚未修改本轮动作，未烘焙应用到运行资产，未启动 PIE。

## 已保存手调与烘焙的一致性诊断

`control_rig.process_dual_arm_body_pose(action=inspect)` 对 `*_ManualAction.json.source` 执行只读检查。`write_paths` 仍明确列出本制作 LS 与 Rig，以满足现有入口的资产占用契约；该检查不保存资产、不写键、不改制作源。普通双臂制作源仍走原有检查语义。

返回 `source_matches_preparation` 验证正式源骨轨是否变化，`modified_controls` 列出相对源动作的控制键变化数、时间范围及小数帧键。存在 `review_bake` 时，使用官方纯瞬态烘焙比较所有整数采样帧，返回 `bake_matches_saved_integer_frames`；另对手调小数帧和其相邻整数帧，以原生通道 `evaluate_keys` 加独立 Rig 实例进行求值，返回 `subframe_preview_comparison`、`subframe_peak_hand_error_cm`、`integer_hand_error_cm` 和 `manual_subframe_positions_preserved`。整数帧一致不能作为小数帧手调已保留的证明。

原生通道范围从 `compute_effective_range` 取得真实 Tick 分辨率，再设置待查 Tick 区间，避免将小数帧截断。不能在同一调用中连续改变播放位置后立即用视口组件缓存姿势作此项验证；该组件可能尚未刷新。

2026-10-21 Rifle01 装备诊断：左手新增键位于 20.24875、23.8075、27.99125、30.6 帧。源骨轨摘要与制作开始时一致，整数帧官方重导出与成品一致；上述四处原生手调位置与 30 FPS 成品相差 12.3412、10.9799、8.70865、3.34513 厘米，相邻整数帧左手位置最大差小于 0.000061 厘米。当前仍保留逐帧底层键，没有稀疏修正层，新增子帧键形成的窄峰可能在固定帧率导出时丢失。本轮仅确诊和补充核验，没有自动重摆手、覆盖用户关键帧或将成品认定为穿模修复通过。

## 从现有小数帧手调生成连续审核动画

`control_rig.process_dual_arm_body_pose(action=bake)` 对正式 `*_ManualAction.json.source` 调用 `BBBManualActionBake.py`。`continuous_review` 显式提供 `animation`、`control=hand_l_ik_ctrl`、`entry_frame=0`、`exit_frame`、`bake_fps=120` 和 `max_anchor_error_cm`，`write_paths` 必须只包含审核动画。输出必须属于同型号 `Animation/Sequence`。本入口只生成审核成品，不改变运行引用，不覆盖用户 LS 或 Rig。当前只处理已有密集底稿中左手 IK 的小数帧修正点；其他控制器的小数帧输入明确拒绝，不能把它当作完整的通用修正层编辑器。

步骤：

1. 校验正式源骨轨摘要和明确写入范围，读取实际用户小数帧键。
2. 在纯瞬态序列中移除这些小数帧窄峰，保留全部整数帧基线；先以官方瞬态导出初始化克隆的 Control Rig 通道代理。未初始化的副本可能没有可读通道。
3. 按每个人工时间点读取原始手调目标和瞬态基线，计算完整左手目标在右手空间中的位置、旋转修正。
4. 在第0帧与原结束帧使用零修正，中间使用人工点，以无过冲的平滑插值连接；保留原动作轨迹，再求解双臂和手指。没有自动贴枪或碰撞拟合。
5. 以120 FPS生成全部局部骨轨，保留原长度及通知、曲线、加法和Root Motion等元数据。直接写入审核动画，不调用通用 `CurveSnapshot_*` 分支。
6. 分别核验每个原始骨轨采样、四处实际预览位置与起止姿态。骨轨回读不重复应用骨架平移重定向；另以启用重定向的姿势单独验证实际预览误差。用户视觉审核仍是独立步骤。

`inspect` 对这种成品返回 `bake_mode=continuous_manual_correction`，原密集序列中间整数帧本就应与连续成品不同，不再将这种差异误报为烘焙失败。改为比较原人工点与起止姿态，并返回本次明确的审核位置容差。

2026-10-21 Rifle01 已真实保存并打开：原长度1.666667秒，120 FPS，201个采样关键帧。全部原始骨轨回读最大组件位置误差0.000290厘米；四个人工点的实际预览位置误差依次0.369916、0.073857、0.005226、0.197093厘米。最初0.25厘米预检未通过，核对原始与预览姿势后保留真实重定向剩余误差，当前审核容差明确设置为0.5厘米；不宣称完全零误差。四点原始轨迹插值误差均小于0.027厘米。独立 `inspect` 通过，起止手部误差小于0.000042厘米。原LS和Rig文件SHA不变，用户四处手调仍可回读，运行引用未切换，穿模视觉审核待用户。

## 原生叠加编辑与所见即所得烘焙（2026-10-21）

人工动作入口统一使用 Scripts/BBBManualActionNative.py。prepare_action 到达 manual_edit_ready 时自动建立覆盖原动作区间的原生 Additive Section，保留全部原始控制键，锁定原动作段，选中叠加段；重复调用复用同一段，不叠加新段。无键时使用中性通道默认值。整段固定修正使用叠加段单一偏移键；局部变化只使用UE本身的关键帧与曲线，不由工具猜测过渡。

bake 仅调用官方 SequencerTools.export_anim_sequence 对实际序列求值，以120 FPS导出，再直接写回明确审核目标骨轨并保留源浮点曲线及目标通知、加法、根运动等已有元数据。没有重算控制目标，没有阶段或平滑插值，没有 CurveSnapshot 资产。旧 BBBManualActionBake.py 与旧人工小数帧解释诊断已删除；inspect 返回实际原生段与通道状态，不再以额外算法解释人工意图。

原生段初始化需通过官方导出建立通道代理；get_blend_type 返回 OptionalMovieSceneBlendType，须读取 blend_type。克隆上的原生通道同样需先初始化后再编辑。初始化导出只用于建立代理，原LS播放结束51帧可能产生额外一帧；正式导出在纯瞬态120 FPS序列上明确控制完整源长度，不改变用户LS播放区间。

已验证 Rifle01 装备：中性叠加前后全轨差0，瞬态左手X偏移1厘米实际移动1.000005厘米，右手差0；原键保留，自动建立与重复打开成功。Rifle02 装备也已实际通过自动准备，未改变正式运行动画。一次失败后的Slate访问崩溃已重启前台宿主恢复，随后准备成功；不将尚未执行的正式返工烘焙称为已通过。用户当前编辑入口仍是Rifle01装备。

## 完整手臂制作预览（2026-10-21）

用户确认只需完整大臂模型，不修改肘部控制。prepare_action 在恢复现有人工序列时调用 prepare_preview_mesh，默认使用同骨架原包 Arms/SK_arms；制作源可用 preview_mesh 指定明确网格。仅替换现有角色绑定的预览网格，并同步制作源 mesh，保证后续绑定查找和直接烘焙使用同一制作网格。不更改运行角色网格、Rig控制器、动画引用或挂接。

修改前后逐通道核对所有关键帧的显示帧时间、子帧、值与默认值摘要，绑定GUID使用export_text稳定表示；不将Python结构显示字符串中的地址写入摘要。另在纯瞬态中官方导出替换前后实际动画，核对全部骨轨位置、旋转及缩放。失败恢复原预览网格；不重建LS，不写控制键，不做自动拟合。

实际Rifle01换弹批次61c60ffb20d0b446完成：现用SK_arms，通道摘要11f03a44a30bd612b5884f595ffaca0f0c2a7cceb7b05ae41eab18bb732d5f32前后一致，原生骨轨差0，绑定保留。用户左手叠加位置与旋转各10键、缩放各3键保留，旧/新弹匣Transform轨保留。肘部控制与Rig资产未写入，未跑PIE，不生成备份资产。

## 换弹左侧恢复原通用动作（2026-10-21）

后续换弹人工制作按用户要求，以对应原通用换弹的左臂、左腕和手指开始编辑，不能用专属Grip或静态握姿替代原通用换弹。为每条新ManualAction制作源显式填写left_reference.animation与applied=false；Rifle Reload基准使用/Game/_Project/Characters/BBBC_UA/Animation/OtherAnimation/Lyra/Rifle/MM_Rifle_Reload。其他动作基准须选自身对应原通用动画，长度或骨架不匹配会拒绝，不猜测时间映射。装备不应用此操作；已确认的历史动画不回改。

prepare_action恢复阶段调用restore_left_reference：先在纯瞬态副本逐帧重写左侧原生Absolute控制通道，并清除左侧Additive偏移；肩、肘、腕、源骨和逐节手指同时恢复。以官方导出核对全部67帧左侧位置和旋转，另核对非左侧骨轨不变，再写入原LS。其它通道的全部键时间、子帧、数值和默认值摘要必须一致，武器及弹匣轨道不变。UE骨名比较忽略大小写，写入仍使用实际通道名称。

成功后制作源记录applied=true、参考骨轨摘要和误差；后续打开不再重复恢复，用户之后的手调可继续按原生Offset编辑及直接烘焙。没有自动平滑、重建LS、运行引用变更或备份资产。Rifle02原生批次6c82ef18cd19d245完成，最大左侧位置误差0.000174厘米、其他通道保持；fb4bbfeda1fc46e4验证重复打开不重置。

## 2026-10-21 公共动作底稿正式链路（当前规范）

本节取代前文schema=1和left_reference制作入口。当前ManualAction只接受schema=2：animation为UsedAnimation中的公共身体动作，finger_animation为本枪手指/元数据输入，output_animation为本枪Sequence下的烘焙成品，baseline_catalog为角色Source/Animation/CommonActionBaselines.json.source，source_time_scale明确公共时间与本枪制作时间之比。LS与Rig仍归本枪Animation/work。没有旧格式兼容分支。

同一公共目录制作源采用format=BBBCommonWeaponActions、schema=1，列出baselines、weapons、manual_recipes。公共动作通过control_rig.process_dual_arm_body_pose(capture)建立，write_paths列出全部公共包；源为经明确确认的校准版本，不重复叠加已手调ManualEdit。移除公共手指骨轨及通知，逐项核对其余骨轨。inspect使用同一占用范围，只读检查公共AS、全部型号制作要求、骨架和显式时序。finalize用于采纳已保存的公共手调，保持时长及骨架并拒绝手指和通知，随后prepare_action刷新各枪身体基础轨、bake输出本枪成品。公共输入改变后旧运行AS不会自动更新。

prepare_action在原LS动画轨绑定真实公共AS引用，Absolute身体控制轨从该公共输入按明确时间比例生成；不改变现有Additive键、手指控制轨或附件通道。先在纯瞬态副本以官方Sequencer导出核验身体姿态，再保存，保留通道摘要。公共摘要不变时重复打开不改底轨。手指仍独立采用本枪输入，首次制作分别验证公共身体和本枪手指局部姿势；原生Offset及直接120 FPS烘焙方式不变。旧左侧单独还原函数已移除，不再从OtherAnimation抽取Lyra左臂拼到专属动作上。

本次已建立18个公共底稿及14把武器映射，27份装备/普通换弹制作要求通过原生只读检查。Rifle01/02四条现有LS实际依赖已改为公共AS，所有手调和附件键摘要保持；身体基线官方导出误差最大0.000132厘米。Rifle02装备重新烘焙后与官方实际序列导出骨轨差0。Rifle03装备从空制作要求完整走通prepare阶段并到达manual_edit_ready。其他未准备条目仅是明确制作要求，不宣称完成手调或运行应用；逐发霰弹枪保留三个独立阶段，不强套普通换弹。未跑PIE，无备份和兼容跳转。


## 2026-10-21 干净Manny重定向公共动作

新增 Scripts/BBBActionRetargetTools.py，通过 control_rig.process_dual_arm_body_pose 的 *_RetargetActions.json.source 分派 capture/finalize/inspect。BBBNativeRetargetActions/schema1明确原始动作、原生RTG、网格、参考、输出和首尾帧窗口；write_paths必须等于全部输出。capture调用UE原生IKRetargetBatchOperation，校验非空op stack、精确目标和源摘要，拒绝覆盖未采纳输出。finalize只平滑明确首尾窗口并回读中段/首尾、保存摘要，inspect核对保存及轨迹。不解释人工Offset键，不产生备份或兼容跳转。

公共目录改按各baseline的finger_policy核验；新rifle装备/换弹保留源动画手指。ManualAction/schema2允许公共AS同时作为身体与手指来源，显式source_time_scale；准备时正确导入is_finger，并按本枪正式蒙太奇源验证弹匣预览，避免公共手指输入误当成本枪蒙太奇源。

实机静态验证：指定RTG生成两条新公共动作；原始输入不变，首尾最大位置误差0.00003305835cm，中段最大写入误差0.00009338207cm。目录18底稿/14武器/27制作要求通过；Rifle01/02四LS原生Additive空键、四成品与实际Sequencer导出误差0、正式蒙太奇读回正确、无PIE。入口prepare_action再次打开Rifle01装备第0帧。通用CurveSnapshot备份分支本轮未调用。


## 2026-10-21 现有装备指节异常修复

BBBActionRetargetTools在inspect中输出手指前段逐帧命名旋转、参考及骨架中性姿势；finalize支持正式源显式finger_repair.mode=bridge_hyperextended_distal_yaw和approval。该分支只原位修复装备非拇指02/03节超允许上限5度的连续Yaw异常段，用两侧现有安全帧连接，保持其他骨轨和关节Pitch/Roll、位置/缩放，不调用重定向。记录区间和摘要，重复调用核验当前摘要。

ManualAction的finger_repair_source通过prepare_action同步受影响源指节Absolute Rotation.Z键。写入前逐键与旧源比对，存在人工冲突即拒绝；回读并验证其他控制键及原生Offset摘要不变，再正常官方烘焙。实机：16轨266异常采样修复，Rifle01/02/03制作序列同步，Rifle01现有9个Offset通道保留，Rifle01/02成品与LS导出误差0、正式引用读回正确，换弹不变；未跑PIE、未重新重定向、未产生备份。


## 2026-10-21 动作制作控制器显示筛选

ManualAction正式源可用visible_controls显式限定视口控制器。prepare_action在原生Offset准备后同步Rig资产及当前Sequencer实例的shape_visible，核对精确可见集合，比较全部序列通道摘要以保证关键帧不变；不删除控制器、不改求解。Rifle01换弹实机回读只显示左手IK、左肘方向、左锁骨及15节左手指FK，共18个控制器；全部关键帧保存不变。无PIE、无备份、无临时资产。


## 2026-10-21 换弹右食指修复

finger_repair现归属RetargetActions每个jobs项，mode统一为bridge_hyperextended_finger_yaw，bones显式限定可修改骨轨；finalize逐动作核验或修复，sync按ManualAction.action匹配。正式源已迁移至唯一当前结构，不保留旧结构分支。inspect同时报告装备与换弹指节命名旋转及全轨迹最大Yaw。

实机检测换弹index_02_r在3–9、25–56帧反向上翘，峰值8.29799度；仅修这条骨轨39采样，修后最大Yaw为-0.33319度。其他骨轨、位置和缩放保持。Rifle01/02已准备换弹LS同步39个Rotation.Z源键，摘要验证其余控制键和Offset保留，Rifle01仍仅显示左侧控制器。无重新重定向、无PIE；当前左手编辑尚在进行，正式成品待用户完成后按既定流程统一烘焙，未将未完成左手编辑提前应用。


## 2026-10-21 复制Rifle01原生Offset关键帧

ManualAction正式源的offset_source_recipe显式指定同动作、同公共输入的源制作要求。prepare_action在目标已准备后，只复制唯一原生Additive层的通道默认值与关键帧，包括帧/子帧、值、插值模式、切线模式、切线权重模式及两侧切线/权重。源目标显示帧率与tick按有理数比较，段范围和通道集合必须一致。复制后完整回读对比，摘要证明其他层及武器/弹匣挂接轨道不变。结果记入offset_copy，后续打开直接保留用户继续修改，不自动重复覆盖。

用户明确只要求应用编辑键，禁止直接烘焙。已在当前上线步枪范围Rifle02、Rifle03的装备及换弹LS应用Rifle01的原生Offset；装备各73键/18带键通道，换弹各1950键/936带键通道（含源序列已有中性键）。Rifle03换弹先完成制作底稿准备。四条回读键值、时间、默认值和切线一致，底层与挂接不变，无正式AS烘焙、无运行引用修改、无PIE、无备份。窗口回到Rifle02装备供人工微调。


## 2026-10-21 Sequencer无效时间范围修复

prepare_action在恢复已有制作序列前检查view/work范围；只有NaN、无穷或倒置范围才按原播放区间及5%留白重建，正常缩放保持。修复保存并重开当前序列，比较全部通道摘要及播放区间，不改变动画内容。正式制作源timeline_ui_request=true可只执行范围修复并消费请求，不进入烘焙、源姿势同步或运行引用应用。

当前Rifle03换弹实机读取view结束为NaN，work正常；修复后view/work均为[-0.21666666666666667,2.35]秒。通道摘要及播放区间保持，保存后重开并求值成功。鼠标拖动由用户在前台确认，未运行PIE，未创建备份或临时资产。


## 2026-10-21 换弹11/33帧通知正式同步

ManualAction源的rifle_reload_timing是公共Rifle换弹时间约定（30 FPS，拔出11帧，插入33帧）。仅写源文件不会改变蒙太奇。先设置reload_timing_request=true，以prepare_action调用，write_paths精确列出DA实际配置的角色及武器换弹蒙太奇；该入口只同步通知，不切换编辑器，不写LS/Rig或用户控制键，完成后消费请求并记录reload_timing_applied。然后才以通常LS/Rig范围准备、烘焙和应用动作。

同步旧弹匣手持显示起点、枪体弹匣隐藏起止、新弹匣手持显示终点、装弹逻辑起点及出入音效；保留显示实例和实例上配置的变换、网格、速度参数。通过UE原生AddAnimationNotify(State)EventObject复用同一实例，核对事件数、实例身份、触发条件、过滤、服务端/跟随设置以及全部实际触发起止时间。不重建配置实例。生命周期、允许开火及其他未改轨道的时间保持；装弹逻辑持续时间保持。角色映射目前要求单片段、从0开始、1倍播放；枪体片段可不同速度，通知按蒙太奇时间修改，不能再乘枪体动画速度。

实际核对并修复Rifle01/02插入音效36→33帧、拔出音效→11帧；Rifle03双侧显示、装弹和音效10/36→11/33；当前SMG01双侧同样完成11/33（枪体片段速度0.454545，蒙太奇与角色仍为2.2秒）。四把枪均回读1.10000002384秒插入；通知原UObject实例保持，人工控制键未写。仅Rifle03已完成换弹及SMG01已确认参考装备执行官方直接烘焙、替换并显式保存正式蒙太奇，导出骨轨位置差0；SMG01换弹仍供人工编辑，未提前应用。前台保持LS_SMG01_CharacterReload。

其余型号仅核对、未批量改写：SMG02/03、LMG03、Sniper02/04仍需在各自制作轮执行此同步。LMG01角色旧动作2.833333秒与公共2.2秒不一致，必须先完成其正式制作时间映射，不能盲套秒数。Shotgun03使用弹壳/弹药手持表现，缺少普通旧/新弹匣对，不能套普通弹匣通知；该入口会拒绝。手枪、Minigun与逐发霰弹枪未写。当前SMG01制作预览的弹匣生命周期来自同步前的通知，需在用户编辑结束后的交接阶段仅同步显示时间，不重建或覆盖人工控制轨。

无PIE、无备份或兼容资产。本轮未清理Rifle03/SMG01历史制作资产，避免在用户编辑期间重现旧包删除故障；仅已完成动作的历史清理仍待独立收尾。


## 2026-10-22 公共换弹帧的时间比例

reload_timing_request使用time_space=common_source时，通知秒数按source_time_scale反向映射到型号制作/蒙太奇时间。LMG01原角色换弹2.833333秒、公共输入2.2秒，比例0.7764706；保持原有换弹时长、曲线/手指元数据输入采用当前本枪CharacterReload_Grip，公共身体动作按该比例采样。公共第11/33帧分别映射为蒙太奇0.472222/1.416667秒（30 FPS显示帧14.1667/42.5）。不是把33直接当成本枪显示帧。两侧通知保留原实例，枪体自身0.7764706播放速度保持，当前正式换弹引用仍待用户编辑结束后应用。LMG01装备已官方烘焙、替换保存；无PIE、无备份。


## 2026-10-22 LMG01正确Shotgun换弹基准（取代前述LMG01的Rifle时间映射）

用户明确指定原MM_Shotgun_Reload并要求迁入Used及首尾对齐。已原生迁移至/Game/_Project/Characters/BBBC_UA/Animation/UsedAnimation/shotgun/MM_Shotgun_Reload，旧包、重定向器及旧引用清零。唯一正式公共输入保留原名，不另建重复底稿；本轮误建的AS_Shotgun_ReloadFull_Base已核对当前哈希及无引用后原生删除。此前为这次派生源临时修改的工具源码已恢复，不保留额外入口或兼容分支。

正式Source/Animation/Shotgun_Reload_Alignment_RetargetActions.json.source记录原位首尾对齐（不重新重定向）：以MM_Rifle_Idle_Hipfire第0秒为基准，入口0–6帧、出口71–81帧，末尾4帧稳定。完整2.833333秒/86采样保持；6–71帧全部原骨轨位置和旋转验证保留，中段写入误差0.00001077cm，首尾最大误差0.00003306cm。检查结果original_source_unchanged=false是因为source与animation明确为同一个原位修改资产，不代表中段改变。四条IK/握姿抑制曲线按正式首尾窗口重建。

CommonActionBaselines中的shotgun.reload_full唯一引用上述MM资产（身体及手指），仅LMG01.reload映射改用该条目。LMG01制作源animation=finger_animation=上述Used/MM资产，source_time_scale=1；旧Rifle通知约定已移除，恢复原LMG01拔出0.3秒/第9帧、插入1.5秒/第45帧，原通知实例、配置及其它时序保持。修正前只读检查原生Additive层无人工关键帧，故清除错误底稿并原位重建LS；已重新打开LS_LMG01_CharacterReload第0帧及原生Offset层。新底稿全帧原姿势回读误差0.000106cm；正式运行换弹仍待用户编辑完成后烘焙应用。装备已应用不变。未跑PIE，无备份，无临时文件遗留。


## 2026-10-22 Shotgun换弹末节上翻修复

用户要求原位修复当前UsedAnimation/shotgun/MM_Shotgun_Reload。全轨检测30指节后，按既有中性伸展上限及超过5度规则，限定pinky_03_l、ring_03_l。小指异常区间4–7/21–26/42–45/66–69共18采样；无名指6–11/17–29/42–47/65–70共31采样，峰值43.64793度。仅用两侧安全采样平滑连接异常局部Yaw，位置、缩放、Pitch/Roll及其余骨轨回读保持；未重定向。

修后全轨最大Yaw小指-0.11819度，无名指11.27020度，分别不超过0/12.89972度上限。首尾腕/前臂与参考误差保持原值。正式Alignment源记录修复前后摘要及49个修改采样，catalog更新正式摘要；LMG01通过sync_finger_repair仅同步Absolute层49个Rotation.Z键，逐键旧值核验并摘要确认其他控制键与人工Offset不变。当前序列已保存并刷新至第0帧；未烘焙未完成的人工作品、未改正式运行引用、无PIE、无备份或临时资产。


## 2026-10-22 当前序列全部反向手指：基础轨与无键默认偏移同时核验

inspect_manual增加全部30指节的源/实际Sequencer导出最大Yaw和非零未打键手指Additive默认值报告。实际LMG01发现42个未打键手指旋转默认值作用于全段，左无名指第二节额外Yaw43.935度，使源最大-8.117度在最终序列变成+35.818度。此前仅修源动画不足以修复当前结果。最初尝试FK全局/局部空间互换没有消除此误差，已恢复原图全部GlobalSpace及生成方式，不保留这项无效变更。

ManualAction源可显式reset_unkeyed_finger_offsets_request=true，通过普通prepare_action作用于当前序列。仅清零没有任何关键帧的fk_*旋转默认值；记录全部原值，并核对所有关键帧的时间/子帧/值以及其他通道默认值不变。当前左手IK位置7/8/8键、旋转各8键、左肘各2键均保持，不清除手动控制轨，不改Rig求解逻辑。完成后消费请求，记录finger_offset_repair。

基础动画另以既有bridge_hyperextended_finger_yaw规则扩查双手24个非拇指指节。显式extension_limit_basis=reference_pose时上限采用max(0,正确参考Yaw)，minimum_excess_degrees=0.1，不再将骨架中性姿势的过伸容差当作最终可接受范围。新增修复左食指末节17采样、左中指末节19、左无名指末节40、右食指末节56，共132。只修Yaw，保持其余骨轨、位置/缩放和首尾参考。拇指全部检查，保留正常对掌角度，不把其旋转正号等同于异常。

源修复后通过原生finger同步仅写上述Absolute Rotation.Z键，其他键与人工Offset摘要不变。最终120 FPS官方瞬态导出341采样：42个无键默认偏移已清零，左侧四指全部指节最大Yaw均小于0，右食指末节最大1.574482度与正式参考一致；源与序列手指位置差0，旋转四元数点积最小0.999999938。当前LS_LMG01_CharacterReload已保存并刷新，未提前烘焙用户尚未完成的正式动画、未运行PIE、无备份或临时资产。


## 2026-10-22 LMG03也使用正式Shotgun完整换弹

用户明确指定LMG03换弹同样使用已迁移/基准对齐/完整指节修复的UsedAnimation/shotgun/MM_Shotgun_Reload。修改前只读确认当前LMG03换弹Additive无人工关键帧且没有非零手指默认偏移，故原位重建错误Rifle底稿。catalog中仅LMG03.reload改为shotgun.reload_full，身体与手指均引用唯一MM_Shotgun_Reload，原速2.833333秒/86采样。没有新增或复制公共资产。LS已保存、打开第0帧，原生Offset已选中。

LMG03原枪体片段2.2秒，通过现有retime_single_action_montage将枪体蒙太奇调整至2.833333秒、DefaultSlot保持、片段速度0.7764706，制作枪体预览据此同步。普通Rifle的11/33约定已从本枪制作源移除；两侧弹匣通知使用Shotgun9/45帧及原实例，预览已同步。手调完成后须使用正式配置蒙太奇入口把角色片段改为新2.833333秒（当前运行片段仍为旧2.2秒，不能使用只允许等长的替换接口），并同步换弹生命周期、阻火结束、允许开火至2.8秒。此待办已明确记录本枪源runtime_apply_requirement，未提前应用未完成的角色手调。

真实prepare全帧源姿势位置误差0.000106cm，源摘要为5be6e85aacbb8cbbb72cffb513a956e0bdc204376f4ca9bd800e791ebe881f77；指节继承同一个已修复Shotgun输入。无PIE、无备份和临时资产。


## 2026-10-22 LMG03装入弹匣改为第47帧并完成应用

用户确认手调完成，明确本枪插入改为47帧。LMG03普通弹匣通知范围本轮为9/47帧（30 FPS）；角色新弹匣结束、武器显隐结束、装弹逻辑开始和插入音效均原实例同步到1.5666667秒，出弹0.3秒保持。继承Shotgun完整2.833333秒而非旧2.2秒，生命周期与阻火结束、允许开火统一2.8秒/84帧。手指使用已修复的唯一公共Shotgun基准。

新增显式ManualAction apply_baked_request：prepare_action以唯一角色蒙太奇write_paths应用已有成功bake_result，只改当前单片段的动画引用、源起止与1倍速度，按烘焙输出更新时长，不重建蒙太奇或重设混合/通知。实际LMG03从旧2.2秒改为新2.833333秒，UpperBody保持，原blend_in0.25和blend_out0.4回读保持。正式动画341采样、官方直接烘焙全轨位置差0，蒙太奇保存与片段引用回读正确。普通同步入口支持显式reload_end_seconds联动生命周期/阻火/允许开火尾点，其余通知和实例参数保持。

新增preview_timing_request：以通常LS/Rig/Preview范围prepare_action，只更新现有OldMagazine/NewMagazine生命周期及枪体显隐预览，保留绑定和全部人工控制/附件Transform键。LMG03旧弹匣[9,17)、新弹匣[25,47)显示帧；全部控制及Transform通道摘要保持，最终当前LS与已应用AS再次官方导出比对误差0，existing_output_matches_preview=true。制作源runtime_applied=true，时长交接待办标为完成。源保留magazine_timing=9/47，不扩大修改其他型号。未运行PIE，无备份、无兼容跳转或临时资产。


## 2026-10-22 Sniper02正式右腕角度的制作预览

用户要求当前Sniper02装备序列应用已手调的右腕角度。真实读取DA的right_hand_grip_rotation_offset，其四元数为[0.1193930358,0.1331199110,-0.1653194875,0.9698937535]，与握姿制作源校准一致。运行Base对hand_r施加ParentBoneSpace加法旋转，因此不能将同一角度直接烘焙进原动作再由运行时重复施加。

ManualAction可显式runtime_right_wrist_preview=true。prepare在当前Rig已有IK求解及ik_hand_r拷贝之后、手指FK之前，读取hand_r局部变换，使用RigVM QuaternionMul按D*LocalRotation写回局部旋转，保持局部位置缩放及上臂/前臂求解。未改控制器键、DA、武器挂接或公共动作。LS保存BBB_RuntimeRightWristPreview四元数标签；原生_export在瞬态动画中逆乘D以还原raw hand_r旋转，正式运行再由既有右腕节点应用一次。该标签是明确的运行预览语义，不是旧资产兼容。当前Sniper02装备与后续换弹制作源均启用，其他型号未批量写入。

初始准备阶段复用含该预览节点的Rig时暂时关闭其Weight；重建LS清除预览标签，在manual_edit_ready阶段恢复Weight1并写入当前实际DA角度。重复打开同一角度及Weight1时不累计添加节点或修正。当前装备实际生效，所有通道键摘要保持；前后官方120 FPS瞬态导出、扣除运行预览D后的全骨轨位置误差0.0000992cm，旋转/缩放通过原有比较；重复prepare再次通过。未运行PIE、未烘焙未完成的用户手调、未改正式运行引用，无备份与临时资产。

## 2026-10-22 霰弹枪分段换弹只对齐外侧端点

BBBNativeRetargetActions 的每项 entry_frames、exit_frames 可显式为 null；至少指定一侧。单侧入口复用原 finalize，仍校验原资产摘要、帧数和窗口，使用最短弧旋转平滑，只核对所指定端点与参考一致；另一端及窗口外全部骨轨位置、旋转、缩放回读保持。四条 IK/握姿抑制曲线在入口结束后保持禁用，在出口对齐完成时恢复，末尾稳定段保持零。已对齐资产重复调用只核验摘要，不重复累加。

Shotgun01 公共 AS_Shotgun_ReloadStart_Base 仅入口0–6帧对齐 MM_Rifle_Idle_Hipfire，6–25帧保留；AS_Shotgun_ReloadEnd_Base 仅出口3–13帧对齐，0–3帧及装填接口保留，最后4帧稳定。正式源为角色 Source/Animation/Shotgun_PhasedReload_Alignment_RetargetActions.json.source，catalog 采纳两条新摘要并保存参考及制作源。单发 AS_Shotgun_ReloadInsert_Base 未写入，catalog 全部19基准/14武器/27制作要求通过。双臂外侧端点最大差0.00003494cm，开始→装填、循环、装填→结束最大差0.00005251cm，旋转最大0.000108度；源输出长度和骨轨数量保持。专属运行成品仍待各枪人工制作后烘焙应用，本轮未切换其运行引用。

手枪保持自己的完整动画组，已打开 LS_Pistol_CloseHold_BodyPose 供用户修改第0帧双臂基准；当前挂接与 DA 一致。原生纯瞬态 Sequencer 导出与正式 AS_Pistol_01_HandGrip 第0帧比较无差异，未改控制键或 Rig。临时播放器直接读取曾返回未刷新骨骼缓存，不作为预览姿势错误或 IK 权重失效的证据；实际图使用直接双臂求解，不受该旧权重字段控制。用户确认新基准前不重烘整组手枪动作，不重跑已有 result 的旧任务。未运行PIE，无备份、兼容包或重新重定向。

## 2026-10-22 逐发换弹原生Offset制作

ManualAction/schema2 增加 reload_start、reload_insert、reload_end，继续使用 process_dual_arm_body_pose 的原有 prepare_action/bake/inspect 入口。ACTION_MONTAGE_FIELDS 明确对应角色及枪体配置字段：开始/结束读取各自 start/end 蒙太奇，单发装入读取 reload_montage；应用成品使用同一字段映射，不猜测资产名称。公共目录按相同阶段键验证源和时长，LS、Rig及必要枪体预览AS仍归本型号原有目录。普通reload的旧/新弹匣完整性检查保持，三段逐发换弹不套普通11/33帧约定。

预览从真实 BBBCharacterHeldObjectDisplayAnimNotifyState 读取 ObjectMesh、HandBoneName、HandObjectTransform 及原生起止时间，在 held_objects 中记录并建立可选择附件；与 magazines 分开保存。实际挂接校验覆盖手持物体，不改运行通知实例或武器代码。三段均继承显式 runtime_right_wrist_preview，原生导出扣除运行右腕旋转以避免重复应用。尚未完成的阶段只保留正式制作要求，不提前烘焙。

实机完成Shotgun01装备官方120 FPS烘焙并保存正式蒙太奇引用，骨轨误差0。新 LS_Shotgun01_CharacterReloadStart 从已对齐的公共开始基准准备26采样，原生Offset已选中，右腕预览扣除后的导出误差小于0.00012cm，全部控制键摘要保持；HeldObject_0在30 FPS第12–24帧显示，变换来自原通知，附件实际回读通过。枪体存在显隐状态，明确保留 ReloadStart_AuthoringPreview 作为有效制作输入。开始动作尚待用户手调，未应用运行成品；未运行PIE，无备份或旧路径兼容。

## 2026-10-22 开始换弹末姿衔接原生装填循环

reload_insert 的正式ManualAction可显式指定 phase_handoff_recipe，要求同武器、已准备的reload_start源及唯一原生Offset层。match_reload_phase_offset用原生通道evaluate_keys在Start末帧求值，将非中性偏移作为循环整段常量（0帧和末帧相同线性键）写入目标Offset；保留原装填底层轨迹和附件，不自行解释人工中间阶段。UE原生Additive的缩放通道中性值同样为0，只有Weight为1。已有非中性目标人工编辑会拒绝覆盖；phase_handoff记录成功结果后再次准备不重复拷贝。

先在纯瞬态副本上试写并通过官方120 FPS导出，核对双肩、肘、腕和30指节的循环首尾与Start末帧，再写正式LS；比较源完整通道摘要及目标非Offset摘要，保证Start用户键、底层和附件保持。未提前应用循环成品。瞬态副本统一通过_copy_sequence保留BBB_RuntimeRightWristPreview标签，防止公共底轨验证和探针遗漏右腕逆补偿；副本使用不与导出目标冲突的名称。原生Offset段已保存但制作源尚未保存的中断恢复会补齐阶段事实，再执行实际偏移探针，不重建段或覆盖关键帧。导出缺少唯一角色绑定时明确报告序列与网格路径。

Shotgun01人工Start官方烘焙101采样、0.833333秒、全轨误差0，原角色开始蒙太奇引用已保存。Insert接收13个末帧非中性通道：左手IK位置/旋转和左拇指逐节旋转；真实循环两端对Start末帧最大位置差0.000054994cm、旋转差0.037144度，底层和附件摘要保持，Start通道摘要f08453c826632bc79a63c9c24908c94fe6dd7155374e8dd1c21fa22ddff2ee8c保持。LS_Shotgun01_CharacterReloadInsert已打开第0帧及原生Offset层供用户审核，runtime_applied=false；未改通知时间、未跑PIE，无备份或临时Content资产。

## 2026-10-22 循环装填应用与结束段原生衔接

phase_handoff_recipe及phase_handoff统一表达分段换弹的相邻制作源和成功事实，仅接受同武器Start→Insert、Insert→End。既有Insert源已原位迁移字段，不保留旧字段兼容。Insert继承整段常量；End显式handoff_release_frames=[3,13]，原生线性键在0/3帧保持继承值，13/末帧归零。用户可直接在Sequencer编辑，未添加自定义插值算法。成功记录存在时不重复覆盖；非中性人工目标编辑仍拒绝覆盖。

结束段先在瞬态副本核验入口与Insert末帧一致、出口与中性Offset目标末帧一致，再写正式LS，保持源键、非Offset底层和附件摘要。中性与实际输出统一120 FPS官方导出比较，避免以初始化导出最后一帧作为正式末帧。Shotgun01 Insert已按用户批准烘焙45采样/0.366666675秒，全轨误差0，角色ReloadInsert蒙太奇引用保存且原混合设置保留。End继承13通道，入口/出口最大位置差0.000041657cm、角差0.040551度，原生Offset探针左手0.999999cm、右手0；正式LS已打开供手调，结束段尚未应用运行成品。未改通知、配置或运行IK；未跑PIE，无备份和兼容资产。

## 2026-10-22 一次式手持弹药换弹预览

普通reload预览按真实通知接受完整OldMagazine/NewMagazine组合，或无弹匣通知且存在有效HeldObject的换弹；缺少表现输入和仅一侧弹匣通知仍拒绝。不再将一次换弹等同于可拆卸弹匣换弹，不新增配置开关。Shotgun03实际两条手持弹药通知通过现有物体网格、骨骼、变换和生命周期读取，原生Offset制作序列准备完成67帧，公共身体预览误差0.000335cm以内，右腕实际修正预览保留；未改通知或运行玩法，未运行PIE。装备已官方直接烘焙201采样、1.666667秒、全轨误差0并保存角色装备蒙太奇引用。

## 2026-10-22 原生帧段拼接通用单次装弹

BBBNativeRetargetActions的capture可使用每个job的source_frame_ranges（闭区间）直接从同骨架原动作采样，不经过IK重定向；按源顺序拼接，新增明确输出，拒绝原位覆盖和非连续接缝。保存前逐骨核验接缝组件空间位置/角度、全部输出位置/旋转/缩放以及源摘要。输出去除原通知和曲线，之后由既有finalize建立明确首尾窗口及抑制曲线；已有成功输出只回读核验，不重复裁切或覆盖。

用户明确纠正Shotgun03的原动作必须是Shotgun01来源BigLocomotionPack的anim_shotgun_aim_reload，而非Lyra MM_Shotgun_Reload。原完整73采样/2.4秒资产已原生迁入UsedAnimation/shotgun，旧路径和重定向器清零。新增AS_Shotgun_ReloadSingle_Base取原0–25及55–72帧，44采样/1.433333秒，接缝位置差0、最大旋转差0.042760度，全轨位置写入误差0，完整源保留。入口0–6及出口29–39对齐Rifle参考，最后4帧稳定，首尾最大位置误差0.000033059cm。Shotgun03制作源/catalog已切换，正式LS原位重建并打开原生Offset；公共身体预览误差0.000139cm以内。两发手持弹药的原网格和局部变换保留，角色通知显示区间调整到首次装入的0.4–0.8秒；角色运行动画尚待人工完成后烘焙引用，枪体装入/结束通知同步留待该次应用完成。未运行PIE，无临时Content资产、备份或兼容入口。

## 2026-10-22 单把动作固定右腕显示角度

ManualAction显式freeze_right_wrist_rotation_request通过prepare_action将当前第0帧显示右腕方向保持到整段。仅写hand_r_ik_ctrl的三个原生Offset旋转通道，保留底轨、位置缩放、左手和附件全部键。计算包含现有右腕预览旋转的父空间补偿，原生导出回读实际手骨角度和位置；在瞬态候选通过全帧检查后写正式LS。请求成功消费，不在每次准备时重新锁定用户编辑；输出仍是可直接编辑的原生键，无运行时代码链条和自定义时间插值。

Shotgun03当前44帧换弹已执行，原生导出显示右腕方向固定检查通过（误差上限0.1度），左右腕及左臂原位置保持（上限0.02cm），非目标通道时间/值/默认值摘要保持；具体实际误差保存在正式制作源right_wrist_rotation_hold。没有改公共Single底稿或武器DA，尚未烘焙应用，未运行PIE。无备份、兼容资产或本次临时Content输出。

## 2026-10-22 单次装弹成品应用与角色/枪体通知同步

既有sync_reload_timing支持显式single_reload_application_timing：要求已应用的正式烘焙成品，按held_object_frames/load_frame和成品长度同步一次式手持弹药换弹。保持真实通知实例、全部可编辑属性及事件元数据，保留通知数量与轨道归属；装入结算仍恰好一次。枪体唯一完整片段通过播放速率同步成品总长，其余表现事件按原蒙太奇归一化时间缩放，枪体显隐结束/装弹音与实际装入时间一致。阻止开火与允许开火安排在结束前一显示帧，生命周期到成品结束；不增加玩法代码。普通弹匣流程保持原有11/33等显式时序，单次手持弹药不套旧新弹匣完整性要求。读取并核验保存后通知原生时间、实例身份、元数据以及两侧实际蒙太奇长度。

Shotgun03用户确认成品已官方120 FPS烘焙173采样/1.433333278秒，全轨误差0；UpperBody引用当前ManualEdit、原混合配置保留。枪体DefaultSlot保持本枪原1秒动作，速率0.697674453，总长同为1.433333278秒。两发手持弹药0.4–0.8秒；唯一LoadAmmo通知0.8–0.833333秒，装入音0.8秒；允许开火1.4秒，Lifecycle结束1.433333秒。九个枪体通知及两个角色通知实例保留，全部时间范围回读通过。正式制作源runtime_applied=true，weapon_timing_sync_pending=false。未改武器DA、公共底稿或手调序列键，未运行PIE；无备份、兼容资产和本次临时Content输出。

## 2026-10-22 原位刷新枪体预览动画

ManualAction制作源可显式设置refresh_weapon_animation_request，由既有prepare_action读取当前DA的角色/枪体蒙太奇及实际播放速率，复用_weapon_preview_animation把最新枪体骨轨和实际显隐区间写入本型号正式AuthoringPreview，并替换唯一有内容的Weapon动画轨；空动画轨不参与唯一性计数。刷新前后全部控制与Transform通道摘要一致，不重建绑定、不清空人工Offset或附件位置。消费请求后继续原生Offset准备并打开第0帧。

Rifle02运行枪体弹匣骨轨已清理，但LS仍使用旧AuthoringPreview，本轮已刷新。预览Magazine_joint全段位置保持安装姿势，11–33帧仅使用缩放隐藏，33帧恢复；骨轨长度和每帧显隐缩放由原生回读核对。LS刷新及后续准备成功、dirty为空，人工控制键/附件摘要保持。未重新烘焙角色成品、未运行PIE，无备份或兼容资产。

## 2026-10-22 弹匣预览显隐帧边界

枪体AuthoringPreview的显隐窗口改为源采样帧闭开区间，以ceil(seconds*fps-0.0001)转换开始/结束，和附件生命周期采用相同的浮点帧对齐语义。避免通知11/30秒存储为0.3666666746而第11帧采样为0.3666666667时漏隐藏。保存制作源weapon_preview_frame_boundaries，来自输出骨轨实际缩放回读。Rifle02实测10帧scale=(1,1,1)、11与32帧=(0,0,0)、33帧=(1,1,1)，现有控制键和Transform摘要保持，正式通知时间未改。未运行PIE，无备份或兼容资产。

### 动作首尾同步已应用握姿（2026-10-23）

ManualAction 制作源可显式设置 `grip_endpoints_request`，包含同型号正式握姿 `animation` 和四个显示帧 `frames=[起帧,离手过渡结束,回握过渡开始,末帧]`。既有 `prepare_action` 入口只在原生 Additive 层写左手 IK 与左手指 FK 的首尾修正，保留中段关键帧、身体底轨及附件轨道。首尾手掌目标按参考握姿相对右手的完整变换求得，包含显式启用的运行右腕预览；过渡由 UE 原生 AUTO 关键帧曲线完成。正式修改前先在瞬态候选中用官方 Sequencer 导出核验手掌与全部左指局部角度，不创建备份资产。请求成功后消费，后续打开不会重复覆盖。

占用范围为目标 LS；启用 `runtime_right_wrist_preview` 时同时列入原 Rig。Sniper04 以当前 AS_Sniper_04_HandGrip 修正 0/6/60/66 帧范围，首尾位置最大误差 0.000032915cm、旋转最大误差 0.04047度。正式换弹重新烘焙265采样、2.2秒，与实际序列导出误差0，已应用原角色换弹蒙太奇并保留原混合设置；窗口留在 LS_Sniper04_CharacterReload。未运行 PIE。

### 换弹实际编辑器预览核验（2026-10-23）

ManualAction 明确设置 `inspect_editor_grip_request=true` 后，原 `prepare_action` 入口读取当前已经打开的编辑器绑定实例、组件世界骨骼、附件局部变换和 Rig 手骨。只读取当前 Sequencer 实例，不创建第二播放器、不在采样时重新求值；要求 LS 已打开并给编辑器完成一轮正常求值。结果返回实际 Root_joint 缩放，避免仅用经过重定向的 AnimPose 数据判断枪体动画尺寸。请求在读取后消费。

Sniper04 定位出两个实际预览问题：临时播放器结束后共享预览组件与 Rig 状态不一致，需关闭实际资产编辑页后重开；枪体换弹根骨原始缩放仍是1.0，而重导入网格参考根骨为0.9，AnimPose 重定向采样会掩盖这种原始骨轨差异。已将正式 ANI_BBB_Sniper_04_Reload 和正式 AuthoringPreview 的67个根骨采样统一为实际网格参考根骨，其他骨轨及显隐不变。重开后直接读取编辑器组件，根骨缩放0.899999976，左手组件与Rig位置一致，左手首帧[-8.712429,40.746600,143.908958]cm与已确认握姿一致。只核验前台组件及骨轨，未运行PIE；窗口留在换弹第0帧。

### 开火枪体原始根轨缩放核验（2026-10-23）

`inspect_editor_grip_request` 可为含 `root_tracks` 数组的对象，明确列出同型号 Animation/Sequence 动画；原入口同时返回原始首骨轨各采样的位置、四元数和缩放，不经过 AnimPose 重定向。便于保留位置和旋转，仅用既有 replace_animation_bone_tracks 改写必要缩放。

Sniper04 正式 equipment_fire_montage 指向 AM_BBB_Sniper_04_Fire，其唯一序列 ANI_BBB_Sniper_04_Fire 的13个原始根采样缩放均为1.0，与当前网格参考根0.9不一致。已原位将这13个采样的缩放统一为实际网格参考根[0.899999976,0.899999857,0.899999857]；回读全部13采样一致。保留根骨位置和旋转方向，其余枪机骨轨、通知、蒙太奇引用及角色握姿未改。未运行PIE。

### 逐发换弹开始只修入口握姿（2026-10-23）

`grip_endpoints_request.frames` 支持两帧 `[0,入口过渡结束]`，只对齐开始姿势，不把逐发换弹开始段的末帧改回握枪，保留装填阶段衔接。四帧首尾窗口继续使用原契约。`finger_sides` 显式指定 l/r，默认仍仅左手；双侧时使用同一正式握姿的局部指骨旋转。仍通过原生 Additive AUTO 键过渡，候选先由官方 Sequencer 导出并核验，未通过不写正式序列。

Shotgun01 换弹开始按已应用 AS_Shotgun_01_HandGrip 修正入口0–6帧、双手指骨；入口手掌位置误差0.000028325cm、指骨及手腕最大旋转误差0.03544度。保留第6帧后的原编辑和末帧装填衔接，完整人物预览继续使用 Sk_CombinedMesh。此次修改制作LS，未提前烘焙角色运行动画，未运行PIE。

可显式提供 `grip_recipe_path`，限定同型号、已应用且动画引用一致的人工握姿制作源；掌间完整变换及指骨旋转直接采用已确认人工 solution，避免 AnimPose 重定向后姿势替代人工标定。最终 Shotgun01 入口候选位置误差0.000030595cm、最大旋转误差0.03536度；重开后直接回读编辑器当前帧为0、角色组件与Rig一致。仅修改当前制作序列，未烘焙运行成品。编辑器曾发生Slate崩溃，已恢复前台编辑器后重新核验保存结果。

### 人工左臂稀疏关键姿势连续化与审核烘焙（2026-10-23）

ManualAction 的 `smooth_left_request` 由既有 prepare_action 执行。apply=false 返回关键点、插值类型和旋转跳变检查；apply=true 通过 UE SMART_AUTO 原生键重建左侧位置/旋转切线。include_base 可纳入原绝对层。consolidate 明确采纳当前手部人工关键点为锚点，在原帧号及子帧上求原绝对层与叠加层总值，将左手、左肘、左锁骨和实际存在的对应左臂源控制器合并为稀疏原生叠加键；常量部分仍在原绝对层。不引入自定义时间插值，不重建绑定。核验每个人工锚点的控制总变换保持，右侧、身体其余通道和附件轨道不变；以120 FPS官方导出对比腕部及肘部轨迹。

Shotgun01 ReloadStart 现有人工锚点含6.535、11.4175、16.845、20.6325、25.97625等小数帧。仅切换自动切线不能消除底稿与偏移叠加产生的中间突变，因此按人工关键姿势合并左侧运动后再用UE原生曲线连接。最初/最终手腕峰值加速度90614.89/11218.66 cm/s2，左肘39149.05/24809.39 cm/s2；关键姿势控制总值回读通过。结果已烘焙为 ANI_BBB_Shotgun_01_CharacterReloadStart_Smooth 独立审核动画，未改原运行蒙太奇引用。

bake 可显式启用 preserve_authored_end，若人工叠加键晚于源动画末采样，在纯瞬态输入中保持源末姿势延长到覆盖该子帧的完整源帧，副本段末端延长一导出采样以避免末帧失效。原动画和用户LS播放区间不改；曲线通过同长度瞬态输入复制。审核版105采样、0.866667秒，原生骨轨回读误差0，预览网格沿用实际制作网格 Sk_CombinedMesh，动画编辑窗口已打开。实际未运行PIE；并行会话测试占用时按调度等待。

### 原位重置制作序列为公共基础动作（2026-10-23）

ManualAction制作源显式设置reset_base_request=true，通过prepare_action执行，write_paths只允许当前LS。重新从data.animation采样全部源骨骼、双臂控制器和逐节FK，清空原生Additive层关键帧并将位置、旋转、缩放增量归零；保留原绑定、附件、完整人物模板和可编辑叠加段。候选先进行官方导出及全源帧骨骼对比，通过后才保存正式LS，不改公共动画或运行引用。原生Additive缩放的中性增量是0，绝对层缩放才是1，已有专项检查保护。Shotgun01 ReloadStart实际还原26个源采样，全骨骼组件姿态位置最大误差0.000082889cm，手部IK辅助骨按既有约定排除；保留武器附件，清除旧端点、去抖及烘焙记录并回到第0帧。
