# 离线握姿拟合

`Scripts/BBBGripPoseFitting.py` 使用 `sample_skeletal_mesh_surface` 的真实网格报告进行离线线性蒙皮与有界局部旋转搜索。依赖 NumPy 不依赖 SciPy。程序不连接编辑器 不修改资产。

## 明确制作输入

顶层配置包含 `attachment` 和 `contacts`。`attachment` 是完整挂接链中的武器到 `hand_r` 局部变换 十项顺序为 `tx ty tz qx qy qz qw sx sy sz`。工具将它与角色采样的 `hand_r.component` 合成。调用者必须先确认插槽父骨及额外局部变换。

每个接触组具有以下字段:

| 字段 | 用途 |
| --- | --- |
| `name` | 接触组名称 |
| `bones` | 允许旋转的明确骨骼 同一骨骼不能属于多个组 |
| `vertex_ids` | 人工确认的掌面或指腹原始顶点编号 正式拟合默认要求 |
| `selection_reviewed` | 接触点是否已确认 必须明确为true才会标为已审核 缺省false |
| `exclude_vertex_ids` | 明确排除的指背 指甲或其它区域顶点 |
| `weapon_triangle_ids` | 明确目标部件的原始面片编号 |
| `weapon_bounds` | 可选武器组件空间包围盒 以面片质心筛选 可与面片编号同时使用 |
| `exclude_weapon_triangle_ids` | 需要剔除的目标面片 |
| `axes` | 允许旋转的局部轴 `0 1 2` 对应 `X Y Z` |
| `maximum_delta_degrees` | 本组每个局部轴的最大增量 缺省取顶层同名值 默认25度 |
| `joint_limits_degrees` | 每骨三个 `[最小增量 最大增量]` 局部轴范围 必须包含零 |
| `target_gap_cm` | 目标外侧法向间隙 默认0.06厘米 |
| `surface_normal_sign` | 明确的外法向符号 必须为1或-1 用于修正面片绕序 |
| `signed_normal_target` | 正式默认true 要求明确法向符号 false只作无方向探索 |
| `clearance_vertex_ids` | 需要保持在枪体外侧的完整指面顶点 可独立于少量接触点 |
| `clearance_weapon_triangle_ids` | 用于清除穿透的完整闭合组件面片编号 |
| `clearance_cm` | 最低外侧间隙 默认0.03厘米 可在顶层设统一值 |
| `clearance_weight` | 清除欠距惩罚权重 允许10至30 默认20 可在顶层设统一值 |

必须指定 `weapon_triangle_ids` 或 `weapon_bounds`。不能默认把所有手指吸向整把枪最近的任意表面。编号不匹配 空接触组 空目标区域及错误骨骼均直接报错。

探索阶段可以显式设置 `selection_mode=radial_candidate` 代替 `vertex_ids`。此模式根据骨权重与目标方向选择候选顶点 可能选到指侧或指背 输出永久标记 `requiresContactSelectionReview=true`。它不能直接作为正式接触点审核结论。算法生成后以显式编号传入的候选点也不会自动变成人工已确认 输入必须另外明确 `selection_reviewed=true`。

## 算法与边界

拟合前用实际 `inverseBindMatrix` 和局部姿势重算导出表面。最大蒙皮误差必须小于等于0.002厘米。没有显式逆绑定矩阵时由 `referenceLocal` 重建 不能从当前动作姿势反推绑定矩阵。

使用逐轴有界坐标下降。局部旋转覆盖保留关节平移和缩放。顶层 `steps_degrees` 控制搜索精度 默认 `8 3 1`。`regularization` 抑制过大姿势变化 默认0.00008。每轴限制是制作约束 不等同于人体解剖约束。工具明确返回 `jointConstraintsAreAnatomicalProof=false`。

正式目标使用 `外法向符号 * 原始法向间隙 - 目标间隙` 的平方 加上到最近三角面的切向距离平方。因此同样贴近但位于表面背侧的点不会被当成等价极小值。没有明确 `surface_normal_sign` 时默认拒绝执行。符号必须根据对应接触区域的实际绕序确认 不能假设UE导出的三角面叉乘方向天然朝外。区域绕序不一致或本身是薄片时 该有向目标仍依赖调用者确认的局部朝向假设。

结果给出 `meanOutwardNormalGapCm` `minimumOutwardNormalGapCm` 与 `wrongSideContactPointCount`。它们验证相对指定局部表面的方向 不能单独证明全枪没有穿透。探索配置可以显式 `signed_normal_target=false` 使用无符号距离 结果明确保留该标志且没有外侧方向验收值。

## 完整指面清除约束

接触点只用于把指定指腹贴到对应部位。只优化几个接触点仍可能把指侧和指背旋入枪体。正式需要清除时 同时提供 `clearance_vertex_ids` 和 `clearance_weapon_triangle_ids`。工具先验证目标包含完整闭合组件 且组件面片绕序一致。缺面 开口 非流形和混乱绕序直接报错。

每个清除点以 `surface_normal_sign * 原始法向间隙` 为外侧距离。低于 `clearance_cm` 的欠距参与惩罚。代价为 `clearance_weight * (均方欠距 + 最大点平方欠距)` 使少数深穿不能被大量正常顶点稀释。它是软约束 最终仍须查看回读和独立闭合组件结果 不能仅以优化结束作为通过依据。

