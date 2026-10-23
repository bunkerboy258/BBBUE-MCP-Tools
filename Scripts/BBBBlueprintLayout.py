from collections import defaultdict
import heapq
from statistics import median
from bisect import bisect_left, bisect_right
from math import hypot


def _is_main(node):
    """/** @return 节点是否属于执行主链或姿势主链 */"""
    return node["exec"] or node.get("pose", False)


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
            heapq.heappush(ready, (not _is_main(nodes[key]), key))

    order = []
    while remaining:
        if not ready:
            key = min(remaining, key=lambda value: (not _is_main(nodes[value]), value))
            heapq.heappush(ready, (not _is_main(nodes[key]), key))

        _, key = heapq.heappop(ready)
        if key not in remaining:
            continue

        remaining.remove(key)
        order.append(key)
        for edge in outgoing[key]:
            target = edge["target"]
            incoming[target] -= 1
            if target in remaining and incoming[target] == 0:
                heapq.heappush(ready, (not _is_main(nodes[target]), target))

    indices = {key: index for index, key in enumerate(order)}
    forward = [edge for edge in edges if indices[edge["source"]] < indices[edge["target"]]]
    return order, forward


def _layout_flat_component(nodes, edges, horizontal_spacing, vertical_spacing):
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
        if _is_main(nodes[key]) or not outgoing[key]:
            continue

        if any(_is_main(nodes[edge["source"]]) and edge["kind"] == "data" for edge in incoming[key]):
            continue

        ranks[key] = min(ranks[edge["target"]] - 1 for edge in outgoing[key])

    consumers = {key: set() for key in nodes}
    for key in reversed(order):
        if _is_main(nodes[key]):
            consumers[key].add(key)
            continue

        for edge in outgoing[key]:
            consumers[key].update(consumers[edge["target"]])

    dependency_heights = defaultdict(int)
    for key in order:
        if _is_main(nodes[key]) or not consumers[key]:
            continue

        owner = min(consumers[key], key=lambda value: (ranks[value], value))
        dependency_heights[(owner, ranks[key])] += nodes[key]["height"] + 32

    lane_requests = defaultdict(list)
    lane_occupied = defaultdict(list)
    lanes = {}
    next_lane = 0
    for key in order:
        if not _is_main(nodes[key]):
            continue

        requests = lane_requests[key]
        if not requests:
            requests = [(0, next_lane)]
            next_lane += 1

        lane = float(min(requests)[1])
        while lane in lane_occupied[ranks[key]]:
            lane = next_lane
            next_lane += 1

        lanes[key] = lane
        lane_occupied[ranks[key]].append(lane)
        targets = sorted(
            (edge for edge in outgoing[key] if edge["kind"] in ("exec", "pose")),
            key=lambda edge: (edge["sourceOrder"], edge["target"]),
        )
        for index, edge in enumerate(targets):
            lane = lanes[key]
            if index > 0:
                lane = next_lane
                next_lane += 1

            lane_requests[edge["target"]].append((edge["targetOrder"], lane))

    lane_offsets = {}
    cursor_y = 0
    for lane in sorted(set(lanes.values())):
        members = [key for key in lanes if lanes[key] == lane]
        above = max(nodes[key].get("primaryOffset", 0) for key in members)
        below = max(
            nodes[key]["height"] - nodes[key].get("primaryOffset", 0)
            + max((height for (owner, rank), height in dependency_heights.items() if owner == key), default=0)
            for key in members
        )
        lane_offsets[lane] = cursor_y + above
        cursor_y += above + below + max(vertical_spacing, 64)

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
        y = round(lane_offsets[lanes[key]] - nodes[key].get("primaryOffset", 0))
        positions[key] = (x, y)
        occupied[ranks[key]].append((y, y + nodes[key]["height"]))

    pure_keys = sorted(
        (key for key in reversed(order) if not _is_main(nodes[key])),
        key=lambda key: (
            -ranks[key],
            min((edge.get("targetOffset", (0, edge["targetOrder"]))[1] for edge in outgoing[key]), default=0),
            key,
        ),
    )
    sink_row = 0
    for key in pure_keys:
        target_rows = []
        for edge in outgoing[key]:
            target = edge["target"]
            target_y = positions[target][1]
            if _is_main(nodes[target]):
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


def _dependency_groups(nodes, edges):
    """/** @return 按最终主节点消费者集合划分的专属参数组与共享参数组 */"""
    order, forward = _ordered_graph(nodes, edges)
    outgoing = defaultdict(list)
    for edge in forward:
        outgoing[edge["source"]].append(edge["target"])

    consumers = {}
    for key in reversed(order):
        consumers[key] = {key} if _is_main(nodes[key]) else set()
        if _is_main(nodes[key]):
            continue

        for target in outgoing[key]:
            consumers[key].update(consumers[target])

    groups = defaultdict(set)
    for key in order:
        owners = tuple(sorted(consumers[key]))
        group = ("owners", owners)
        if not owners:
            group = ("sink", (key,))

        groups[group].add(key)

    return dict(groups)


