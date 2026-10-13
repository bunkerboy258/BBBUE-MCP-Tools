# 蓝图图表排版

公开批次默认完成本批次范围的验证、保存与回读。分阶段预览或人工检查时传 `completion="review"`。下文函数级保存行为描述对应领域实现；公开调用的完成策略以批次参数为准。

`BBBBlueprintGraphToolset.optimize_blueprint_node_layout` 根据原生引脚连接进行从左到右的分层排版。参数为 `graph_path`、`horizontal_spacing`、`vertical_spacing` 与 `dry_run`。先使用 `dry_run=true` 检查重叠、反向连线及预计移动数量，再写入。

工具只移动节点坐标，回读确认节点、引脚连线与固定注释不变，不自动保存。目标资产必须已通过 Perforce 独占签出或打开添加。签出检查使用资产的实际 `.uasset` 文件路径并强制刷新状态，避免对象路径导致未知状态。完成后编译并显式保存目标资产。
