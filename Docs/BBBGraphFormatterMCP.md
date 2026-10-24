# Graph Formatter 图表整理

公共入口为 `blueprint.format_blueprint_graph(graph_path, node_guids=[])`

仅使用作者发布的 UE 5.8 版 Graph Formatter 2.3.1 不使用 master 替代发布版本
官方发布地址 https://github.com/howaajin/graphformatter/releases/tag/ue5.8
Win64 发布包 BuildId 为 55116800 必须匹配实际引擎

工具不修改 Graph Formatter 或 Electronic Nodes 源码
Graph Formatter 执行排列 Electronic Nodes 自行绘制连线 MCP 不调用连线插件
MCP 通过项目编辑器模块 ExecuteGraphFormatter 接入已注册的 GraphFormatterEditor/FormatGraph 命令
无需链接插件私有头文件或复制算法 不生成自研排列 不自动增删 Reroute 节点

需要已初始化 Slate 的可视资产编辑宿主 PIE 中拒绝操作
原版插件按鼠标位置选择图表 接入先打开指定蓝图并定位目标图表
命令执行前验证焦点图表与鼠标命中的 SGraphEditor 均为目标 随后恢复鼠标和节点选择
图表控件未布局 或命令未注册时明确失败 不回退其它算法

空 node_guids 数组整理整张图
非空数组使用只读快照 GUID 原版插件的单节点选择会扩展到连通节点 注释框选择会包含框内节点
不承诺选择范围严格等于移动范围 返回 positions 是实际发生几何变化的节点
间距 算法 参数分组使用插件原有 Editor Preferences 设置 MCP 不维护第二份设置

插件本身提供排列事务 可以通过编辑器撤销
MCP 比较前后节点身份 引脚连接 配置 资源引用与注释 仅允许坐标及尺寸变化
验证失败拒绝保存 并要求撤销插件本次事务 不宣称能够恢复任意插件产生的逻辑修改
工具不自行保存 公开批次负责目标资产的保存与回读

旧 optimize_blueprint_node_layout 和 annotate_blueprint_graph 入口已删除
旧 BBBBlueprintLayout BBBBlueprintWireRouting 及自动注释布局算法不再加载
手动移动 手动注释和明确路径布线仍独立保留

## 本机验证 2026-10-24

UE 5.8 Development 编辑器构建通过 官方插件源文件 27 项与发布包逐字节哈希一致
插件调用核验专项 5 项 工具发现及契约专项 31 项通过 隔离 HTTP 流程 20 类通过
较广 MCP 回归 202 项中 201 项通过 另 1 项为现有 Control Rig 领域重复映射导致的范围测试失败 未在本任务修改

Base 的 FullBody_SkeletalControls 共 43 节点 调用后连接 配置 资源引用与注释签名保持
默认设置首次画布 5848 x 2702 原画布 4977 x 2190 节点重叠从 1 变为 0 但整体范围更大
顶部算法及 64/40 间距可缩小画布 仍未满足姿势主链与参数分区要求
连续调用仍移动大量节点 本机未通过动画图视觉及稳定性验收
插件分组实现只识别 Exec 没有把 PoseLink 单独作为主链输入
动画图已恢复本轮测试前全部 43 节点坐标 原有逻辑签名保持

SetUpIdleState 普通函数 6 节点 含 2 个原有说明框 调用与注释保护通过
该函数保留验证后的插件布局 允许说明框尺寸随插件排列变化 原文及逻辑不变
未批量排列其它图表 没有以自研规则修正插件输出
试验项目配置已移除 下次编辑器启动恢复原有默认设置 当前进程未强制重载配置

结果的 layoutQualityVerified 固定为 false 只验证逻辑及注释 不把技术调用成功当作视觉通过
撤销由插件原生 FScopedTransaction 提供 本轮未单独执行撤销与重做操作验收
