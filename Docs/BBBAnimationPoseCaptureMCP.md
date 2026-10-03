# 通用动画姿势截图

使用已注册的 `BBBAnimationMigrationToolset.capture_animation_pose` 渲染指定帧

- 支持人物与武器骨骼网格 不要求前臂辅助骨
- 动画与网格必须使用同一骨架
- 必须在启用渲染的 PIE 宿主中调用
- `focus_bone` 指定观察中心 `camera_offset` 指定相机偏移
- 临时预览对象与截图相机在调用结束后销毁
- 输出图像位于项目 `Saved/Diagnostics/ArmTwist/Captures` 使用者完成检查后删除

## Niagara 固定时刻截图

`BBBGenericEditorToolset.capture_niagara_preview` 接收 `system_path` `age_seconds` 与 `file_name`

在渲染 PIE 中生成临时特效对象 按 120 Hz 步进至指定时间 隔离渲染后销毁临时对象

输出位于 `Saved/Diagnostics/NiagaraCaptures` 不修改源特效 不向关卡保留对象 检查后删除输出

`BBBGenericEditorToolset.inspect_pie_static_mesh_instances` 根据 `mesh_path` 检查 PIE 中生成的物理占位物 返回数量 速度 是否正在物理模拟与剩余寿命
