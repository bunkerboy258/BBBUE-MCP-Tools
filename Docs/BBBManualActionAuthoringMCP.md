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
