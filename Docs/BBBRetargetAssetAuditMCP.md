# 重定向资产审计与独立资产准备

通过已发现的 `run_editor_script` 加载 `Scripts/BBBRetargetAssetAuditToolset.py` 后，重新执行 `list_toolsets` 与 `describe_toolset` 获取当前注册名称。

- `inspect_retargeter(asset_path)` 使用官方控制器读取操作栈的启用状态和设置，返回源目标网格、IK Rig 和 Perforce 连接状态。
- `inspect_animation_poses(asset_paths, mesh_path="", sample_count=13)` 使用原始动画数据采样根、骨盆和手脚 IK，返回组件空间位置、四元数与 FK/IK 关系。`sample_count=0` 检查全部帧。空网格使用动画骨架。指定网格必须与动画骨架一致。结果仅通过 MCP 返回，不写诊断文件。

两者不修改或保存资产。局部 IK 轨道是否恒定不能单独用作失败判据；应与源动画的组件空间关系对照。正式重定向与资产写入应由对应资产工具执行并遵守独占签出规则。

`configure_root_motion_retargeter(asset_path, source_mesh_path)` 配置已独占签出或打开添加的独立重定向器与源动画预览网格。源根骨通过专用 setter 设置为 root，并核验七组辅助 IK 骨映射后保存。完成后须用 `inspect_retargeter` 独立回读操作栈。

该配置保留已有姿势与 FK 设置，移除 Run IK Rig，明确复制源 root 的运动及高度。末端标准 Pin Bones 操作把辅助 IK 骨设置为重定向后手脚的组件空间变换。它不复制原始源 IK 局部轨道；仅用于辅助 IK 骨跟随手脚的动画需求，不能用它处理 IK 与手脚需要保持独立轨迹的动画。

`open_new_assets_for_add(asset_paths)` 仅为明确列出的、尚未纳入版本控制的自有资产打开 Perforce 添加。已打开添加的包直接跳过，受控或存在冲突的包拒绝处理。不提交或操作引用资产。

`retarget_sequences(source_paths, retargeter_path, target_folder, overwrite=False)` 使用官方批量重定向，目标限定在自有目录，不包含引用资产。覆盖必须显式开启，且所有已有目标必须已签出或打开添加。严格核对同名输出，设置目标预览网格并保存；新包打开添加。调用后须对照源动画核验根轨迹、手脚 IK、曲线与通知。
