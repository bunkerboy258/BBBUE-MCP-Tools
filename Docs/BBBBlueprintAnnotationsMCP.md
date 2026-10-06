# 蓝图逻辑读取与注释排版

## 现行教学注释重写接口

`edit_blueprint_graph_comments(graph_path, request_json, dry_run=True)` 支持蓝图直属图以及嵌套状态和过渡图

请求只包含 `expectedSnapshot` `removeComments` `nodeComments`
`removeComments` 每项为 `nodeGuid` 与完整 `expectedText` 只允许说明框
`nodeComments` 每项为 `nodeGuid` `expectedText` `text` 只允许逻辑节点 允许以空正文清除旧气泡
原文或快照变化立即拒绝 每类至多 512 项 未列出的注释及全部节点坐标保持原样

实际写入调用原生 `EditBlueprintGraphComments` 要求非 PIE 和 Perforce 独占签出
单个事务逐项核对剩余节点和逻辑签名 失败恢复本次注释 成功后仍需明确编译保存
本接口仅在用户要求删除或重写旧注释时使用 不用于普通新增注释

`annotate_blueprint_graph` 的区块 `title` 现支持至多 2048 字的多行简体中文
把教学说明放入 `title` 可以直接在图中阅读 `description` 仍用于额外悬停说明
原生 Slate 测量会计算完整多行标题的高度 区块成员从正文下方开始排列
其它新增保护及布局质量检查保持生效

## 多行教学分组的连线避让

注释联合布局在分组内部复查全图连线 包括跨组共享参数线
数据直接来自执行节点的纯节点保持靠近来源 避免把同一对象的取值节点分散到远处
新分组内采用有界位置搜索 执行与姿势主链只做纵向避让 保持左右次序
辅助节点可以在本分组正文下方移动 原有固定注释及成员不参与此搜索
避让后收紧区块下边界 并重新检查成员范围 主链方向 节点重叠与精确曲线穿线
全部检查通过才允许写入 穿线计数没有放宽 不创建中转节点或改变原连线
复杂图可使用一个主分组配合关键节点气泡解释步骤 共享节点仍只保留一份


## 接口发现

通过官方 `list_toolsets` 寻找 `BBBBlueprintGraphToolset` 的实际注册名称
再使用 `describe_toolset` 读取参数结构
不要缓存带哈希的工具集名称

## 只读逻辑快照

`inspect_blueprint_graph(graph_path)` 返回完整图表对象路径对应的 JSON

`nodes` 使用节点 `guid` 和引脚 `pinId` 识别目标
包含原生节点类 标题 说明 函数或变量引用 属性访问路径 引脚默认值及完整连接
动画节点包含现有专项导出的结构值及绑定
`subGraphs` 提供宏 折叠图及状态机子图入口 需要深入分析时继续读取对应图表
原生函数源码和项目设计意图由调用方结合引用路径分析
不能从节点标题推断未提供的业务原因

`nodeComment` 为已有节点正文
注释框另含 `details` 和 `members`
`geometry` 在完整 Slate 测量成功时提供实际节点尺寸 引脚锚点及气泡边界
`layoutSupported=false` 的图表可以分析语义 但不得注释排版
`warnings` 明确返回无法解析的引用或不支持的测量

`snapshot` 校验逻辑 注释及位置
`logicSignature` 用于写入后确认原有逻辑未变
读取已有节点 不调用会临时创建节点的 DSL 默认值探测

## 注释方案

`annotate_blueprint_graph(graph_path, annotations_json, dry_run=True)` 默认只读预览
`annotations_json` 必须含以下三个字段

```json
{
    "expectedSnapshot": "inspect_blueprint_graph 返回的 snapshot",
    "blocks": [
        {
            "title": "目标方向更新",
            "description": "根据目标位置计算方向并发布更新结果",
            "members": ["目标节点 GUID", "另一个节点 GUID"]
        }
    ],
    "nodeComments": [
        {
            "nodeGuid": "目标节点 GUID",
            "text": "使用组件空间方向作为后续输入"
        }
    ]
}
```

区块按逻辑职责划分
节点注释优先解释阈值 单位 特殊条件与默认值
缺少证据的意图保留为待确认事项 不写入臆测
正文采用简体中文 使用空格断句和半角符号 不使用逗号
区块可见正文与节点正文各限 2048 字 允许换行 单次限 64 个区块和 512 个节点注释

