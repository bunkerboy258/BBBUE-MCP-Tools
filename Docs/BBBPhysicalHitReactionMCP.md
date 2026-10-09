# 骨骼物理受击工具

`BBBHitReactionToolset` 通过官方工具注册表加载 依赖项目原生 `BBBHitReactionEditorLibrary` 和 ProcHitReact

- `configure_hit_reaction_physics_asset` 为独占签出的自有物理资产配置 `BBBHitReact` 恢复驱动 关节限制和无重力刚体 调用后显式保存
- `create_hit_reaction_profile` 创建不存在路径的躯干 头部 手臂或腿部配置 并保存 调用方将新文件加入 Perforce
- `remove_fact_hit_bone_layer` 移除已知六骨骼方向偏转链 将基础动画姿势直接接回惯性混合 严格编译成功后保存
- `inspect_skeletal_physics_state` 只读检查已加载的骨骼组件 记录命中编号 活动混合 刚体权重和速度
- `spawn_inspection_projectile` 仅在当前 PIE 使用正式子弹配置提交出生输入 经过正式移动 碰撞和命中处理器 零伤害检查表现 正伤害检查本地玩家累计伤害 不直接写入受击事实
- `start_skeletal_hit_reaction_capture` 在临时表现对象上跨真实游戏帧测试单发 连射 移动 死亡和隐藏 输出骨骼姿态 刚体状态与引擎帧耗时 可选真实渲染帧 全部临时演员在结束后销毁
- `inspect_skeletal_hit_reaction_capture` 读取采样状态 峰值骨骼角度和位移 完整逐帧数据保存于 `Saved/temp/` 调用方完成验收后清理

资产修改前必须独占签出 工具禁止修改第三方物理资产 不直接写入 Mass 玩法状态

`inspect_pie_audio_device()` 只读检查当前 PIE 的设备编号 活跃设备 静音 应用总音量和非实时混音配置 不输出进程命令行 不修改静音或项目设置 静音录音必须结合本诊断定位 不能仅以音频组件播放计数证明混音输出

## 尸体约束与质量

### 封闭断肢资源

- `create_zombie_sealed_part_meshes(source_mesh_path root_bone output_folder rebuild_existing=False)` 只读源网格 根据断开骨骼的权重提取部件 验证切口闭环 生成封闭掉落部件和身体断口封盖 默认拒绝已有输出 显式重建要求同名部件与封口完整存在且已独占签出 原地重建不备份旧版本 不自动保存
- `configure_monster_severing_parts(definition_path parts_json)` 要求正式配置独占签出 五个部位完整对应头部 左右上臂和左右大腿 每项包含 `region bone part cap` 不自动保存

- 运行时断肢仅还原 Mass 损毁位图 掉落部件全局最多二十四个 八秒回收 不新增逐实例逻辑更新 池化复用时恢复骨骼并清除自有部件 身体断口和衣物接缝必须用实际画面验收

- `inspect_physics_asset_constraints(asset_path)` 回读刚体质量 阻尼 约束两端 摆动与扭转限制和软约束开关 不修改资产
- `configure_corpse_physics_asset(asset_path total_mass_kg=75.0)` 拒绝运行中的 PIE 和非自有资产 要求独占签出 将总质量按骨骼分布 建立 `BBBCorpse` 硬关节配置 不修改活体受击驱动 不自动保存
- 运行时仅在尸体阶段启用 `BBBCorpse` 回收表现对象时恢复默认配置 不能以质量或约束报告代替落地与姿态的真实渲染验收

采样支持 `shots=0` 的无受击基线和 `actor_count=1..64` 的全骨骼表现压力检查 单演员无中断测试创建动画对照 仅初始姿态误差不超过 0.25 厘米时 `matchedAnimationControl` 为真且骨骼峰值取同期差异 否则峰值包含基础动画变化 群体结果属于表现层压力检查 不能当作完整 Mass 群体容量结论 渲染帧记录 `imageSeconds` 可按实际时间制作预览

插件源固定于 `d4110b10b8ae8cf19ae8d6aca4702f28c2da2e63` 本项目保留 MIT 许可 修正异步加载捕获移动源路径及 UE 5.8 切换模拟覆盖混合权重的问题

单演员对照共用表现随机种子 并临时关闭世界动画预算以同步采样 结束后恢复预算 群体压力采样保留正式预算设置 `run_monster_hit_reaction_regressions` 只排队编辑器自动化测试 通过与否必须读取宿主日志确认

恢复时先清除物理驱动再关闭碰撞 避免操作已销毁的刚体 本项目源只保留 UE 5.8 签名 已移除旧引擎版本分支 恢复驱动和受击组件均在空闲时关闭 Tick

当前身体回弹允许骨骼 LOD 0 至 2 四个受击配置与表现组件保持相同上限 LOD 3 及以后仍停止回弹 并通过 Verbose 日志记录拒绝条件与成功命中的实际 LOD 直线力度和旋转力度
