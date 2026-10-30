# 持枪表现只读采样

2026-10-30：正式运行验收先确认目标武器实际装备，再检查动画库切换。默认 DoNotInterrupt 可让空手 continuing pose 在换装备后继续保留，不能只核对候选库；需对比当前命中库。端枪相位与显示权重分开存储，0.25/0.30 秒线性相位经 EaseInOut 后共同驱动姿势及 AimIK，每帧仅推进一次。因 PIE 销毁而取消的输入回放不计通过；当世界已不存在且 clockOverridden=false 时，只回收失效的输入活动登记，保留原回放的取消和释放错误供查询。

2026-10-30：沿用 `animation.start_locomotion_runtime_probe` 与 `animation.stop_locomotion_runtime_probe`。不增加独立启动入口。实现位于 `Scripts/BBBPresentationProbe.py`，由现有移动探针调用。

每条 `runtime_sample` 增加 `presentation`：

- `componentBones`：根、骨盆、脊柱、颈、头、左右肩臂手和脚共 17 根骨骼的最终组件空间位置与四元数。缺骨明确列入 `missingBones`。
- `meshWorld`：网格世界变换，用于与组件空间数据区分。
- `aiming`、`running`、`fireIntent`：主动画实例公开的基础事实。
- `hasMuzzle`、`muzzleInHandR`、`aimTargetComponent`：枪口是否有效、右手空间枪口变换、组件空间目标。
- `hasLeftHandTarget`、`leftHandTargetInHandR`：左手握持目标是否有效及其右手空间位置。
- `mainCurves`、`layers[].curves`：禁用 AimIK、左手 IK、左右握姿的长短名称曲线，供核验实际使用名称，不能仅凭短名为零认定曲线缺失。
- `layers`：实际链接层的端枪权重、AimIK 权重、跟随速率与角色后坐力时间、权重。不存在的字段写入 `missingProperties`。

该模块只读，不强制求值骨骼，不调整网格更新策略、动画属性、控制器或输入。向量与四元数非有限数值会明确报错，由现有探针错误记录处理。有效性标记为 false 时，不把对应目标当作真实握持或枪口数据。

采样由 Slate 回调触发，不保证覆盖每个引擎帧。按 `native_runtime.frame`、世界时间和 `deltaSeconds` 对齐；不可把相邻 JSONL 行一概当作相隔 1/60 秒。需要完整骨骼帧覆盖时使用原生 MM 探针，并检查缺帧报告。

分阶段证据沿用 `blueprint.configure_transient_pose_watches`，非 PIE 时对明确 GUID 配置，结束后显式 `enabled=false`；最终组件姿态与中间 Pose Watch 要分别比较。不要以最终手腕异常直接推断 AimIK 的骨链包含手腕。

输出仍为 `Saved/temp/LocomotionRuntimeProbe/BBBLocomotionRuntime.jsonl` 和脚部 CSV；再次启动会覆盖。停止后可将本任务报告移到自己的临时目录整理。禁止覆盖或删除其他会话正在使用的报告。

验证：语法解析通过；真实 FAL PIE 已读取全部 17 根骨骼、瞄准事实与链接层数据。两次 300 帧固定模拟步长的短输入对照均确认 `state=finished`、`releaseAck=true`、`clockOverridden=false`。这些是诊断采样与接口验证，不是武器玩法或多人验收。
