# 蓝图手动注释

`blueprint.add_blueprint_comment_node` 在指定坐标创建明确尺寸的中文说明框
`blueprint.edit_blueprint_graph_comments` 按快照和原文校验修改说明或节点注释
`blueprint.remove_blueprint_comment_node` 按明确标识删除说明框

这些操作不自动排列节点 不改变节点连接
节点整理单独调用 `blueprint.format_blueprint_graph`
