# 骨骼网格动画交付导出

通用工具集的 `export_skeletal_mesh_fbx(mesh_path, export_name)` 使用 UE 官方 `SkeletalMeshExporterFBX` 导出带骨骼和蒙皮的 LOD0 二进制 FBX 同目录生成 `Skeleton.json` 供离线动画工具和 AI 读取

`mesh_path` 为骨骼网格对象或包路径 `export_name` 为 Saved/Exports 下尚不存在的目录名称 仅接受字母数字下划线与连字符 禁止覆盖既有交付 不修改源资产 不保存包 不执行 Perforce 操作 PIE 或目标网格与骨骼含未保存改动时拒绝执行 失败会记录带 SkeletalExport 前缀的错误 部分失败可能留下输出目录 调用者应核对后清理本次输出再重试

固定导出选项为 FBX 2013 二进制 X 前向 仅最高细节网格 不导出碰撞 允许已有形态键 不烘焙材质贴图 材质槽可以保留 纹理与 UE 材质图不属于本交付 动画师使用网格进行比例和蒙皮检查

UE5.8 官方骨骼导出器即使禁用材质烘焙仍创建临时组件并读取 CPU 蒙皮 无渲染宿主会触发 MeshObject 断言 工具在调用前拒绝 NullRHI 使用唯一隐藏宿主并在启动脚本传入 EnableRendering 完成后关闭该宿主

JSON 保留 UE 查询骨名 name 父骨名称以及参考姿势的 local 与 component 变换 同时记录实际导出骨名 fbxName UE 名称按 FName 不区分大小写匹配 Blender 动画轨道应使用 fbxName 的精确拼写 位置为 UE 厘米 旋转为 XYZW 四元数 component 表示网格参考姿势空间 并非场景 Actor 世界坐标 JSON 坐标与导入 Blender 后的坐标不可直接混用 FBX 导入器负责坐标转换

返回目录与两文件绝对路径 骨骼数和 LOD0 顶点数 工具使用本仓库 `Scripts/VerifySkeletalMeshFbx.py` 解析二进制结构 核验骨名 父子层级 网格 蒙皮簇与权重关联 核验结果写入 fbxVerification 骨骼 JSON 通过后才写出 该结构核验不等同于在 Blender 中实际打开文件