只向空节点注释添加正文
不覆盖任何已有节点正文或注释框正文
同正文与同成员的已完成结果跳过
共享节点保留单份 且最多属于一个新区块
新区块采用单层分组 已有固定框中的成员不能再由新区块认领

## 独立说明框添加

`add_blueprint_comment_node(graph_path, expected_snapshot, text, x, y, width, height, dry_run=True)` 在明确空白位置添加说明框 不调整任何原有节点或分组

先读取 `inspect_blueprint_graph_logic` 并传入当前 `snapshot` 预览通过后使用同一方案传 `dry_run=false`
正文包含标题与多行说明 使用简体中文 空格断句及半角符号
宽度支持 200 至 4096 高度支持 100 至 4096 坐标必须为整数

适用于函数图及状态机过渡子图 不依赖完整自动排版测量
空白位置预检使用已有说明框尺寸及逻辑节点保守尺寸 因特殊节点可能更大 调用方还应确认正文可读且未遮挡原有内容
说明框不包含逻辑节点 移动模式为 `NoGroupMovement` 不改变现有说明框正文或分组
同正文且同位置的说明框跳过 同正文位于其它位置时拒绝重复添加

实际写入使用项目原生 `BBBBlueprintEditorLibrary.AddBlueprintCommentNode` 并要求非 PIE 及 Perforce 独占签出
该原生入口创建有效 GUID 及不包含逻辑节点的说明框 支持过渡子图 不受引擎 Python 说明框身份初始化限制
单个事务添加后逐项核对所有原有节点与连线及 `logicSignature` 并核对新框正文 坐标和尺寸
失败时移除本次新框并报警 不自动编译 保存 签出或 Submit

## 指定说明框删除

`remove_blueprint_comment_node(graph_path, node_guid, expected_text, dry_run=True)` 默认只读预览

从 `inspect_blueprint_graph_logic` 的当前快照取得说明框 GUID 和完整 `nodeComment` 正文
工具只接受 `EdGraphNode_Comment` 类型且原文完全匹配的单个说明框
实际删除使用 UE5.8 原生 `BlueprintGraphEditor.remove_comment_node` 接口
普通 `BlueprintTools.delete_node` 接口只支持 K2 逻辑节点 不适用于说明框

确认预览后传 `dry_run=false`
写入沿用项目 Perforce 独占签出与非 PIE 检查
删除后回读全部剩余节点并比较 `logicSignature` 发现其它变化时报警且不保存
工具不自动编译 保存 签出或 Submit
正文或 GUID 已变化时必须重新读取 不自动寻找相似说明框

## 联合排版

在瞬态副本测量新增气泡 不修改真实图表
区块内复用执行及姿势主链布局 数据靠近消费者
新区块根据实际成员显示边界和标题尺寸计算大小
跨区块连接参与整体排版
已有注释框及其成员保持固定
原有整理工具仍使用原固定框约束

预览返回 `positions` `blocks` `before` `after` `wireNodeHits` `blockConflicts` `canApply`
节点或气泡重叠 连线穿节点 区块侵入或成员越界时拒绝写入
环路可能需要回流 不承诺所有线之间无交叉
特殊图表或自定义绘线策略仍需视觉复核

## 写入与校验

确认预览后传 `dry_run=false`
写入要求非 PIE 项目资产已通过 Perforce 独占签出或打开添加
工具不自动签出 保存或 Submit
快照变化必须重新分析

原生入口再次校验身份 正文 显示边界及 Perforce 状态
单个编辑器事务记录新增框 节点正文 气泡状态和坐标
回读检查逻辑摘要 已有注释 新增正文及位置
回读失败恢复本次新增结果并记录错误
完成后可通过编辑器撤销

## 依赖与验证

原生接口位于项目 `BBBBlueprintEditorLibrary`

- `InspectBlueprintGraphSnapshot`
- `MeasureBlueprintGraphAnnotationGeometry`
- `ApplyBlueprintGraphAnnotations`
- `EditBlueprintGraphComments`

更新原生源码后先编译 UE5.8 编辑器模块再启动唯一隐藏 `-NullRHI` 宿主
启动入口自动注册 Python 工具
热更新通过既有注册生命周期重载辅助模块与图表工具后重新发现

隔离测试使用 `Tests/test_blueprint_annotations.py` 与 `Tests/test_blueprint_layout.py`
原生自动化测试为 `BBB.BlueprintAnnotations.Transaction`
该测试只操作瞬态图 验证真实气泡测量 写入 旧快照拒绝及撤销
真实资产先执行只读预览 实际资产写入限用户指定的已签出图表
