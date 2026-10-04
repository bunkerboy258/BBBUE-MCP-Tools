# 显式时间动画过渡图

通过官方发现查找 BBBAnimationGraphToolset，先核对原生 BBBAnimationGraphEditorLibrary 已加载。

create_sequence_crossfade_blueprint 只创建不存在的资产。提供动画实例父类、同骨架预览网格和序列，以及六个只读查询：甲序列、乙序列、甲时间、乙时间、乙启用、混合时间。原生实现连接两个 Sequence Evaluator 和 Blend Poses by Bool，不保留旧播放路径，不使用蒙太奇通知驱动玩法。求值器开启显式时间跳转，禁用通知推进和根运动提取。标准布尔节点零号通道是真、一号通道是假，不能凭编辑器排列误接。

蓝图必须无警告编译通过才保存，已有已制作的动画图拒绝覆盖。创建失败不自动重试，先检查是否存在脏资产。

configure_actor_animation_blueprint 将已编译的同骨架动画蓝图绑定至演员蓝图指定默认组件属性。演员蓝图须事先 Perforce 独占签出；工具验证骨架、编译后回读并仅保存这一资产。新建 UE 二进制资产仍须按项目要求登记为 binary+l，不自动 Submit。

完成绑定后必须重新加载资产验证持久化，并使用真实运行时采样确认切换、同状态新动作和显式进度。创建成功不代表动画视觉验收通过。

Perforce 待添加的新演员资产也允许配置，必须由当前工作区持有且没有其它工作区占用；调用方需先回读文件类型为 binary+l。待添加不等于 IsCheckedOut，不能为了满足检查而自动 Submit。

当前生成图使用标准纯函数节点直接连接六个只读快照查询，不依赖属性访问缓存。bind_sequence_crossfade_getters 可对明确独占持有的标准双通道图重连输入；原生实现要求一个输出、一个布尔混合及两个序列求值器，拒绝含其它逻辑的已制作图。旧属性访问节点被整体移除，不保留兼容播放路径。必须检查实际求值器资产和权重，而非仅动画实例查询结果。

程序创建 UAnimGraphNode 后必须执行 PostPlacedNewNode，初始化绑定并请求编译扩展。缺少此步骤时连线和编译状态可能正确，实际求值器仍取空资产；本工具创建和重连均执行该步骤。原生依赖位于项目 Source/ABBB_EvacEditor/Public 与 Private 下的 BBBAnimationGraphEditorLibrary，单独分发本 Python 模块不能替代项目原生编译。
