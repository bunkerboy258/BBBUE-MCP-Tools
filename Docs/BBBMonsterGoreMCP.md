# 僵尸毁伤与断肢工具

身体二级破坏分为同级的毁伤系统与断肢系统。毁伤系统负责八区躯干创口。断肢系统负责头部与四肢的五个持久断点。两者共用原身体的投影材质 血效与残肢池。

## 配置与资源

正式入口是各版本的 DA_BBBZombie<外观>Presentation。十种外观与男女基础模板各自持有内联分区。固定靶独立入口是 /Game/_Project/Debug/ZombieHitReaction/DA_TargetPresentation。

- Destruction 保存正面左胸 / 右胸 / 左腹 / 右腹及背面左上背 / 右上背 / 左腰背 / 右腰背八处范围。区域允许交叠并覆盖侧腰。
- Destruction.Interior 是一份共用的蒙皮内部组织。运行时共用身体姿态。三档网格由制作流程分别导入 每档单材质槽。材质配置工具核对三档齐全 不自动减面或覆盖制作结果。
- Dismemberment.Parts 保存九个离线断点资源。当前结果分别为头 / 左臂 / 右臂 / 左腿 / 右腿选定一个断点。
- 身体保留原拓扑。材质按参考空间裁剪外皮并还原血层。内部组织由 Blender 制作并传递身体邻域的四骨权重。
- 组织由外皮开口自然露出 不再按顶点颜色拆成八套肉壁。颜色 / DirectX 法线 / ORM 通过共享图集与一个烘焙 UV 通道还原。
- T_DestructionRegions 将八区制作遮罩按四列两行打包。通道依次为开口 / 血液 / 凝血 / 边界距离。身体保留原 UV0 与 UV2 UV1 保存破损许可与衣料标记 UV3 保存认可源的圆周和高度制作坐标。制作结果符合骨骼网格的四通道导入限制。适配前遍历原材质及函数中的坐标节点与纹理默认坐标 拒绝覆盖仍被原表面使用的 UV1 或 UV3。材质直接读取制作坐标 不再用正弦扰动椭圆替代制作轮廓。
- T_DestructionCloth 保存同一布局的切线空间厘米位移与边界距离。顶点阶段只读取已开口区域 重叠处取最近边界的位移 原材质位移继续叠加。皮肤材质默认不启用衣料位移。所有僵尸共享只读制作图 不建立每实例可写纹理。
- UV1 与 UV3 是数据通道 制作器在 FBX 边界反向编码 Y 以抵消原生 FBX 导入的 V 翻转。材质接收到的衣料标记和制作高度都是逻辑数值 不对普通表面 UV0 与 UV2 进行此处理。FBX 的 UV 数据块必须按 0 1 2 3 顺序排列。
- 身体与内部组织在 FBX 导出前统一烘入制作坐标的正九十度 Z 基变换 抵消导入根姿势偏转。适配工具在写入材质前核对身体根原点和朝向与原骨架一致 身体自身根缩放为一 内部组织根姿势完整跟随身体。核验以网格实际绑定姿势为准 骨架资产身份及骨架资产上的根缩放不能代替该检查。
- 每个玩家的伤害贡献附带八个字节的毁伤累计量。重复与迟到贡献逐区取最大值。实体八区强度由各玩家贡献汇总。房主分发和迟加入沿用现有完整贡献快照。

## 运行时参数

| 自定义图元数据 | 内容 |
| --- | --- |
| 1 至 5 | 五个当前断点编号 |
| 8 | 生命周期淡出 |
| 9 | 独立掉落件标记 |
| 10 至 17 | 八区归一化毁伤强度 |

共享材质实例的 InjuryStyle 前三项保存粗糙度 / 湿润度 / 开口阈值。正式身体的破损许可由制作标记控制 颈肩连续范围直接来自认可源 不再按统一胸椎高度截断创口。内部组织的烘焙颜色 法线与粗糙度受现有 TissueTint Roughness Wetness 配置调节 不增加独立运行时配置。

第一次受损时才切换身体的破坏材质。开口后才创建一份共享躯干组织组件。五个断点组织加躯干组织最多六份跟随组件。跟随组件关闭独立动画更新与碰撞。显示档位跟随身体。组件复用时清除本代参数与组织可见性。

## 编辑操作

monster_gore.configure_monster_wound_materials(definition_path) 适配已有资源的身体 / 断面 / 掉落件与毁伤组织材质。须先导入三档组织网格及破口和衣料图集 工具核对齐全后保存相关自有包。匹配的共享表面图复用现有节点。断面与掉落件的材质绑定发生变化时才重建对应网格资源。着色器核验使用有渲染能力的编辑宿主。编译错误返回具体材质与编译信息。