每组 `clearanceAudit.before/after` 给出最小外侧间隙 穿侧点数 低于规定间隙的点数 最坏欠距和相关原始顶点编号。最终值在所有接触组完成后统一重新蒙皮计算。

迭代仅蒙皮本接触组与清除组的顶点并集。`SurfacePose` 缓存指定顶点对应的真实蒙皮影响项 `TriangleQuery` 缓存固定区域的边向量和单位法向。每次搜索不重新蒙皮整个手部 也不查询整把枪的面片。全部手部与整枪检查只在最终独立回读执行。

若深穿顶点主要受 `hand_l` 或 `hand_r` 影响 单独旋转手指无法清除。应先完成挂接与腕目标几何校准 并用校准后的真实蒙皮作为手指拟合基线。腕位置与IK目标数值吻合只说明两者一致 不说明实际掌面已经在枪体外侧。

全部接触组完成后重新蒙皮最终姿势 并重新计算每组最终间隙。结果不是优化过程中的过期采样。`jointDeltaDegrees` 记录各骨局部轴增量 `jointRotationDeltaDegrees` 记录各骨相对基线的真实最短四元数角度 `localRotations` 是可供后续正式制作工具使用的绝对局部四元数。每轴30度不等于总旋转30度 应结合真实角度审核关节扭转。

独立全表面回读使用所有 `selected=true` 的角色顶点到全部武器三角面 不限于拟合所选顶点或目标区域。分别报告基线和最终姿势的最近间隙 近表面数量 局部法向负号数量及最近顶点编号。顶层 `near_surface_threshold_cm` 默认0.25厘米。

局部法向负号无法代表封闭实体内部。网格薄片 面片绕序以及开放区域会影响符号。报告明确提供 `volumePenetrationEvaluated=false` 和 `normalSignIsVolumeClassification=false`。逐顶点距离也可能漏掉面片之间的交叉。因此该审计用于定位问题 不能宣称已经证明无穿模。

## 独立闭合组件包含检查

`Scripts/BBBGripSolidAudit.py` 先按0.00001厘米位置量化焊接三角面顶点 再依据共享边建立连通组件。每条边恰好由两个面片共享的组件才执行包含查询。边界边和非流形边均记录并将对应组件标记为 `inconclusive_open_or_non_manifold`。

闭合组件使用三个不同方向的Moller-Trumbore射线奇偶查询。交点落在边界或不同方向无法形成一致结论时输出边界或不确定状态 不强行决定内外。算法与面片法向朝向无关 所以可对局部有向距离提供独立核对。

`independentClosedComponentAudit.before/after` 记录每个闭合组件的包含数量与原始顶点编号 同时输出开放组件数量 射线不确定数量和整表面覆盖状态。存在开放或非流形组件时 整枪覆盖明确为 `inconclusive_open_non_manifold_or_degenerate_components`。

对已确定在闭合组件内的顶点 另以实际三角面最近距离计算内部深度。每个组件和总报告给出 `insideDepthMaximumCm` 与 `insideDepthP95Cm` 总报告的 `deepestPoints` 定位最深原始顶点。重叠组件内同一顶点取已检查组件的最大深度。该深度属于明确组件的包含结果 不以局部法向符号推导。

该检查没有证明组件不存在自交 也没有定义多个闭合壳之间的布尔运算或空腔含义。落在某闭合组件内的点是需要定位的包含结果 不能自动转化为整个枪械实体材质的穿透结论。报告始终给出 `wholeWeaponSolidPenetrationProven=false` 和 `selfIntersectionTested=false`。不能用一个闭合部件检查通过去代替对开放护木等区域的审核。

## 验证

`Tests/test_grip_pose_fitting.py` 检查:

- 参考姿势逆绑定与当前动作姿势分离。
- 明确指腹点及排除区域生效。
- 单轴和小数关节界限保持。
- 自动候选不能成为静默默认。
- 无关顶点参与独立最终检查。
- 错误权重 父子层级 基线误差和过期编号明确失败。
- 分块向量最近点与独立三角面实现结果一致。
- 重复关节组无法覆盖之前结果。
- 正反两侧等距时有向目标不会选择背侧极小值。
- 正负明确法向符号会得到相应一侧的拟合结果。
- 缺少正式法向配置会报错。
- 焊接闭合立方体的内部 外部和表面点分类。
- 开放与非流形组件保持不确定。
- 闭合组件包含结果不依赖三角面绕序。
- 指定行蒙皮与完整蒙皮一致 且保留行顺序及重复行。
- 指定行缓存与固定三角区域缓存重复使用。
- 完整指面清除能保护未被接触点选中的指侧顶点。
- 清除区域缺失或不是完整闭合组件时明确失败。
- 闭合立方体内部最大深度和95分位与解析距离一致。

实际 `ArmsBaseline` 在2026-10-18的离线蒙皮最大误差为0.000042241厘米。该样本有68根骨骼 2770个导出顶点 4717个面片 左右手各十五根指骨 Morph和Cloth数量均为零。此结果只验证蒙皮计算一致性 不代表最终握姿已验收。
