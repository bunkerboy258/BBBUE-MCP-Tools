# 骨骼部件刚性附着工具

`Scripts/BBBRigidPartToolset.py` 已加入 `BBBMcpBootstrap`。实际工具集名称通过 `list_toolsets` 发现，不固定 Python 类型哈希。

## 工具

- `inspect_reference_attachment(mesh_paths, bone_name)`：只读返回多个骨骼网格共用骨架的组件空间参考姿势和逆变换。调用方必须核对网格的绑定姿势与该骨架一致。
- `configure_rigid_blueprint_part(...)`：在指定 `SetLeaderPoseComponent` 节点前，按部位名称分流；其它部位保留原有姿势跟随，目标部位调用新建的蓝图附着函数。函数清除 LeaderPose，切换单节点动画并清空动画资源，附着到指定骨骼，再设置参考姿势逆变换。没有逐帧脚本，没有新运行时系统。
- `validate_rigid_part_selection(...)`：在唯一单人 PIE 世界创建瞬时真人与预览人物，以独立复制的选装结构执行指定公开 Python 方法，依次切换目录条目，并通过项目已有原生姿势求值接口采样动画。检查附着、LeaderPose、内部骨骼不变形和附着位置；输出 JSON 与实际 SceneCapture 图片。临时 Actor 和灯光始终在 `finally` 清理。

## 编辑约束

1. 先通过 Perforce 独占签出蓝图，不提交或回退资产。
2. 明确提供姿势节点、部位输出引脚和唯一的新函数名称。必须先核对参考骨架；不适用于参考姿势不同的混合部件。
3. 只在非 PIE 时编辑；不覆盖已有函数，不覆盖报告或截图。修改通过事务记录，编译失败时不保存，必须检查或撤销未完成事务。
4. 每次编译后重新取得节点及引脚，不保留编译前的原生引脚引用；蓝图编译可能销毁原引脚。
5. 用 `compile_blueprint` 和显式 `save_assets` 完成目标资产保存。不要保存全部脏包。
6. 验证要求 `BBBBlueprintEditorLibrary` 的 `SpawnTransientPIEActor`、`EvaluateAnimationPreviewPose`；这些依赖位于接入项目，不在 MCP 仓库内。选装结构需要 `parts`、`slot`、`item` 字段，组件需要指定的公开组装方法。

## 当前项目实例

- 函数：`BPC_BBBCharacterAppearance.ApplyBackpack`
- 分流：`ApplyPart.K2Node_CallFunction_77`，部位来自 `K2Node_BreakStruct_5.Slot`，值为 `Backpack`
- 附着骨骼：`spine_03`
- 参考网格：`/Game/UkraineSoldier/Meshes/Backpacks/SK_backpackBig`
- 验证方法：`preview_appearance`。仅测试瞬时、禁用 Actor 复制的验证人物，不修改玩家人物和存档。
- 验证报告位于接入项目 `Saved/Diagnostics/RigidParts/`。

此方法使整个背包和肩带一起保持参考形状。它不是肩带蒙皮修正或布料模拟工具；遇到明显肩带穿插应先审核实际模型，不自动扩大改造范围。