整体重建表面图时同时解除所有旧材质输出引用。新投影只捕获当前烘焙表面的颜色 / 粗糙度与常量遮罩。BakedMaterialGraph 原生回归核对旧遮罩与顶点输出链的解除并验证匹配图集节点直接复用。

T_AnatomyColor / T_AnatomyNormal / T_AnatomyORM 使用当前制作产物的实际分辨率。导入后通过 editor.configure_asset_properties 将 virtual_texture_streaming 设为 false。颜色使用 TC_BC7 与 sRGB。法线使用 TC_NORMALMAP 并保持 sRGB=false 与 flip_green_channel=false。ORM 与 Regions 使用 TC_MASKS 与 sRGB=false。Cloth 使用 TC_VECTOR_DISPLACEMENTMAP 与 sRGB=false 并保留透明通道。法线与切线位移采用 DirectX 切线约定。区域图集在原生材质中明确转换 PNG 的垂直坐标。

monster_gore.inspect_monster_gore_assets 回读资源有效性和容量。当前容量为八区毁伤与五处断肢。每实例可写纹理字节数为零。inspect_monster_presentation 核对整份表现配置及内联分区所有权。save_monster_presentation 验证后保存明确主配置。

import_monster_hit_profile 将受击参数模板复制到主配置的躯干 / 头 / 臂 / 腿四份内联分区。物理来源绑定主配置的物理资产。

资源写入完成并保存回读后再进行读取这些包的测试。Windows 下其它宿主的包读取句柄可能阻止编辑器替换文件。共享材质写入与依赖这些材质的测试分阶段执行。本任务按用户要求直接使用主编辑器。

## 制作与验证

Blender 源位于项目 ArtSource/ZombieDestruction。制作输入为人工认可的 Polish/Connor/WoundSet/WoundSet.blend 及摘要。ExportTorso.py 的 --prepare 按正式身体同档伤口邻域密度分配三档网格与烘焙 UV。--bake 从原始组织对象烘焙本色 / 法线 / 粗糙度与实际 AO。--style 只重算本色倍乘 不重复烘焙法线和 AO。ExportSurface.py 打包八区轮廓与衣料场。ReviewProduction.py 在同机位对照实际生产网格与认可源。尚未通过生产外观复核的产物拒绝导出到 UE。

当前制作源三档分别为 2395 / 470 / 276 三角面 原生导入清除退化面后实际渲染数据为 2395 / 469 / 256 三角面。女性原骨架包含额外 joint 骨骼 导出保留各外观完整骨名与父子关系 每顶点最多四根归一权重。材质不读取旧肉壁归属或深层腔壁颜色标记。

FBX 使用厘米单位 Armature 对象与 NULL 骨架节点并关闭额外叶骨。回导使用 import_uniform_scale=1.0。骨名数量 / 父子关系 / 网格实际参考变换 / 厘米包围盒与四通道布局均须核验。骨架资产的参考姿势不能冒充网格实际绑定姿势。

BBB.Monster.Gore 保留贡献合并 / 正背面选区 / 当前结果恢复 / 真实资产契约 / 断肢姿态 / 点命中与复用的正式验收入口。自动化执行按本轮授权进行 不把资产保存 编译或离屏制作检查冒充玩法验收。

preview.spawn_mass_inspection_population 使用正式配置创建本轮实体。destruction_regions=0..8 和 sever_left_arm 建立明确外观对照。测试辅助库经正式伤害输入投递当前贡献。实际子弹命中另行验证。

preview.inspect_mass_inspection_population 回读本轮群体及每只实体的八区强度 / 断点 / 实际组织组件。animation_graph.inspect_mass_variation_network 同时回读各 PIE 世界的个体状态与破坏结果。可比较主客机和迟加入的同一网络身份。

editor.configure_pie_session 在 PIE 结束后临时设置下一次主进程 PIE 的网络模式。listen 与 players=2 创建同一编辑器内的主客机。editor.request_pie_late_join 增加真实迟加入客机。测试结束后用 standalone 与 players=1 恢复普通单窗口模式。工具核对实际设置且仅修改编辑器内存。

preview.start_mass_population_benchmark 支持相同毁伤区域与断臂参数。每组保存实际破坏快照并测量真实 Mass 群体的动画预算关闭 / 开启。完好 / 一区 / 四区 / 八区与断臂并存采用同机位 同分辨率 同画质和独立帧号采样。GPU 指标来自真实渲染宿主。截图采样与稳态测量分开。

真实场景继续检查衣物破口 肉壁交叠 动画随动 喷血 残肢和回收。资源有效性与编译成功各有独立证据。最终画面以 UE 实际渲染截图为准。