def _layout_component(nodes, edges, horizontal_spacing, vertical_spacing):
    """/** @return 先布局完整参数组 再按主链排列分组的节点位置 */"""
    groups = _dependency_groups(nodes, edges)
    if not any(_is_main(node) for node in nodes.values()):
        return _layout_flat_component(nodes, edges, horizontal_spacing, vertical_spacing)

    owners = {member: group for group, members in groups.items() for member in members}
    local_positions = {}
    group_nodes = {}
    for group, members in groups.items():
        local_nodes = {key: nodes[key] for key in members}
        local_edges = [edge for edge in edges if edge["source"] in members and edge["target"] in members]
        local = _layout_flat_component(local_nodes, local_edges, min(horizontal_spacing, 192), min(vertical_spacing, 96))
        bounds = _bounds(local_nodes, local)
        local_positions[group] = {key: (x - bounds[0], y - bounds[1]) for key, (x, y) in local.items()}
        main = next((key for key in members if _is_main(nodes[key])), None)
        group_nodes[group] = {
            "width": bounds[2] - bounds[0],
            "height": bounds[3] - bounds[1],
            "exec": main is not None,
            "primaryOffset": 0,
        }
        if main is not None:
            group_nodes[group]["primaryOffset"] = local_positions[group][main][1] + nodes[main].get("primaryOffset", 0)

    group_edges = []
    for edge in edges:
        source = owners[edge["source"]]
        target = owners[edge["target"]]
        if source == target:
            continue

        item = dict(edge, source=source, target=target)
        group_edges.append(item)

    group_positions = _layout_flat_component(group_nodes, group_edges, horizontal_spacing, vertical_spacing)
    return {
        key: (group_positions[group][0] + point[0], group_positions[group][1] + point[1])
        for group, members in local_positions.items() for key, point in members.items()
    }


def _dependency_group_conflicts(nodes, edges, positions):
    """/** @return 不同主节点参数组及共享组的区域交叠数量 */"""
    if not any(_is_main(node) for node in nodes.values()):
        return 0

    regions = [_bounds({key: nodes[key] for key in members}, positions) for members in _dependency_groups(nodes, edges).values()]
    return sum(_intersects(first, second) for index, first in enumerate(regions) for second in regions[index + 1:])


def _compact_shared_groups(nodes, edges, positions, movable, fixed_regions=()):
    """
    /**
     * 共享计算链整组靠近消费者 同时避开主链与其它参数区域
     * @param nodes	节点几何
     * @param edges	原始连线
     * @param positions	分组初始位置
     * @param movable	固定注释框外可移动节点
     * @param fixed_regions	不可侵入的固定注释区域
     * @return 保留分组的紧凑位置
     */
    """
    positions = dict(positions)
    groups = _dependency_groups(nodes, edges)
    if not _wire_hits(nodes, edges, positions) and not _dependency_group_conflicts(nodes, edges, positions):
        return positions

    for group, members in groups.items():
        if len(group[1]) < 2 or not members <= movable:
            continue

        local = {key: nodes[key] for key in members}
        bounds = _bounds(local, positions)
        width = bounds[2] - bounds[0]
        height = bounds[3] - bounds[1]
        targets = {edge["target"] for edge in edges if edge["source"] in members and edge["target"] not in members}
        if not targets:
            continue

        limit = min(positions[key][0] for key in targets) - width - 64
        incoming = [edge for edge in edges if edge["target"] in members and edge["source"] not in members]
        minimum = max((positions[edge["source"]][0] + nodes[edge["source"]]["width"] + 64 - positions[edge["target"]][0] + bounds[0] for edge in incoming), default=float("-inf"))
        xs = {min(bounds[0], limit), limit, limit - 64, limit - 160}
        xs = {x for x in xs if x >= minimum}
        ys = {bounds[1]}
        for key in targets:
            ys.update((positions[key][1] - height - 64, positions[key][1] + nodes[key]["height"] + 64))

        for other, region_members in groups.items():
            if other == group:
                continue

            region = _bounds({key: nodes[key] for key in region_members}, positions)
            ys.update((region[1] - height - 32, region[3] + 32))

        incident = {index for index, edge in enumerate(edges) if edge["source"] in members or edge["target"] in members}
        other_edges = set(range(len(edges))) - incident
        cache = {}
        original_hits = _wire_hits(nodes, edges, positions, cache)
        unchanged_hits = sum(index not in incident and key not in members for index, key in original_hits)

        def score(trial):
            """/** @return 优先保持几何约束 再比较画布面积与连线长度 */"""
            region = _bounds(local, trial)
            if any(_intersects(region, fixed) for fixed in fixed_regions):
                return (float("inf"),) * 5

            rectangles = [
                (trial[key][0], trial[key][1], trial[key][0] + node["width"], trial[key][1] + node["height"])
                for key, node in nodes.items()
            ]
            overlaps = sum(_intersects(first, second) for index, first in enumerate(rectangles) for second in rectangles[index + 1:])
            conflicts = _dependency_group_conflicts(nodes, edges, trial)
            if (overlaps, conflicts) > best_score[:2]:
                return (overlaps, conflicts, float("inf"), float("inf"), float("inf"))

            hits = unchanged_hits + len(_wire_hits(nodes, edges, trial, cache, incident))
            hits += len(_wire_hits(nodes, edges, trial, cache, other_edges, members))
            box = _bounds(nodes, trial)
            length = sum(hypot(trial[edge["target"]][0] - trial[edge["source"]][0], trial[edge["target"]][1] - trial[edge["source"]][1]) for edge in edges)
            return (overlaps, conflicts, hits, (box[2] - box[0]) * (box[3] - box[1]), length)

        best = positions
        best_score = (float("inf"),) * 5
        best_score = score(best)
        for x in sorted(xs):
            for y in sorted(ys, key=lambda value: (abs(value - bounds[1]), value))[:48]:
                trial = dict(positions)
                for key in members:
                    trial[key] = (round(positions[key][0] + x - bounds[0]), round(positions[key][1] + y - bounds[1]))

                candidate = score(trial)
                if candidate < best_score:
                    best = trial
                    best_score = candidate

        positions = best

    return positions


