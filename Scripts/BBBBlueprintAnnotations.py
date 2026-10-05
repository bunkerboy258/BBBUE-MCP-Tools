import json
import re


def _text(value, field, required=True):
    """
    /**
     * 校验面向人的新增注释文字
     * @param value	文字值
     * @param field	字段名称
     * @param required	是否要求非空
     * @return 原文字
     */
    """
    if not isinstance(value, str) or len(value) > 2048:
        raise RuntimeError(field + " 必须为不超过 2048 字的文字")

    if required and not value.strip():
        raise RuntimeError(field + " 不允许为空")

    if any(character in value for character in (",", "，", "；", "：", "（", "）", "。", "！", "？")):
        raise RuntimeError(field + " 请用空格断句及半角符号")

    if any(ord(character) < 32 and character not in "\n\t" for character in value):
        raise RuntimeError(field + " 包含非法控制字符")

    if value.strip() and not re.search(r"[\u4e00-\u9fff]", value):
        raise RuntimeError(field + " 必须包含简体中文说明")

    return value


def prepare_annotations(snapshot, annotations_json):
    """
    /**
     * 将外部注释方案解析为确定的新增工作 不覆盖已有正文
     * @param snapshot	原生只读图表快照
     * @param annotations_json	注释方案 JSON
     * @return 校验后的新增区块 节点注释与重复结果
     */
    """
    request = json.loads(annotations_json)
    if not isinstance(request, dict) or set(request) != {"expectedSnapshot", "blocks", "nodeComments"}:
        raise RuntimeError("注释方案必须只包含 expectedSnapshot blocks nodeComments")

    if request["expectedSnapshot"] != snapshot["snapshot"]:
        raise RuntimeError("图表快照已变化 请重新读取并分析")

    if not isinstance(request["blocks"], list) or not isinstance(request["nodeComments"], list):
        raise RuntimeError("blocks 与 nodeComments 必须为数组")

    if len(request["blocks"]) > 64 or len(request["nodeComments"]) > 512:
        raise RuntimeError("单次最多 64 个区块和 512 个节点注释")

    nodes = {node["guid"]: node for node in snapshot["nodes"] if not node["isComment"]}
    comments = [node for node in snapshot["nodes"] if node["isComment"]]
    claimed = set()
    blocks = []
    node_comments = []
    skipped = []
    for index, block in enumerate(request["blocks"]):
        if not isinstance(block, dict) or set(block) != {"title", "description", "members"}:
            raise RuntimeError("区块必须只包含 title description members")

        title = _text(block["title"], "区块标题")
        description = _text(block["description"], "区块说明", False)
        if "\n" in title or len(title) > 120:
            raise RuntimeError("区块标题必须为不超过 120 字的单行文字")

        members = block["members"]
        if not isinstance(members, list) or not members or any(not isinstance(key, str) or key not in nodes for key in members):
            raise RuntimeError("区块成员必须为本图逻辑节点 GUID 的非空数组")

        if len(set(members)) != len(members) or claimed.intersection(members):
            raise RuntimeError("区块成员重复 共享节点只能归属一个区块")

        claimed.update(members)
        existing = [comment for comment in comments if set(comment["members"]) == set(members)]
        if len(existing) == 1 and existing[0]["nodeComment"] == title and existing[0]["details"] == description:
            skipped.append({"kind": "block", "guid": existing[0]["guid"]})
            continue

        if any(set(comment["members"]).intersection(members) for comment in comments):
            raise RuntimeError("新区块成员已经属于已有注释框 请保留已有分组")

        blocks.append({"id": "block:" + str(index), "title": title, "description": description, "members": sorted(members)})

    seen = set()
    for item in request["nodeComments"]:
        if not isinstance(item, dict) or set(item) != {"nodeGuid", "text"}:
            raise RuntimeError("节点注释必须只包含 nodeGuid text")

        key = item["nodeGuid"]
        if not isinstance(key, str) or key not in nodes or key in seen:
            raise RuntimeError("节点注释目标不存在或重复")

        seen.add(key)
        text = _text(item["text"], "节点注释")
        if nodes[key]["nodeComment"] == text:
            skipped.append({"kind": "node", "guid": key})
            continue

        if nodes[key]["nodeComment"]:
            raise RuntimeError("禁止覆盖已有节点注释 " + key)

        node_comments.append({"nodeGuid": key, "text": text})

    return {"expectedSnapshot": snapshot["snapshot"], "blocks": blocks, "nodeComments": node_comments, "skipped": skipped}


