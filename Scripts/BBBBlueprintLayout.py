from collections import defaultdict
import heapq
from statistics import median


def _bounds(nodes, positions):
    """/** @return 节点矩形的合并边界 */"""
    if not nodes:
        return (0, 0, 0, 0)

    return (
        min(positions[key][0] for key in nodes),
        min(positions[key][1] for key in nodes),
        max(positions[key][0] + nodes[key]["width"] for key in nodes),
        max(positions[key][1] + nodes[key]["height"] for key in nodes),
    )


def _intersects(first, second, padding=0):
    """/** @return 两个矩形是否侵入安全间隙 */"""
    return (
        first[0] < second[2] + padding
        and second[0] < first[2] + padding
        and first[1] < second[3] + padding
        and second[1] < first[3] + padding
    )


def _components(nodes, edges):
    """/** @return 以稳定标识排序的弱连通分组 */"""
    neighbors = {key: set() for key in nodes}
    for edge in edges:
        source = edge["source"]
        target = edge["target"]
        neighbors[source].add(target)
        neighbors[target].add(source)

    remaining = set(nodes)
    result = []
    for root in sorted(nodes):
        if root not in remaining:
            continue

        pending = [root]
        remaining.remove(root)
        members = set()
        while pending:
            current = pending.pop()
            members.add(current)
            for target in sorted(neighbors[current]):
                if target not in remaining:
                    continue

                remaining.remove(target)
                pending.append(target)

        result.append(members)

    return result


def _ordered_graph(nodes, edges):
    """/** @return 拓扑顺序与前向视觉边 不改变真实连线 */"""
    outgoing = {key: [] for key in nodes}
    incoming = {key: 0 for key in nodes}
    for edge in edges:
        outgoing[edge["source"]].append(edge)
        incoming[edge["target"]] += 1

    ready = []
    remaining = set(nodes)
    for key in sorted(nodes):
        if incoming[key] == 0:
            heapq.heappush(ready, (not nodes[key]["exec"], key))

    order = []
    while remaining:
        if not ready:
            key = min(remaining, key=lambda value: (not nodes[value]["exec"], value))
            heapq.heappush(ready, (not nodes[key]["exec"], key))

        _, key = heapq.heappop(ready)
        if key not in remaining:
            continue

        remaining.remove(key)
        order.append(key)
        for edge in outgoing[key]:
            target = edge["target"]
            incoming[target] -= 1
            if target in remaining and incoming[target] == 0:
                heapq.heappush(ready, (not nodes[target]["exec"], target))

    indices = {key: index for index, key in enumerate(order)}
    forward = [edge for edge in edges if indices[edge["source"]] < indices[edge["target"]]]
    return order, forward


def _layout_component(nodes, edges, horizontal_spacing, vertical_spacing):
    """/** @return 执行主链与局部数据块的相对位置 */"""
    order, forward = _ordered_graph(nodes, edges)
    outgoing = {key: [] for key in nodes}
    incoming = {key: [] for key in nodes}
    for edge in forward:
        outgoing[edge["source"]].append(edge)
        incoming[edge["target"]].append(edge)

    ranks = {key: 0 for key in nodes}
    for key in order:
        for edge in outgoing[key]:
            target = edge["target"]
            ranks[target] = max(ranks[target], ranks[key] + 1)

    # 纯节点向消费者收紧 不让只有一条依赖的变量留在全图最左列
    for key in reversed(order):
        if nodes[key]["exec"] or not outgoing[key]:
            continue

        ranks[key] = min(ranks[edge["target"]] - 1 for edge in outgoing[key])

    consumers = {key: set() for key in nodes}
    for key in reversed(order):
        if nodes[key]["exec"]:
            consumers[key].add(key)
            continue

        for edge in outgoing[key]:
            consumers[key].update(consumers[edge["target"]])

    dependency_heights = defaultdict(int)
    for key in order:
        if nodes[key]["exec"] or not consumers[key]:
            continue

        owner = min(consumers[key], key=lambda value: (ranks[value], value))
        dependency_heights[(owner, ranks[key])] += nodes[key]["height"] + 32

    lane_stride = (
        max(node["height"] for node in nodes.values())
        + max(dependency_heights.values(), default=0)
        + max(vertical_spacing, 64)
    )
    lane_requests = defaultdict(list)
    lane_occupied = defaultdict(list)
    lanes = {}
    next_lane = 0
    for key in order:
        if not nodes[key]["exec"]:
            continue

        requests = lane_requests[key]
        if not requests:
            requests = [next_lane]
            next_lane += 1

        y = round(float(median(requests)) * lane_stride)
        height = nodes[key]["height"]
        for start, end in sorted(lane_occupied[ranks[key]]):
            if y + height + 32 <= start:
                break

            if y < end + 32:
                y = end + 32

        lanes[key] = y / lane_stride
        lane_occupied[ranks[key]].append((y, y + height))
        targets = sorted(
            (edge for edge in outgoing[key] if edge["kind"] == "exec"),
            key=lambda edge: (edge["sourceOrder"], edge["target"]),
        )
        for index, edge in enumerate(targets):
            lane = lanes[key]
            if index > 0:
                lane = next_lane
                next_lane += 1

            lane_requests[edge["target"]].append(lane)

    column_widths = defaultdict(int)
    for key in nodes:
        column_widths[ranks[key]] = max(column_widths[ranks[key]], nodes[key]["width"])

    column_x = {}
    cursor = 0
    for rank in sorted(column_widths):
        column_x[rank] = cursor
        cursor += max(horizontal_spacing, column_widths[rank] + 64)

    positions = {}
    occupied = defaultdict(list)
    for key in order:
        if key not in lanes:
            continue

        x = column_x[ranks[key]]
        y = round(lanes[key] * lane_stride)
        positions[key] = (x, y)
        occupied[ranks[key]].append((y, y + nodes[key]["height"]))

    pure_keys = sorted(
        (key for key in reversed(order) if not nodes[key]["exec"]),
        key=lambda key: (
            -ranks[key],
            min((edge["targetOrder"] for edge in outgoing[key]), default=0),
            key,
        ),
    )
    sink_row = 0
    for key in pure_keys:
        target_rows = []
        for edge in outgoing[key]:
            target = edge["target"]
            target_y = positions[target][1]
            if nodes[target]["exec"]:
                target_y += nodes[target]["height"] + 32

            target_rows.append(target_y)

        y = sink_row
        if target_rows:
            y = round(median(target_rows))

        if not target_rows:
            sink_row += max(vertical_spacing, nodes[key]["height"] + 32)

        height = nodes[key]["height"]
        for start, end in sorted(occupied[ranks[key]]):
            if y + height + 32 <= start:
                break

            if y < end + 32:
                y = end + 32

        positions[key] = (column_x[ranks[key]], y)
        occupied[ranks[key]].append((y, y + height))

    return positions