def _compact_group_roots(nodes, edges, positions, movable, horizontal_spacing, fixed_regions=()):
    """/** @return 将无外部输入的主链起点靠近消费者 缩短跨空白区域的长线 */"""
    positions = dict(positions)
    groups = _dependency_groups(nodes, edges)
    owners = {key: members for members in groups.values() for key in members}
    for members in groups.values():
        if not members <= movable or not any(_is_main(nodes[key]) for key in members):
            continue

        if any(edge["target"] in members and edge["source"] not in members for edge in edges):
            continue

        targets = {edge["target"] for edge in edges if edge["source"] in members and edge["target"] not in members}
        if not targets:
            continue

        bounds = _bounds({key: nodes[key] for key in members}, positions)
        limit = min(_bounds({key: nodes[key] for key in owners[target]}, positions)[0] for target in targets)
        shift = round(limit - max(horizontal_spacing, bounds[2] - bounds[0] + 64) - bounds[0])
        if shift <= 0:
            continue

        trial = dict(positions)
        for key in members:
            trial[key] = (positions[key][0] + shift, positions[key][1])

        region = _bounds({key: nodes[key] for key in members}, trial)
        if any(_intersects(region, fixed) for fixed in fixed_regions):
            continue

        before = layout_quality(nodes, edges, positions)
        after = layout_quality(nodes, edges, trial)
        if any(after[field] > before[field] for field in ("overlaps", "dependencyGroupOverlaps", "wireNodeIntersections", "backwardDataEdges", "backwardPoseEdges", "backwardExecEdges")):
            continue

        if after["wireLength"] < before["wireLength"]:
            positions = trial

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


