# 武器关卡序列完整人物预览

本项目武器制作序列统一显示 `/Game/_ThirdParty/Characters/UkraineSoldier/Meshes/Sk_CombinedMesh`。适用目录为 `/Game/_Project/Characters/BBBC_UA/Items/Equipment/<类别>/<型号>/Animation/work/`。

`BBBWeaponSequencePreview.py` 维护显示网格与计算网格的区分。制作源的 `character_mesh` 或 `mesh` 继续作为握姿、插槽及骨骼求值的计算依据；完整人物只替换角色 Spawnable 模板的显示网格。序列元数据 `BBB_WeaponCharacterPreview` 明确记录原计算网格、显示网格和角色绑定 GUID。绑定查询只接受精确网格或这份明确映射，不能按相似骨架猜测角色。

## 已有工具入口

- `grip.author_weapon` 的 `manual_prepare` 在新建或恢复握姿编辑时更新完整人物预览。`manual_prepare_fire` 沿用同一个制作入口。
- `control_rig.process_dual_arm_body_pose` 的 `prepare_action` 在恢复装备或换弹编辑时更新完整人物预览。
- 握姿源或 ManualAction 源可显式设置 `full_character_preview_request=true`，通过上述入口只执行预览更新，成功后消费请求。不执行求解、重建控制器、生成附件、烘焙正式动画或应用运行引用。
- 握姿源的请求也可为 `{"sequences":["/Game/.../Animation/work/LS_..."]}`，明确列出本型号的其他制作序列。仅接受同型号 work 直属资产，逐个核验；中途失败时已完成项仍为已保存状态，可以原请求重试。

## 保存与核对

只允许同骨架替换。修改正式模板前，在瞬态副本中由官方 Sequencer 导出比较骨轨；保存前再次检查所有轨道通道的关键帧、默认值和角色绑定 GUID。序列不重建，轨道、武器挂接、弹匣显隐及通知配置不重写。该导出仅用于检查，不保存动画成品。

如果原握姿应用指纹在更新前有效，仅显示变更核验通过后更新对应指纹及精确引用它的同型号动作制作记录。原本失效的指纹不会因此被认定有效。预览记录和预览请求不参与握姿计算输入摘要。

重复打开已更新序列返回 `modified=false`。没有增加运行时动画处理。PIE 期间拒绝更新，按 MCP 调度等待所属测试结束，不抢占其它任务的 PIE。

## 本轮核验（2026-10-23）

14把武器共113个已有工作序列已检查并保存为完整人物预览，包含57份当前制作记录及56个其他工作序列。各修改项的官方瞬态导出骨轨位置误差均为0，全部通道及绑定保持。所有预览请求已消费；再次打开Shotgun01未开火握姿返回resumed，角色模板回读为Sk_CombinedMesh。6项绑定保护检查与2项既有时间轴专项检查通过。本轮未烘焙运行动画、未替换蒙太奇引用、未启动PIE。
