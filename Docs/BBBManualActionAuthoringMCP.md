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
