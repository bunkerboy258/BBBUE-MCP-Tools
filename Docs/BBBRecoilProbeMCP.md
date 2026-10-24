# 后坐力屏幕探针

`animation.sample_recoil_runtime` 只在 PIE 的 `GameViewport.OnDrawn` 阶段观察本地玩家 已完成该帧的姿势与相机更新 不改变玩法 不扫描特效或弹壳 不保存资产。

- `action=start seconds=10` 开始采样 手持装备及可渲染视口必须存在
- `action=status` 返回统计 `limit=0` 不返回逐帧数组
- `action=status offset=0 limit=1200` 分页读取原始数据
- `action=stop` 提前结束并解除委托
- PIE 结束时自动解除委托并将未完成采样标记为 interrupted

`columns` 定义每帧数组的字段顺序。`screenX screenY` 使用 HUD 相同的枪口 X 正轴最近落点及玩家视口相对投影。`viewLeft viewTop viewWidth viewHeight` 保留约束视口。`width height` 是完整玩家视口像素大小。`valid` 和 `onScreen` 区分投影失败与准星越界 不做边界钳制。

`summary` 中带 Height 的二维数值均为屏幕高度比例 X 向右 Y 向上。基线为第一枪之前最后半秒。稳定阶段采用持续射击的后 60%。逐枪峰谷只有相邻开火事件间至少存在两帧时才计算。`settleSeconds` 表示末枪后回到基线三倍标准差或 0.2% 屏幕高度的较大范围且持续约四分之一秒。没有足够尾段时返回 null。

帧间隙 投影失败 视口或 FOV 改变 同帧多枪及大幅落点变化均单独报告 不插值掩盖。帧间隙必须结合实际采样帧率判断。镜头 真实枪口方向 后坐力输入和命中落点分别保留 不能用配置角度冒充实际屏幕位移。射击测试前必须通过现有输入工具完成装备并等待姿态稳定。

原生实现为项目编辑器模块的 `BBBRecoilProbeEditorLibrary` 不进入游戏运行时模块。统计实现为 `Scripts/BBBRecoilProbeTools.py`。离线测试为 `python -B -m unittest Tests.test_recoil_probe`。

`farScreenX farScreenY farValid` 额外保留枪口前方一千米点的投影 不做碰撞查询。它只用于识别近处遮挡和视差造成的准星跳变 不能替代 HUD 实际准星。`steadyCenterHeight` 是连射后段实际准星相对屏幕中心的平均位置 `steadyOffsetHeight` 才是相对开火前基线的变化。腰射抬枪会改变基线 两者必须分开理解。