def _pack_components(nodes, edges, horizontal_spacing, vertical_spacing):
    """/** @return 左边界对齐并垂直分区的独立逻辑链 */"""
    positions = {}
    cursor_y = 0
    for members in _components(nodes, edges):
        local_nodes = {key: nodes[key] for key in members}
        local_edges = [edge for edge in edges if edge["source"] in members and edge["target"] in members]
        local = _layout_component(local_nodes, local_edges, horizontal_spacing, vertical_spacing)
        bounds = _bounds(local_nodes, local)
        for key, (x, y) in local.items():
            positions[key] = (x - bounds[0], y - bounds[1] + cursor_y)

        cursor_y += bounds[3] - bounds[1] + max(vertical_spacing, 64)

    return positions


def _place_beside_obstacles(x, y, width, height, obstacles):
    """
    /**
     * 选择离原分组最近的空位 不把所有框外节点推到画布底部
     * @param x		原分组左边界
     * @param y		原分组上边界
     * @param width		新分组宽度
     * @param height	新分组高度
     * @param obstacles	固定框和已排分组边界
     * @return 可容纳分组且距离最小的左上角
     */
    """
    candidates = {(x, y)}
    for rect in obstacles:
        candidates.update({
            (rect[0] - width - 32, y),
            (rect[2] + 32, y),
            (x, rect[1] - height - 32),
            (x, rect[3] + 32),
        })

    available = [
        (left, top) for left, top in candidates
        if not any(_intersects((left, top, left + width, top + height), rect, 32) for rect in obstacles)
    ]
    return min(available, key=lambda point: (abs(point[0] - x) + abs(point[1] - y), abs(point[1] - y), point))


def layout_quality(nodes, edges, positions):
    """
    /**
     * 仅计算几何指标 不承诺所有连线都能无交叉
     * @param nodes		节点尺寸快照
     * @param edges		原始有向连线
     * @param positions	待检查的位置
     * @return 边界 重叠与逆向连线计数
     */
    """
    bounds = _bounds(nodes, positions)
    rectangles = sorted(
        (positions[key][0], positions[key][1], positions[key][0] + node["width"], positions[key][1] + node["height"], key)
        for key, node in nodes.items()
    )
    overlaps = 0
    for index, first in enumerate(rectangles):
        for second in rectangles[index + 1:]:
            if second[0] >= first[2]:
                break

            if _intersects(first, second):
                overlaps += 1

    backward = {"exec": 0, "data": 0}
    for edge in edges:
        source = edge["source"]
        target = edge["target"]
        if positions[target][0] < positions[source][0] + nodes[source]["width"]:
            backward[edge["kind"]] += 1

    return {
        "bounds": list(bounds),
        "width": bounds[2] - bounds[0],
        "height": bounds[3] - bounds[1],
        "overlaps": overlaps,
        "backwardExecEdges": backward["exec"],
        "backwardDataEdges": backward["data"],
    }