def _wire_points(nodes, edge, positions):
    """
    /**
     * 使用宿主样式计算 Hermite 曲线 并自适应细分到一单位误差
     * @param nodes	节点尺寸
     * @param edge	引脚锚点和连线样式
     * @param positions	待检查坐标
     * @return 按曲线方向排列的采样点
     */
    """
    source = edge["source"]
    target = edge["target"]
    start_offset = edge.get("sourceOffset", (nodes[source]["width"], nodes[source]["height"] / 2))
    end_offset = edge.get("targetOffset", (0, nodes[target]["height"] / 2))
    start = tuple(positions[source][axis] + start_offset[axis] for axis in (0, 1))
    end = tuple(positions[target][axis] + end_offset[axis] for axis in (0, 1))
    settings = edge.get("spline", {})
    prefix = ""
    if end[0] < start[0]:
        prefix = "backward"

    dx = min(abs(end[0] - start[0]), settings.get(prefix + "horizontalRange", 1000))
    dy = min(abs(end[1] - start[1]), settings.get(prefix + "verticalRange", 1000))
    horizontal = settings.get(prefix + "horizontalTangent", (1, 0))
    vertical = settings.get(prefix + "verticalTangent", (1, 0))
    tangent = tuple(dx * horizontal[axis] + dy * vertical[axis] for axis in (0, 1))
    controls = (start, tuple(start[axis] + tangent[axis] / 3 for axis in (0, 1)), tuple(end[axis] - tangent[axis] / 3 for axis in (0, 1)), end)
    result = [start]
    pending = [(controls, 0)]
    while pending:
        points, depth = pending.pop()
        first, second, third, fourth = points
        chord = (fourth[0] - first[0], fourth[1] - first[1])
        squared_length = chord[0] ** 2 + chord[1] ** 2
        deviation = 0.0
        for point in (second, third):
            projection = 0.0
            if squared_length > 0:
                projection = max(0.0, min(1.0, sum((point[axis] - first[axis]) * chord[axis] for axis in (0, 1)) / squared_length))

            distance = sum((point[axis] - first[axis] - projection * chord[axis]) ** 2 for axis in (0, 1)) ** 0.5
            deviation = max(deviation, distance)
        if depth >= 12 or deviation <= 1:
            result.append(fourth)
            continue

        a = tuple((first[axis] + second[axis]) / 2 for axis in (0, 1))
        b = tuple((second[axis] + third[axis]) / 2 for axis in (0, 1))
        c = tuple((third[axis] + fourth[axis]) / 2 for axis in (0, 1))
        d = tuple((a[axis] + b[axis]) / 2 for axis in (0, 1))
        e = tuple((b[axis] + c[axis]) / 2 for axis in (0, 1))
        middle = tuple((d[axis] + e[axis]) / 2 for axis in (0, 1))
        pending.append(((middle, e, c, fourth), depth + 1))
        pending.append(((first, a, d, middle), depth + 1))

    return result


def _segment_hits_rect(start, end, rectangle):
    """
    /**
     * 裁剪线段以检查节点矩形
     * @param start	线段起点
     * @param end	线段终点
     * @param rectangle	含安全间隙的矩形
     * @return 是否相交
     */
    """
    low = 0.0
    high = 1.0
    for axis in (0, 1):
        delta = end[axis] - start[axis]
        if abs(delta) < 0.000001:
            if start[axis] < rectangle[axis] or start[axis] > rectangle[axis + 2]:
                return False

            continue

        first = (rectangle[axis] - start[axis]) / delta
        second = (rectangle[axis + 2] - start[axis]) / delta
        low = max(low, min(first, second))
        high = min(high, max(first, second))
        if low > high:
            return False

    return True


def _build_wire_index(nodes, positions):
    """
    /**
     * 建立当前计算的双向横轴碰撞索引
     * @param nodes	节点尺寸
     * @param positions	本次坐标
     * @return 左右边界索引及稳定节点顺序
     */
    """
    entries = [(order, key, (positions[key][0] - 8, positions[key][1] - 8, positions[key][0] + node["width"] + 8, positions[key][1] + node["height"] + 8)) for order, (key, node) in enumerate(nodes.items())]
    left = sorted(entries, key=lambda item: item[2][0])
    right = sorted(entries, key=lambda item: item[2][2])
    return left, [item[2][0] for item in left], right, [item[2][2] for item in right]


def _wire_candidates(index, bounds):
    """
    /**
     * 从较短的横轴候选集合筛选相交矩形
     * @param index	当前节点索引
     * @param bounds	曲线包围盒
     * @return 保持原节点顺序的碰撞候选
     */
    """
    left, starts, right, ends = index
    end = bisect_right(starts, bounds[2])
    start = bisect_left(ends, bounds[0])
    candidates = left[:end]
    if len(right) - start < end:
        candidates = right[start:]

    return sorted((entry for entry in candidates if entry[2][0] <= bounds[2] and entry[2][2] >= bounds[0] and entry[2][1] <= bounds[3] and entry[2][3] >= bounds[1]), key=lambda entry: entry[0])


