# 蓝图逻辑读取与注释排版

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
单个标题限 120 字 正文限 2048 字 单次限 64 个区块和 512 个节点注释

只向空节点注释添加正文
不覆盖任何已有节点正文或注释框正文
同正文与同成员的已完成结果跳过
共享节点保留单份 且最多属于一个新区块
新区块采用单层分组 已有固定框中的成员不能再由新区块认领

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

更新原生源码后先编译 UE5.8 编辑器模块再启动唯一隐藏 `-NullRHI` 宿主
启动入口自动注册 Python 工具
热更新通过既有注册生命周期重载辅助模块与图表工具后重新发现

隔离测试使用 `Tests/test_blueprint_annotations.py` 与 `Tests/test_blueprint_layout.py`
原生自动化测试为 `BBB.BlueprintAnnotations.Transaction`
该测试只操作瞬态图 验证真实气泡测量 写入 旧快照拒绝及撤销
真实资产先执行只读预览 实际资产写入限用户指定的已签出图表
