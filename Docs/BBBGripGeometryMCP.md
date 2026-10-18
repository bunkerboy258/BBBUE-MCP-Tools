# 握持网格几何采样与接触查询

## 只读编辑器入口

`editor.sample_skeletal_mesh_surface` 取得骨骼网格实际零级源表面在明确姿势下的线性蒙皮结果。它读取导入顶点与真实骨权重 不使用简单碰撞壳 不依赖 RHI 不修改或保存资产。

原生实现位于项目编辑器模块 `BBBGripGeometryEditorLibrary`。MCP 包装位于 `Scripts/BBBGripGeometryTools.py`。原生库缺失时明确报错 必须先编译并加载编辑器模块。

| 参数 | 含义 |
| --- | --- |
| `mesh_path` | 明确的 `/Game/` 骨骼网格包路径 |
| `animation_path` | 明确的非加法动画序列 空字符串使用网格参考姿势 |
| `time_seconds` | 动画采样秒数 参考姿势必须为零 |
| `selected_bones` | 选取骨骼根名称 自动包含后代 空数组选全部顶点 |
| `minimum_weight` | 顶点在选取骨骼集合上的合计权重阈值 大于零且不大于一 |
| `material_indices` | 有效材质槽索引 空数组选全部非禁用分段 |
| `output_name` | `任务目录名/报告名称` 不含扩展名 |
| `local_rotations` | 可选骨骼名称到局部四元数的字典 四元数顺序 `x y z w` 保留骨长和缩放 |

报告严格写入项目 `Saved/temp/<任务目录名>/<报告名称>.json`。拒绝目录穿越 链接和覆盖。工具只返回路径 数量 包围盒及几何限制 不向会话打印整个网格。任务完成后由调用者清理本任务目录。

默认动画采样为引擎 Raw 求值 启用角色网格重定向。独立加法动画缺少基底时没有实际表面姿势 因此拒绝直接采样。局部四元数覆盖仅用于明确骨骼 不重新定义关节平移或缩放。

## 文件结构

- `mesh` 与 `animation` 记录源对象和动画路径。
- `space` 固定为 `mesh_component_centimeters`。跨角色与武器查询前必须按完整挂接链变换到同一空间。
- `deformation` 固定为 `linear_blend_skinning_no_morph_cloth_or_deformer`。不包含 Morph Cloth 或额外网格变形器效果。
- `morphTargetCount` 与 `clothSectionCount` 明确提醒调用者存在未模拟的变形来源。
- `vertices` 每项包含原始顶点 `id` 蒙皮后的 `position` 源绑定空间 `bindPosition` 骨权重 `weights` 以及是否满足选点阈值的 `selected`。
- `weights` 每项为 `[骨架索引 归一化权重]`。权重来自原始十六位权重 除数为 65535。拒绝缺失骨骼索引或权重和不合法的源数据。
- `triangles` 每项包含源面片 `id` 三个原始顶点编号 `vertices` 源 `section` 和有效 `material`。
- `bones` 按骨架索引排列 每项包含 `name` `parent` `referenceLocal` `local` `component` 与 `inverseBindMatrix`。
- 变换十项数组顺序为 `tx ty tz qx qy qz qw sx sy sz`。
- `inverseBindMatrix` 是实际逆绑定矩阵的十六项行优先数组 遵循 UE 行向量乘法约定 可用于独立回算源蒙皮。

顶点编号可能不连续 不能用列表下标代替原始编号。为保持接触区域边界的真实三角面 邻接顶点会自动补入并标为 `selected=false`。接触点应从 `selected=true` 的顶点中按指腹或掌心区域进一步选择。

## 纯计算接触审计

`Scripts/BBBGripGeometry.py` 不依赖 Unreal 或第三方库 可直接由离线优化器导入。

- `closest_point_triangle(point a b c)` 精确计算点到三角面的最近点 支持退化三角面。
- `TriangleSurface(surface triangle_ids=None)` 建立 AABB 查询树。可指定人工确认的原始面片编号限制接触目标区域。
- `TriangleSurface.nearest(point)` 返回 `distanceCm` 最近点 面片编号 法向和 `normalGapCm`。
- `audit_contacts(points surface triangle_ids=None)` 返回逐点距离和间隙范围统计。

`normalGapCm` 仅是相对最近三角面朝向的局部法向间隙。开放网格 双面薄片 错误绕序和三角面边界都会使其符号无法代表闭合体内外。工具明确返回 `normalSignIsVolumeClassification=false` 不将负值直接标为体积穿透。

抓握拟合还必须限制正确的握把 护木和扳机区域。无限制的最近点只能定位附近表面 不能判断哪个部件应被手指抓住。几何距离通过也不等于关节自然度或动态交接通过。

## 验证

`Tests/test_grip_geometry.py` 覆盖面内投影 边缘与角点 退化面 稀疏顶点编号 接触区域限制 法向符号边界及 AABB 最近点与穷举结果一致性。编辑器实测必须另行核对导出顶点数 骨架顺序 与离线重蒙皮误差。