def _wire_hits(nodes, edges, positions, cache=None, edge_indices=None, node_keys=None):
    """
    /**
     * 检查连线与非端点节点 留出八单位描边安全区
     * @param nodes	节点尺寸
     * @param edges	原始连线
     * @param positions	待检查坐标
     * @return 连线索引与阻挡节点列表
     */
    """
    hits = []
    rectangles = {
        key: (positions[key][0] - 8, positions[key][1] - 8, positions[key][0] + node["width"] + 8, positions[key][1] + node["height"] + 8)
        for key, node in nodes.items() if node_keys is not None and key in node_keys
    }
    spatial = None
    if node_keys is None:
        spatial = _build_wire_index(nodes, positions)
    indices = range(len(edges))
    if edge_indices is not None:
        indices = edge_indices

    for index in indices:
        edge = edges[index]
        signature = (index, positions[edge["source"]], positions[edge["target"]])
        cached = None
        if cache is not None:
            cached = cache.get(signature)

        if cached is None:
            points = _wire_points(nodes, edge, positions)
            bounds = (min(point[0] for point in points), min(point[1] for point in points), max(point[0] for point in points), max(point[1] for point in points))
            cached = (points, bounds)
            if cache is not None:
                cache[signature] = cached

        points, bounds = cached
        candidates = list(rectangles.items())
        if spatial is not None:
            candidates = [(key, rectangle) for order, key, rectangle in _wire_candidates(spatial, bounds)]

        for key, rectangle in candidates:
            if key in (edge["source"], edge["target"]):
                continue

            if bounds[2] < rectangle[0] or bounds[0] > rectangle[2] or bounds[3] < rectangle[1] or bounds[1] > rectangle[3]:
                continue

            if any(_segment_hits_rect(first, second, rectangle) for first, second in zip(points, points[1:])):
                hits.append((index, key))

    return hits


def _clear_wire_obstacles(nodes, edges, positions, allowed):
    """
    /**
     * 有界调整辅助节点 保持主链与固定分组约束
     * @param nodes	节点尺寸
     * @param edges	原始连线
     * @param positions	候选位置
     * @param allowed	允许移动的节点及上下边界
     * @return 调整后的坐标
     */
    """
    positions = dict(positions)
    cache = {}
    incidents = {key: set() for key in nodes}
    for index, edge in enumerate(edges):
        incidents[edge["source"]].add(index)
        incidents[edge["target"]].add(index)

    others = {key: [index for index in range(len(edges)) if index not in incident] for key, incident in incidents.items()}
    for attempt in range(min(128, len(nodes) * 4)):
        hits = _wire_hits(nodes, edges, positions, cache)
        if not hits:
            break

        best = None
        score = len(hits)
        candidates = set()
        for index, blocker in hits:
            edge = edges[index]
            points, bounds = cache[(index, positions[edge["source"]], positions[edge["target"]])]
            top = min(point[1] for point in points)
            bottom = max(point[1] for point in points)
            for key in (blocker, edge["source"], edge["target"]):
                if key not in allowed or _is_main(nodes[key]):
                    continue

                height = nodes[key]["height"]
                for y in (top - height - 32, bottom + 32, positions[key][1] - height - 64, positions[key][1] + height + 64, positions[blocker][1] - height - 64, positions[blocker][1] + nodes[blocker]["height"] + 64):
                    candidates.add((key, round(y)))

                for incident_index in incidents[key]:
                    connected = edges[incident_index]
                    target = connected["target"]
                    if connected["source"] != key:
                        continue

                    candidates.add((key, round(positions[target][1] - height - 64)))
                    candidates.add((key, round(positions[target][1] + nodes[target]["height"] + 64)))

        for key, y in sorted(candidates):
            minimum, maximum, obstacles = allowed[key]
            if not minimum <= y <= maximum - nodes[key]["height"]:
                continue

            trial = dict(positions)
            trial[key] = (positions[key][0], y)
            rectangle = (trial[key][0] - 16, y - 16, trial[key][0] + nodes[key]["width"] + 16, y + nodes[key]["height"] + 16)
            if any(_intersects(rectangle, obstacle) for obstacle in obstacles):
                continue

            if any(_intersects(rectangle, (trial[other][0], trial[other][1], trial[other][0] + nodes[other]["width"], trial[other][1] + nodes[other]["height"])) for other in nodes if other != key):
                continue

            incident = incidents[key]
            other = others[key]
            count = sum(index not in incident and blocker != key for index, blocker in hits)
            count += len(_wire_hits(nodes, edges, trial, cache, incident))
            count += len(_wire_hits(nodes, edges, trial, cache, other, {key}))
            if count < score:
                score = count
                best = trial

        if best is None:
            break

        positions = best
        cache = {signature: value for signature, value in cache.items() if signature[1] == positions[edges[signature[0]]["source"]] and signature[2] == positions[edges[signature[0]]["target"]]}

    return positions


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

    backward = {"exec": 0, "data": 0, "pose": 0}
    wire_length = 0
    for edge in edges:
        source = edge["source"]
        target = edge["target"]
        if positions[target][0] < positions[source][0] + nodes[source]["width"]:
            backward[edge["kind"]] += 1

        source_offset = edge.get("sourceOffset", (nodes[source]["width"], nodes[source]["height"] / 2))
        target_offset = edge.get("targetOffset", (0, nodes[target]["height"] / 2))
        wire_length += hypot(positions[target][0] + target_offset[0] - positions[source][0] - source_offset[0], positions[target][1] + target_offset[1] - positions[source][1] - source_offset[1])

    return {
        "bounds": list(bounds),
        "width": bounds[2] - bounds[0],
        "height": bounds[3] - bounds[1],
        "overlaps": overlaps,
        "backwardExecEdges": backward["exec"],
        "backwardDataEdges": backward["data"],
        "backwardPoseEdges": backward["pose"],
        "wireNodeIntersections": len(_wire_hits(nodes, edges, positions)),
        "dependencyGroupOverlaps": _dependency_group_conflicts(nodes, edges, positions),
        "wireLength": round(wire_length, 2),
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
    allowed = {}
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
            allowed[key] = (comment["y"] + 64, comment["y"] + comment["height"] - 32, [
                (other["x"], other["y"], other["x"] + other["width"], other["y"] + other["height"])
                for other in comments if other["id"] != comment["id"]
            ])

    free_nodes = {key: node for key, node in nodes.items() if key not in claimed}
    free_edges = [edge for edge in edges if edge["source"] in free_nodes and edge["target"] in free_nodes]
    obstacles = [
        (comment["x"], comment["y"], comment["x"] + comment["width"], comment["y"] + comment["height"])
        for comment in comments
    ]
    for key in free_nodes:
        allowed[key] = (float("-inf"), float("inf"), list(obstacles))
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
                allowed.pop(key, None)

            warnings.append("固定注释框约束导致连线方向或重叠恶化 保留整条连通链原位 " + min(members))

    fixed_regions = [(comment["x"], comment["y"], comment["x"] + comment["width"], comment["y"] + comment["height"]) for comment in comments]
    positions = _compact_shared_groups(nodes, edges, positions, set(free_nodes), fixed_regions)
    group_regions = []
    if any(_is_main(node) for node in nodes.values()):
        for members in _dependency_groups(nodes, edges).values():
            group_regions.append((members, _bounds({key: nodes[key] for key in members}, positions)))

    for members, region in group_regions:
        for key in members:
            if key not in allowed:
                continue

            minimum, maximum, fixed = allowed[key]
            blockers = [rect for other, rect in group_regions if other is not members]
            allowed[key] = (minimum, maximum, fixed + blockers)

    positions = _clear_wire_obstacles(nodes, edges, positions, allowed)
    positions = _compact_shared_groups(nodes, edges, positions, set(free_nodes), fixed_regions)
    positions = _compact_group_roots(nodes, edges, positions, set(free_nodes), horizontal_spacing, fixed_regions)
    if nodes and not comments:
        bounds = _bounds(nodes, positions)
        positions = {key: (x - bounds[0] + anchor_x, y - bounds[1] + min(node["y"] for node in nodes.values())) for key, (x, y) in positions.items()}

    hits = _wire_hits(nodes, edges, positions)
    if hits:
        warnings.append("仍有连线穿过节点 写入被拒绝 请检查固定分组或共享依赖")

    if _dependency_group_conflicts(nodes, edges, positions):
        warnings.append("主节点参数分组区域交叠 写入被拒绝 请检查固定分组或共享依赖")

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
        "wireNodeHits": [{"source": edges[index]["source"], "target": edges[index]["target"], "sourcePin": edges[index].get("sourcePin", ""), "targetPin": edges[index].get("targetPin", ""), "node": key} for index, key in hits],
    }