def calculate_layout(nodes, edges, comments, horizontal_spacing=320, vertical_spacing=180):
    """
    /**
     * 在引擎之外计算位置 保留固定注释框的成员边界
     * @param nodes			节点尺寸与执行类型快照
     * @param edges			带原生类型和引脚顺序的连线
     * @param comments			固定注释框矩形
     * @param horizontal_spacing	水平最小步距
     * @param vertical_spacing		分区最小步距
     * @return 位置与排版质量报告
     */
    """
    original = {key: (node["x"], node["y"]) for key, node in nodes.items()}
    positions = dict(original)
    warnings = []
    claimed = set()
    memberships = {}
    for comment in comments:
        rect = (comment["x"], comment["y"], comment["x"] + comment["width"], comment["y"] + comment["height"])
        memberships[comment["id"]] = {
            key for key, node in nodes.items()
            if rect[0] <= node["x"]
            and rect[1] <= node["y"]
            and node["x"] + node["width"] <= rect[2]
            and node["y"] + node["height"] <= rect[3]
        }
        memberships[comment["id"]].update(key for key in comment.get("members", []) if key in nodes)

    # 嵌套或交叠注释不猜测归属 保留成员原位并报警
    multiple = set()
    for first in comments:
        for second in comments:
            if first["id"] == second["id"]:
                continue

            shared = memberships[first["id"]] & memberships[second["id"]]
            if shared:
                multiple.update(memberships[first["id"]] | memberships[second["id"]])

    for comment in sorted(comments, key=lambda value: value["id"]):
        members = memberships[comment["id"]]
        claimed.update(members)
        if not members:
            continue

        if members & multiple:
            warnings.append("注释框嵌套或归属交叠 保留成员原位 " + comment["id"])
            continue

        local_nodes = {key: nodes[key] for key in members}
        local_edges = [edge for edge in edges if edge["source"] in members and edge["target"] in members]
        local = _pack_components(local_nodes, local_edges, horizontal_spacing, vertical_spacing)
        bounds = _bounds(local_nodes, local)
        if bounds[2] + 64 > comment["width"] or bounds[3] + 96 > comment["height"]:
            warnings.append("注释框空间不足 保留成员原位 " + comment["id"])
            continue

        for key, (x, y) in local.items():
            positions[key] = (comment["x"] + 32 + x, comment["y"] + 64 + y)

    free_nodes = {key: node for key, node in nodes.items() if key not in claimed}
    free_edges = [edge for edge in edges if edge["source"] in free_nodes and edge["target"] in free_nodes]
    obstacles = [
        (comment["x"], comment["y"], comment["x"] + comment["width"], comment["y"] + comment["height"])
        for comment in comments
    ]
    anchor_x = min((node["x"] for node in list(nodes.values()) + comments), default=0)
    cursor_y = min((node["y"] for node in list(nodes.values()) + comments), default=0)
    for members in _components(free_nodes, free_edges):
        local_nodes = {key: free_nodes[key] for key in members}
        local_edges = [edge for edge in free_edges if edge["source"] in members and edge["target"] in members]
        local = _layout_component(local_nodes, local_edges, horizontal_spacing, vertical_spacing)
        bounds = _bounds(local_nodes, local)
        width = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]
        left = anchor_x
        top = cursor_y
        if comments:
            original_bounds = _bounds(local_nodes, original)
            left, top = _place_beside_obstacles(original_bounds[0], original_bounds[1], width, height, obstacles)

        for key, (x, y) in local.items():
            positions[key] = (x - bounds[0] + left, y - bounds[1] + top)

        obstacles.append((left, top, left + width, top + height))
        cursor_y += height + max(vertical_spacing, 64)

    for members in _components(nodes, edges):
        if not members & claimed:
            continue

        local_nodes = {key: nodes[key] for key in members}
        local_edges = [edge for edge in edges if edge["source"] in members and edge["target"] in members]
        regressed = any(
            original[edge["target"]][0] >= original[edge["source"]][0] + nodes[edge["source"]]["width"]
            and positions[edge["target"]][0] < positions[edge["source"]][0] + nodes[edge["source"]]["width"]
            for edge in local_edges
        )
        before = layout_quality(local_nodes, local_edges, original)
        after = layout_quality(local_nodes, local_edges, positions)
        if regressed or after["overlaps"] > before["overlaps"]:
            for key in members:
                positions[key] = original[key]

            warnings.append("固定注释框约束导致连线方向或重叠恶化 保留整条连通链原位 " + min(members))

    _, forward = _ordered_graph(nodes, edges)
    if len(forward) != len(edges):
        warnings.append("图表存在环路 回流线保留 不修改实际连线")

    return {
        "positions": positions,
        "before": layout_quality(nodes, edges, original),
        "after": layout_quality(nodes, edges, positions),
        "cycleBreaks": len(edges) - len(forward),
        "components": len(_components(nodes, edges)),
        "commentMembers": len(claimed),
        "warnings": warnings,
    }


if __name__ == "__bbb_editor_script__":
    import importlib
    import sys

    import toolset_registry
    import unreal

    previous_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        importlib.invalidate_caches()
        importlib.reload(importlib.import_module("BBBBlueprintLayout"))
        toolset_registry.reload_module(importlib.import_module("BBBBlueprintGraphToolset"))
        unreal.log("[BBBBlueprintLayout] 已仅重载蓝图排版工具 请重新发现参数并验证")
    except Exception as error:
        unreal.log_error("[BBBBlueprintLayout] 工具重载失败 请检查注册状态 " + str(error))
        raise
    finally:
        sys.dont_write_bytecode = previous_bytecode
