# 僵尸毁伤与断肢工具

身体二级破坏分为同级的毁伤系统与断肢系统。毁伤系统负责八区躯干创口。断肢系统负责头部与四肢的五个持久断点。两者共用原身体的投影材质 血效与残肢池。

## 配置与资源

正式入口是各版本的 DA_BBBZombie<外观>Presentation。十种外观与男女基础模板各自持有内联分区。固定靶独立入口是 /Game/_Project/Debug/ZombieHitReaction/DA_TargetPresentation。

- Destruction 保存正面左胸 / 右胸 / 左腹 / 右腹及背面左上背 / 右上背 / 左腰背 / 右腰背八处范围。区域允许交叠并覆盖侧腰。
- Destruction.Interior 是一份完整蒙皮内部组织和八处肉壁。运行时共用身体姿态。零级单材质槽。原生工具生成三档精细度。
- Dismemberment.Parts 保存九个离线断点资源。当前结果分别为头 / 左臂 / 右臂 / 左腿 / 右腿选定一个断点。
- 身体保留原拓扑。材质按参考空间裁剪外皮并还原血层。内部组织由 Blender 制作并传递身体邻域的四骨权重。
- 组织颜色的红通道记录肉壁归属。绿色为深层腔壁标记。蓝色保持完整明度。颜色 / 法线 / 粗糙度通过一套共享图集与一个烘焙 UV 通道还原。Blender 使用浮点颜色导出以保留精确编号。
- 每个玩家的伤害贡献附带八个字节的毁伤累计量。重复与迟到贡献逐区取最大值。实体八区强度由各玩家贡献汇总。房主分发和迟加入沿用现有完整贡献快照。

## 运行时参数

| 自定义图元数据 | 内容 |
| --- | --- |
| 1 至 5 | 五个当前断点编号 |
| 8 | 生命周期淡出 |
| 9 | 独立掉落件标记 |
| 10 至 17 | 八区归一化毁伤强度 |

共享材质实例的 InjuryStyle 依次保存粗糙度 / 湿润度 / 开口阈值与颈肩保护高度。高度从对应身体原骨架 spine_03 的完整父链推导。身体的躯干裁剪在最高胸椎下方生效。上胸 / 颈口和肩部保留连续连接。

第一次受损时才切换身体的破坏材质。开口后才创建一份共享躯干组织组件。五个断点组织加躯干组织最多六份跟随组件。跟随组件关闭独立动画更新与碰撞。显示档位跟随身体。组件复用时清除本代参数与组织可见性。

## 编辑操作

monster_gore.configure_monster_wound_materials(definition_path) 适配已有资源的身体 / 断面 / 掉落件与毁伤组织材质。它生成组织 LOD 并保存相关自有包。匹配的共享表面图复用现有节点。断面与掉落件的材质绑定发生变化时才重建对应网格资源。着色器核验使用有渲染能力的编辑宿主。编译错误返回具体材质与编译信息。

整体重建表面图时同时解除所有旧材质输出引用。新投影只捕获当前烘焙表面的颜色 / 粗糙度与常量遮罩。BakedMaterialGraph 原生回归核对旧遮罩与顶点输出链的解除并验证匹配图集节点直接复用。

本轮 T_DestructionSurface / T_DestructionNormal / T_DestructionORM 为共享 4096 图集。导入后通过 editor.configure_asset_properties 将 virtual_texture_streaming 设为 false。颜色使用 TC_BC7 与 sRGB。法线使用 TC_NORMALMAP 并保持 sRGB=false 与 flip_green_channel=false。ORM 使用 TC_MASKS 与 sRGB=false。法线源采用 DirectX 切线约定。该组设置与原生生成器的普通纹理采样一致。

monster_gore.inspect_monster_gore_assets 回读资源有效性和容量。当前容量为八区毁伤与五处断肢。每实例可写纹理字节数为零。inspect_monster_presentation 核对整份表现配置及内联分区所有权。save_monster_presentation 验证后保存明确主配置。

import_monster_hit_profile 将受击参数模板复制到主配置的躯干 / 头 / 臂 / 腿四份内联分区。物理来源绑定主配置的物理资产。

资源写入完成并保存回读后再进行读取这些包的测试。Windows 下其它宿主的包读取句柄可能阻止编辑器替换文件。共享材质写入与依赖这些材质的测试分阶段执行。本任务按用户要求直接使用主编辑器。

## 制作与验证

Blender 源位于项目 ArtSource/ZombieDestruction。Polish/AuthorReview.py 制作人工审看的网格。用户通过后的 Review.blend 与通过摘要为运行制作输入。ExportTorso.py 的 --prepare 生成分件预算与烘焙 UV。--bake 保留原始 UV 烘焙颜色与粗糙度并按源材质分组投射高模法线。--variant 接外观名称并按对应身体曲面和原骨架导出。运行文件为一材质槽与一烘焙 UV。ReviewTorso.py 渲染真实减面与烘焙后的导出源。

2026-10-26 本轮最高档组织为 36536 三角面。女性原骨架包含额外 joint 骨骼。导出按各外观自己的完整骨名集检查。每顶点最多四根归一权重。肉壁使用与外皮同源的五项轮廓波形。正背面裁剪读取参考姿势法线。深层腔壁通过顶点绿色标记还原面向。

绿色腔壁标记导出为精确零或一。该步骤使 FBX 颜色量化后的标记保持 0 或 255。红色归属继续按八分之一间隔编码。

FBX 保留完整原骨架。导出采用 Armature 对象与 NULL 骨架节点并关闭额外叶骨。回导使用 import_uniform_scale=0.01。骨名数量 / 父子关系 / 参考变换 / 厘米包围盒与颜色编号均须核验。

BBB.Monster.Gore 自动化覆盖贡献合并 / 正背面选区 / 当前结果恢复 / 真实资产契约 / 九十处断肢姿态 / 实际点命中与复用。资源契约同时检查四万三角面预算 / 单烘焙 UV / 深层腔壁标记及八区归属。批次完成表示测试执行结束。测试是否成功以自动化日志中的结果为准。

preview.spawn_mass_inspection_population 使用正式配置创建本轮实体。destruction_regions=0..8 和 sever_left_arm 建立明确外观对照。测试辅助库经正式伤害输入投递当前贡献。实际子弹命中另行验证。

preview.inspect_mass_inspection_population 回读本轮群体及每只实体的八区强度 / 断点 / 实际组织组件。animation_graph.inspect_mass_variation_network 同时回读各 PIE 世界的个体状态与破坏结果。可比较主客机和迟加入的同一网络身份。

editor.configure_pie_session 在 PIE 结束后临时设置下一次主进程 PIE 的网络模式。listen 与 players=2 创建同一编辑器内的主客机。editor.request_pie_late_join 增加真实迟加入客机。测试结束后用 standalone 与 players=1 恢复普通单窗口模式。工具核对实际设置且仅修改编辑器内存。

preview.start_mass_population_benchmark 支持相同毁伤区域与断臂参数。每组保存实际破坏快照并测量真实 Mass 群体的动画预算关闭 / 开启。完好 / 一区 / 四区 / 八区与断臂并存采用同机位 同分辨率 同画质和独立帧号采样。GPU 指标来自真实渲染宿主。截图采样与稳态测量分开。

真实场景继续检查衣物破口 肉壁交叠 动画随动 喷血 残肢和回收。资源有效性与编译成功各有独立证据。最终画面以 UE 实际渲染截图为准。