def _clear_annotation_wire_obstacles(nodes, edges, positions, regions):
    """
    /**
     * 在新注释框内部避让跨框连线 保持主链左右次序与固定注释原位
     * @param nodes\t节点显示尺寸
     * @param edges\t完整图表连线
     * @param positions\t候选位置
     * @param regions\t辅助节点允许占用的内部矩形
     * @return 通过严格减少穿线次数得到的位置
     */
    """
    positions = dict(positions)
    cache = {}
    incidents = {key: set() for key in nodes}
    for index, edge in enumerate(edges):
        incidents[edge["source"]].add(index)
        incidents[edge["target"]].add(index)

    others = {key: [index for index in range(len(edges)) if index not in incident] for key, incident in incidents.items()}
    visited = {tuple(sorted(positions.items()))}
    for attempt in range(min(128, len(nodes) * 4)):
        hits = _wire_hits(nodes, edges, positions, cache)
        if not hits:
            break

        best = None
        score = len(hits)
        equal = None
        equal_distance = float("inf")
        candidates = set()
        for index, blocker in hits:
            edge = edges[index]
            for key in (blocker, edge["source"], edge["target"]):
                if key not in regions:
                    continue

                x, y = positions[key]
                width = nodes[key]["width"]
                height = nodes[key]["height"]
                region = regions[key]
                for new_y in (region[1], region[3] - height, y - 128, y + 128, y - 320, y + 320):
                    candidates.add((key, round(x), round(new_y)))

                if not _is_main(nodes[key]):
                    for new_x in (region[0], region[2] - width, x - 128, x + 128):
                        for new_y in (y, region[1], region[3] - height):
                            candidates.add((key, round(new_x), round(new_y)))

                for fraction in (0.25, 0.5, 0.75):
                    new_y = region[1] + (region[3] - region[1] - height) * fraction
                    candidates.add((key, round(x), round(new_y)))
                    if not _is_main(nodes[key]):
                        for horizontal_fraction in (0.25, 0.5, 0.75):
                            new_x = region[0] + (region[2] - region[0] - width) * horizontal_fraction
                            candidates.add((key, round(new_x), round(new_y)))

                for other in (blocker, edge["source"], edge["target"]):
                    left, top = positions[other]
                    horizontal = (x,)
                    if not _is_main(nodes[key]):
                        horizontal = (x, left - width - 64, left + nodes[other]["width"] + 64)

                    for new_x in horizontal:
                        for new_y in (y, top - height - 64, top + nodes[other]["height"] + 64):
                            candidates.add((key, round(new_x), round(new_y)))

        for key, x, y in sorted(candidates):
            left, top, right, bottom = regions[key]
            width = nodes[key]["width"]
            height = nodes[key]["height"]
            if x < left or y < top or x + width > right or y + height > bottom:
                continue

            rectangle = (x - 16, y - 16, x + width + 16, y + height + 16)
            if any(_intersects(rectangle, (point[0], point[1], point[0] + nodes[other]["width"], point[1] + nodes[other]["height"])) for other, point in positions.items() if other != key):
                continue

            trial = dict(positions)
            trial[key] = (x, y)
            signature = tuple(sorted(trial.items()))
            if signature in visited:
                continue

            incident = incidents[key]
            count = sum(index not in incident and blocker != key for index, blocker in hits)
            count += len(_wire_hits(nodes, edges, trial, cache, incident))
            count += len(_wire_hits(nodes, edges, trial, cache, others[key], {key}))
            if count < score:
                best = trial
                score = count
            if count == len(hits):
                distance = abs(x - positions[key][0]) + abs(y - positions[key][1])
                if 0 < distance < equal_distance:
                    equal = trial
                    equal_distance = distance

        if best is None:
            best = equal

        if best is None:
            break

        positions = best
        visited.add(tuple(sorted(positions.items())))
        cache = {signature: value for signature, value in cache.items() if signature[1] == positions[edges[signature[0]]["source"]] and signature[2] == positions[edges[signature[0]]["target"]]}

    return positions


