# FK 重定向器配置

`retarget.configure_fk_retargeter(asset_path, align_source_pose=true)` 配置已有重定向器，不导出动画，不修改源或目标 Rig。

要求源和目标具有完整同名链，以及目标七个标准辅助 IK 骨。工具严格使用同名映射；手臂、腿与手指使用 One to One 旋转，脊柱使用 Interpolated，链平移保持 None。可按链对齐源姿势。

源具有独立 root 时复制源根骨；源仅有骨盆根时从目标骨盆生成地面根骨，避免把骨盆高度复制到目标 root。移除默认目标 IK 求解器，并在最后从目标手脚生成七个辅助骨变换。曲线复制操作保持不变。

调用后使用 `retarget.inspect_retargeter` 回读实际设置，再由用户审核姿势。设置完成不代表视觉验收通过。

`editor.rebind_asset_import_sources` 支持实际存在的外部永久源文件，包含 Windows 跨盘路径；只更改导入来源，不重新导入。无需将源 FBX 放进 Content 引发自动导入。
