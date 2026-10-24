from copy import deepcopy


def verify_formatter_result(before, after):
    """
    /**
     * 核对插件只改变节点及注释框几何 不计算排列
     * @param before	命令前逻辑快照
     * @param after	命令后逻辑快照
     * @return 修改数量与语义验证结果
     */
    """
    if before.get("logicSignature") != after.get("logicSignature"):
        raise RuntimeError("插件整理改变了图表逻辑 拒绝保存 请撤销本次整理")
    original = {node["guid"]: node for node in before["nodes"]}
    current = {node["guid"]: node for node in after["nodes"]}
    if len(original) != len(before["nodes"]) or len(current) != len(after["nodes"]) or set(original) != set(current):
        raise RuntimeError("插件整理增删节点或节点身份重复 拒绝保存")
    changes = []
    for key, node in original.items():
        old = deepcopy(node)
        new = deepcopy(current[key])
        for value in (old, new):
            for field in ("x", "y", "width", "height"):
                value.pop(field, None)
        if old != new:
            raise RuntimeError("插件整理改变了节点配置或原有注释 拒绝保存 " + key)
        if node != current[key]:
            changes.append({"nodeGuid": key, "x": current[key]["x"], "y": current[key]["y"]})
    return {"moved": len(changes), "positions": changes, "semanticConnectionsVerified": True, "commentsVerified": True, "layoutQualityVerified": False}
