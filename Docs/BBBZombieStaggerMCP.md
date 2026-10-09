# 僵尸踉跄构图

`BBBAnimationGraphToolset.configure_fact_stagger_state` 在项目僵尸动画蓝图的 `FactDrivenActions` 状态机加入一个 `Stagger` 状态 不改变六种 AI 行为 不修改 `FactDrivenCrawl`。

参数:

- `asset_path`: `/Game/_Project/` 下已独占签出的动画蓝图
- `sequence_paths`: 头部 左向 右向三个不同的同骨架动画序列
- `blend_duration`: 大于零且不超过 0.3 秒 默认 0.12 秒

调用前必须完成原生编辑器模块编译并重新启动唯一 MCP 宿主。PIE 期间拒绝构图。已含踉跄或非标准站立图拒绝重复构图。不创建兼容分支 不保存编译失败的资产。

动画只读 `StaggeringFact` `StaggerProgressFact` `StaggerVariantFact`。各序列显式时间由 Mass 进度映射 不触发动画通知。死亡无出口 站立踉跄不抢占爬行。轻击不打断攻击 重击由 Mass 的踉跄事实取消未结算攻击并进入踉跄 不回滚已结算伤害。

推荐当前 Ramster 序列顺序: `Zombie_HitReact_Head` `Zombie_HitReact_LeftArm` `Zombie_HitReact_RightArm`。腿部完整受击含明显跪地 不作为通用站立踉跄。

验证边界: `Tests/test_zombie_stagger_graph.py`。实际资产仍需编译 事实测试与渲染验收。

`configure_fact_combat_transition_blends` 要求已含完整七状态站立图与爬行图。它补齐重击的 `Attack -> Stagger` 转换 不产生旧状态或兼容分支。全部转换使用惯性混合 死亡优先。

| 参数 | 默认秒数 | 用途 |
|---|---:|---|
| movement_duration | 0.22 | 普通移动转换 |
| attack_enter_duration | 0.08 | 攻击入场 |
| attack_exit_duration | 0.16 | 攻击退出 |
| hit_enter_duration | 0.07 | 重击踉跄入场 |
| hit_exit_duration | 0.18 | 踉跄恢复 |
| crawl_duration | 0.28 | 爬行姿态入场 |
| death_duration | 0.04 | 死亡入场 |

每项必须有限且大于零 不超过半秒。工具只修改已独占签出的目标蓝图 禁止 PIE 编译存在警告或错误时不保存。边界测试位于 `Tests/test_combat_transition_blends.py`。

`capture_monster_stagger_samples(actor_blueprint_paths, hit_region, sample_progress, file_prefix)` 使用渲染 PIE 在高空生成无 Mass 实体的临时表现载体。每批最多十种外观和三个进度。小于一采样正式 `Stagger` 状态 一采样退出后的移动状态。输出实际运行图和骨骼位置 并在异常和成功时均销毁临时演员。不保存资产 不修改现有场景 不作为真实武器伤害链的验收替代。
