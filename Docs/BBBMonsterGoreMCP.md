# 僵尸统一伤口表现工具

内核使用完整原身体 蒙皮前椭球范围 投影裁剪与血层 以及预制组织。断肢同样是一条伤口定义 可额外引用预制物理残肢。运行时不切网格 不生成封盖 不创建每实例可写伤口纹理。

## 正式资源

配置固定在 `/Game/_Project/Mass/Monster/Zombie/Shared/Injury/<外观>/DA_Wounds`。

- 普通局部伤口最多两处 新伤口轮换替换局部槽位。
- 永久损毁最多五处 头与四肢各一处 普通命中不能挤走。
- 所有槽位采用同一渲染内核 玩法仍使用原有部位伤害结果。
- 组织和残肢在离线工具中定型 身体保持原拓扑。
- 内部组织采用身体表面邻域的四骨权重并共享身体姿态 不使用单骨刚性挂接 不随椭球变形。
- 局部创口的组织使用同一参考姿态椭球和投影裁剪 身体之外的血肉不会从衣领或袖口漏出 永久断口只保留对应截面范围 掉落件使用自身封口。
- 共享遮罩为 RGB 图集 红控制裁剪 绿控制血层 蓝控制湿润。
- 原生预览与调试靶使用正式表现组件 不写第二套伤口渲染器。
- 正式身体 LOD0 至 LOD2 保留预制组织 更远档只保留外皮血层和缺肢轮廓。躯干致死命中仍生成局部创口 不将躯干误判为已移除的肢体。

## 操作

`monster_gore.configure_monster_wound_materials(definition_path)` 只适配已有预制资源的共享材质 明确绑定掉落件材质并保存相关自有资源。它不生成身体或伤口网格 拒绝 PIE 和 Perforce。着色器回读需要有渲染能力的宿主 可使用静音 RenderOffscreen 不可使用 NullRHI。

`monster_gore.inspect_monster_gore_assets(definition_path)` 回读配置引用 有效性及固定容量 不运行世界 不保存。

`monster_gore.open_monster_gore_editor(definition_path)` 仅在用户需要人工调整时打开可见原生预览。选择预设后调整椭球 使用单次命中 应用 重置 播放和保存配置。该界面不含资源生成或重建按钮。

右侧仅显示当前选中的伤口。资源身份和配对模型只读 椭球通过视口移动 旋转和缩放 组织固定在离线适配的蒙皮位置 超出其覆盖范围需要修改离线资源 不自动扩张或生成内部组织。

`monster_gore.control_monster_gore_preview(definition_path, action, template_index, value, capture_name)` 使用无窗口的独立编辑预览世界 不打开资产编辑器 不修改地图 不启动 PIE 不播放声音。支持以下操作。

| 操作 | 作用 |
| --- | --- |
| apply | 应用选择的伤口 包括断肢 |
| fire / burst | 单次命中或短连射 |
| reset / set_reset | 清空本预览或设置本次重置间隔 |
| play / pause / scrub | 动画播放控制 |
| focus / wide / camera | 相机定位 camera 的 value 为绕开口角度 |
| piece | 查看本预览的可见掉落件 可在落地后近看接触情况 |
| time_scale | 预览时间倍率 |
| state | 回读真实预览时钟和物理位置 后台预览随引擎帧持续更新 不使用同帧循环伪造物理时间 |
| capture | 离屏采集真实 UE 图像 |

capture_name 使用 `任务名/唯一截图名`。输出为 `Saved/temp/<任务名>/GorePreview/<截图名>.png` 拒绝覆盖既有截图。实际查看图像和检查运动之后才能给出表现结论。

## 离线资源交付

`editor.export_skeletal_mesh_fbx(mesh_path, export_name, task_name)` 指定 task_name 后将参考 FBX 与骨骼清单导出到任务临时目录。回导后须核对实际骨名 父子关系及参考变换 不能只核对骨骼数量。新组织与蒙皮残肢使用原骨架 静态掉落件使用对应骨骼局部坐标并提供 UCX 凸碰撞。

`hit.inspect_zombie_gib_presentation` 仍用于实际世界残肢池只读检查。原生入口归属 `BBBMonsterGoreEditorLibrary`。

回读中的 `bodyResults` 给出当前世界表现 Actor 的七个实际材质伤口槽位和动态材质数量 用于确认正式 Mass 链路已应用当前结果 不记录命中历史。掉落件与身体共享对应投影材质 通过现有掉落标记保留完整残肢几何 同时保留切口血层与寿命淡出。

`editor.reimport_static_mesh(asset_path, source_file)` 对明确的已有自有静态网格执行原生 FBX 原位重导入。拒绝未保存目标和 PIE 不生成材质 纹理或动画 保存后返回实际包围盒与凸碰撞数量。默认导入入口拒绝覆盖已有资产 迭代预制残肢使用该入口。

旧构建入口和分段身体资源不再用于新配置 不提供转发别名。配置保存成功不等同于正式引用迁移或表现验收完成。