def calculate_annotation_layout(nodes, edges, comments, blocks):
    """
    /**
     * 将新区块视为整体排版并保护已有注释框
     * @param nodes	含气泡边界的节点
     * @param edges	真实连线与显示锚点
     * @param comments	固定注释框
     * @param blocks	新区块成员与标题测量
     * @return 联合位置 区块边界与质量报告
     */
    """
    original = {key: (node["x"], node["y"]) for key, node in nodes.items()}
    fixed = set().union(*(set(comment["members"]) for comment in comments)) if comments else set()
    owners = {}
    local_positions = {}
    groups = {}
    for block in blocks:
        members = set(block["members"])
        if members & fixed:
            raise RuntimeError("新区块侵入已有固定注释归属")

        subset = {key: nodes[key] for key in sorted(members)}
        connections = [edge for edge in edges if edge["source"] in members and edge["target"] in members]
        local = calculate_layout(subset, connections, [], 320, 180)
        bounds = _bounds(subset, local["positions"])
        header = max(64, block["headerHeight"] + 24)
        key = block["id"]
        for member in members:
            owners[member] = key
            position = local["positions"][member]
            local_positions[member] = (position[0] - bounds[0] + 32, position[1] - bounds[1] + header)

        primary = min((local_positions[member][1] + nodes[member].get("primaryOffset", 0) for member in members if _is_main(nodes[member])), default=header)
        groups[key] = {
            "id": key, "x": min(nodes[member]["x"] for member in members), "y": min(nodes[member]["y"] for member in members),
            "width": max(bounds[2] - bounds[0] + 64, block["headerWidth"] + 48),
            "height": bounds[3] - bounds[1] + header + 640,
            "exec": any(nodes[member]["exec"] for member in members),
            "pose": any(nodes[member].get("pose", False) for member in members), "primaryOffset": primary,
        }

    for key, node in nodes.items():
        if key in fixed or key in owners:
            continue

        owners[key] = key
        local_positions[key] = (0, 0)
        groups[key] = dict(node)

    connections = []
    for edge in edges:
        if edge["source"] in fixed or edge["target"] in fixed:
            continue

        source = owners[edge["source"]]
        target = owners[edge["target"]]
        if source == target:
            continue

        item = dict(edge, source=source, target=target)
        for name, member in (("sourceOffset", edge["source"]), ("targetOffset", edge["target"])):
            anchor = edge.get(name, [0, 0])
            item[name] = [local_positions[member][axis] + anchor[axis] for axis in (0, 1)]

        connections.append(item)

    obstacles = [dict(comment, members=[]) for comment in comments]
    group_plan = calculate_layout(groups, connections, obstacles, 320, 180)
    positions = dict(original)
    for member, owner in owners.items():
        origin = group_plan["positions"][owner]
        positions[member] = tuple(origin[axis] + local_positions[member][axis] for axis in (0, 1))

    rectangles = {
        block["id"]: {
            "x": group_plan["positions"][block["id"]][0], "y": group_plan["positions"][block["id"]][1],
            "width": groups[block["id"]]["width"], "height": groups[block["id"]]["height"],
        }
        for block in blocks
    }
    allowed = {}
    fixed_boxes = [(item["x"], item["y"], item["x"] + item["width"], item["y"] + item["height"]) for item in comments]
    for block in blocks:
        box = rectangles[block["id"]]
        minimum = box["y"] + max(64, block["headerHeight"] + 24)
        maximum = box["y"] + box["height"] - 16
        for member in block["members"]:
            allowed[member] = (minimum, maximum, fixed_boxes)

    positions = _clear_wire_obstacles(nodes, edges, positions, allowed)
    regions = {}
    for block in blocks:
        box = rectangles[block["id"]]
        for member in block["members"]:
            regions[member] = (box["x"] + 16, allowed[member][0], box["x"] + box["width"] - 16, allowed[member][1])

    positions = _clear_annotation_wire_obstacles(nodes, edges, positions, regions)
    for block in blocks:
        box = rectangles[block["id"]]
        bottom = max(positions[member][1] + nodes[member]["height"] for member in block["members"])
        box["height"] = bottom - box["y"] + 32

    conflicts = []
    for comment in comments:
        rectangle = (comment["x"], comment["y"], comment["x"] + comment["width"], comment["y"] + comment["height"])
        for key in comment["members"]:
            node = nodes[key]
            bounds = (positions[key][0], positions[key][1], positions[key][0] + node["width"], positions[key][1] + node["height"])
            if not (rectangle[0] <= bounds[0] and rectangle[1] <= bounds[1] and rectangle[2] >= bounds[2] and rectangle[3] >= bounds[3]):
                conflicts.append({"comment": comment["id"], "node": key, "reason": "固定框不能容纳显示边界"})

    for block in blocks:
        box = rectangles[block["id"]]
        rectangle = (box["x"], box["y"], box["x"] + box["width"], box["y"] + box["height"])
        for key, node in nodes.items():
            bounds = (positions[key][0], positions[key][1], positions[key][0] + node["width"], positions[key][1] + node["height"])
            if key in block["members"]:
                if not (rectangle[0] <= bounds[0] and rectangle[1] <= bounds[1] and rectangle[2] >= bounds[2] and rectangle[3] >= bounds[3]):
                    conflicts.append({"block": block["id"], "node": key, "reason": "成员越界"})
                continue

            if _intersects(rectangle, bounds):
                conflicts.append({"block": block["id"], "node": key, "reason": "侵入非成员"})

        for comment in comments:
            fixed_box = (comment["x"], comment["y"], comment["x"] + comment["width"], comment["y"] + comment["height"])
            if _intersects(rectangle, fixed_box):
                conflicts.append({"block": block["id"], "comment": comment["id"], "reason": "侵入固定框"})

    hits = _wire_hits(nodes, edges, positions)
    warnings = list(group_plan["warnings"])
    before = layout_quality(nodes, edges, original)
    after = layout_quality(nodes, edges, positions)
    for field in ("backwardExecEdges", "backwardPoseEdges"):
        if after[field] > before[field]:
            conflicts.append({"reason": "主链回流增加", "metric": field})

    if hits:
        warnings.append("联合布局仍有连线穿过节点 拒绝写入")

    if conflicts:
        warnings.append("新区块边界或成员存在冲突 拒绝写入")

    return {
        "positions": positions, "blocks": rectangles, "blockConflicts": conflicts,
        "before": before, "after": after,
        "warnings": warnings,
        "wireNodeHits": [{"source": edges[index]["source"], "target": edges[index]["target"], "node": key} for index, key in hits],
    }
