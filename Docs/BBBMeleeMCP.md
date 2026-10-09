# 近战装备工具

`Scripts/BBBMeleeToolset.py` 使用官方注册系统 在项目 MCP 启动时自动加载。

- `inspect_melee_sources` 只读检查候选网格边界及双手姿势。
- `create_rigid_equipment_mesh` 调用引擎原生 `FStaticToSkeletalMeshConverter` 创建独立单根骨骼装备 保留第三方源模型 材质和几何。
- `create_melee_attack` 创建独立完整姿势序列及 UpperBody 蒙太奇 保留所有原始骨骼轨道 配置平滑屏蔽握持与瞄准 IK 的曲线 添加角色装备生命周期及伤害窗口通知。
- `inspect_upper_body_mask(blueprint_path)` 只读检查角色主图 UpperBody 直接连接的 BlendMask 全部骨骼权重或 BranchFilter 配置 不修改第三方骨架。
- `stage_upper_body_blend` 在独立项目将唯一上半身混合节点改为 spine_01 深度5与 ik_hand_root 深度1的分支过滤 根骨 骨盆与腿部保留基础姿势 严格编译后仅暂存自有蓝图 正式文件须独占签出且预检摘要一致 合并前必须再核对摘要。
- `create_melee_equipment` 创建近战动画实例子蓝图 参考姿势图 定义资产及演员蓝图 并登记到已签出的装备目录。
- `validate_melee_equipment` 只读核验原始骨骼轨道摘要 两条 IK 渐变曲线 两个通知及装备默认网格动画类 从父类到子类严格编译角色装备动画层及装备蓝图 并执行真实装备的通知窗口 镜像隔离与枪口查询测试 不保存资产。
- `register_melee_equipment` 将已验证的近战蓝图追加到已独占签出的装备目录 拒绝重复装备标识。
- `stage_character_aim_gate` 在独立项目宿主中为唯一 Aim IK 节点添加 `IsRifle && HasMuzzle` 条件 原有权重只在条件成立时通过 其它情况输出零 只将目标包暂存到独立项目 `Saved/temp` 正式文件须已独占签出且 SHA256 与预检一致 严格编译失败时拒绝暂存。

写入前必须停止 PIE 并连接 Perforce 现有目标必须独占签出 新目标必须可添加 工具不提交或回滚 Perforce。工具拒绝覆盖已有资产。通知只影响直接持有角色 经角色装备通信处理器提交抽象装备输入 具体扫掠及伤害由近战装备处理器维护。

原生依赖在接入项目 `Source/ABBB_EvacEditor/Public/BBBEquipmentAuthoringEditorLibrary.h` 和 `Private/BBBEquipmentAuthoringEditorLibrary.cpp`。原生转换入口只接受未占用的 `/Game/_Project` 目标 创建后须由工具核验保存并加入 Perforce。

## 独立进程制作

命令行使用官方 `UnrealEditor-Cmd.exe -run=pythonscript -script=.../Scripts/BBBMeleeToolset.py -NullRHI -unattended`。必须附加 `-ini:EditorPerProjectUserSettings:[/Script/ModelContextProtocolEngine.ModelContextProtocolSettings]:bAutoStartServer=False` 避免开启第二个 MCP 宿主。

环境变量 `BBB_MELEE_REQUEST` 指向本项目 `Saved/temp/本任务/` 下的 JSON 请求 包含 `mesh` `attack` `equipment` 三组公开创建工具参数。`operation` 为 `create` 时不会登记目录。原生转换及内存动画复制保留正式 `/Game/_Project` 包名 新资产由 `SaveStagedEquipmentAsset` 保存到本任务 `Content` 暂存目录 不写入正式内容目录 不自动添加源控。原始动画轨道保存前进行 SHA256 核对。

全部资产创建后工具严格检查两份蓝图 并调用 `RunMeleeChecks` 对真实 `Bat_01` 资产执行 `BBB.Equipment.Melee.WindowLifecycle` 同步自动化测试。只有无错误无警告才生成成功结果。结果验证通过后合并暂存资产到对应正式路径 比较文件摘要 再打开 Perforce 添加。`operation=register` 重新加载合入的资产 再次验收后登记装备目录。`operation=verify` 仅执行检查。运行中编辑器可能占用已有资产文件 最终登记与正式 DLL 编译需先协调释放编辑器。

资产被任何会话写入前均须核实本项目 Perforce 独占状态。本工具不执行源控提交或回滚 新增资产沿用项目 `binary+l` 类型。任务结束必须关闭自己的命令行进程 删除自己的暂存目录 保留其它会话文件。

已有角色图表的隔离编辑使用独立项目和独立 `-ModelContextProtocolPort` 端口 正式内容仅用于读取 所有保存通过 `SaveStagedAsset` 写入隔离任务目录 禁止直接调用正式内容的保存工具 禁用宿主自动保存 合并前再次核对正式文件摘要及独占状态 只复制通过验收的目标包。