def layout_inputs(snapshot, measurement):
    """
    /**
     * 将节点正文与气泡的实际显示边界转为排版矩形
     * @param snapshot	语义快照
     * @param measurement	瞬态注释测量
     * @return 逻辑节点 连线 固定注释框与正文坐标偏移
     */
    """
    from BBBBlueprintLayout import _intersects

    semantics = {node["guid"]: node for node in snapshot["nodes"]}
    measured = {node["guid"]: node for node in measurement["nodes"]}
    if set(semantics) != set(measured):
        raise RuntimeError("注释测量遗漏或增加了原有节点")

    pin_anchors = {key: {pin["pinId"]: pin for pin in item["pins"]} for key, item in measured.items() if not semantics[key]["isComment"]}
    pin_orders = {key: {pin["pinId"]: index for index, pin in enumerate(item["pins"])} for key, item in semantics.items() if not item["isComment"]}

    nodes = {}
    offsets = {}
    comments = []
    for key, node in semantics.items():
        item = measured[key]
        if node["isComment"]:
            comments.append({"id": key, "x": node["x"], "y": node["y"], "width": item["width"], "height": item["height"], "members": list(node["members"])})
            continue

        left, top, right, bottom = item["visualBounds"]
        offsets[key] = (left, top)
        nodes[key] = {
            "id": key, "x": node["x"] + left, "y": node["y"] + top,
            "width": right - left, "height": bottom - top,
            "exec": any(pin["kind"] == "exec" for pin in node["pins"]),
            "pose": any(pin["kind"] == "pose" for pin in node["pins"]),
            "primaryOffset": min((pin["y"] - top for pin in item["pins"] if pin["kind"] in ("exec", "pose")), default=0),
        }

    edges = []
    for key, node in semantics.items():
        if node["isComment"]:
            continue

        anchors = pin_anchors[key]
        for order, pin in enumerate(node["pins"]):
            if pin["direction"] != "output":
                continue

            for link in pin["links"]:
                target = link["nodeGuid"]
                target_pins = pin_anchors[target]
                if pin["pinId"] not in anchors or link["pinId"] not in target_pins:
                    raise RuntimeError("连接引脚没有真实显示锚点")

                source_anchor = anchors[pin["pinId"]]
                target_anchor = target_pins[link["pinId"]]
                edges.append({
                    "source": key, "target": target, "kind": pin["kind"],
                    "sourceOrder": order, "targetOrder": pin_orders[target][link["pinId"]],
                    "sourcePin": pin["name"], "targetPin": target_anchor["name"],
                    "sourceOffset": [source_anchor["x"] - offsets[key][0], source_anchor["y"] - offsets[key][1]],
                    "targetOffset": [target_anchor["x"] - offsets[target][0], target_anchor["y"] - offsets[target][1]],
                    "spline": measurement["spline"],
                })

    for comment in comments:
        rectangle = (comment["x"], comment["y"], comment["x"] + comment["width"], comment["y"] + comment["height"])
        for key, node in nodes.items():
            bounds = (node["x"], node["y"], node["x"] + node["width"], node["y"] + node["height"])
            if _intersects(rectangle, bounds) and key not in comment["members"]:
                comment["members"].append(key)

    return nodes, edges, comments, offsets


def plan_annotations(snapshot, prepared, measurement):
    """
    /**
     * 计算新区块及节点的联合布局并生成原生写入计划
     * @param snapshot	语义快照
     * @param prepared	校验后的注释请求
     * @param measurement	真实显示测量
     * @return 注释与坐标写入计划和质量报告
     */
    """
    from BBBBlueprintLayout import calculate_annotation_layout

    nodes, edges, comments, offsets = layout_inputs(snapshot, measurement)
    blocks = [dict(block, headerWidth=measurement["blocks"][index]["headerWidth"], headerHeight=measurement["blocks"][index]["headerHeight"]) for index, block in enumerate(prepared["blocks"])]
    layout = calculate_annotation_layout(nodes, edges, comments, blocks)
    positions = {key: [x - offsets[key][0], y - offsets[key][1]] for key, (x, y) in layout["positions"].items()}
    planned_blocks = [dict(block, **layout["blocks"][block["id"]]) for block in prepared["blocks"]]
    allowed = not layout["after"]["overlaps"] and not layout["after"]["wireNodeIntersections"] and not layout["blockConflicts"]
    return {
        "expectedSnapshot": prepared["expectedSnapshot"], "nodeComments": prepared["nodeComments"],
        "blocks": planned_blocks, "positions": positions, "skipped": prepared["skipped"],
        "before": layout["before"], "after": layout["after"], "warnings": layout["warnings"],
        "wireNodeHits": layout["wireNodeHits"], "blockConflicts": layout["blockConflicts"],
        "canApply": allowed, "measurement": "SlateFullDetail", "saved": False,
    }
