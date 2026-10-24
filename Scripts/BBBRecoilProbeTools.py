import math
import statistics


def summarize(result):
    """/** @param result 原生逐帧数据 @return 不跨无效样本计算的屏幕后坐力统计 */"""
    rows = [dict(zip(result.get("columns", []), row)) for row in result.get("samples", [])]
    valid = [r for r in rows if r["valid"] and r["viewWidth"] > 0 and r["viewHeight"] > 0]
    for row in valid:
        row["right"] = (row["screenX"] - row["viewWidth"] * 0.5) / row["viewHeight"]
        row["up"] = (row["viewHeight"] * 0.5 - row["screenY"]) / row["viewHeight"]
    intervals = [b["time"] - a["time"] for a, b in zip(rows, rows[1:])]
    shots = [b for a, b in zip(rows, rows[1:]) if b["shot"] > a["shot"]]
    first = shots[0]["time"] if shots else math.inf
    last = shots[-1]["time"] if shots else math.inf
    baseline = [r for r in valid if first - 0.5 <= r["time"] < first]
    shooting = [r for r in valid if first <= r["time"] <= last]
    tail = [r for r in shooting if r["time"] >= first + (last - first) * 0.4]
    after = [r for r in valid if r["time"] > last]
    warnings = []
    if len(baseline) < 3:
        warnings.append("缺少至少三帧开火前基线")
    if any(b["frame"] <= a["frame"] or b["time"] <= a["time"] for a, b in zip(rows, rows[1:])):
        warnings.append("帧号或游戏时间不递增")
    if len(valid) != len(rows):
        warnings.append("存在无效投影 不纳入轨迹统计")
    if len({(r["viewWidth"], r["viewHeight"], round(r["fov"], 2)) for r in rows}) > 1:
        warnings.append("采样期间视口或 FOV 改变")
    if any(b["shot"] - a["shot"] > 1 for a, b in zip(rows, rows[1:])):
        warnings.append("存在同帧多枪或漏采 无法拆解每枪峰谷")
    if any(math.dist([a[k] for k in ("impactX", "impactY", "impactZ")], [b[k] for k in ("impactX", "impactY", "impactZ")]) > 5000
           for a, b in zip(valid, valid[1:])):
        warnings.append("存在大幅落点距离变化 应检查遮挡或背景切换")
    center = [statistics.fmean(r[k] for r in baseline) if baseline else 0.0 for k in ("right", "up")]
    mean = [statistics.fmean(r[k] for r in tail) if tail else 0.0 for k in ("right", "up")]
    peak = [max((abs(r[k] - center[i]) for r in shooting), default=0) for i, k in enumerate(("right", "up"))]
    cycles = []
    for a, b in zip(shots, shots[1:]):
        cycle = [r["up"] for r in tail if a["time"] <= r["time"] < b["time"]]
        if len(cycle) >= 2:
            cycles.append(max(cycle) - min(cycle))
    settle = None
    if baseline and after:
        tolerance = [max(0.002, 3 * statistics.pstdev(r[k] for r in baseline)) for k in ("right", "up")]
        for row in after:
            window = [r for r in after if row["time"] <= r["time"] <= row["time"] + 0.25]
            if window[-1]["time"] - row["time"] < 0.2:
                continue
            if all(abs(r[k] - center[i]) <= tolerance[i] for r in window for i, k in enumerate(("right", "up"))):
                settle = row["time"] - last
                break
    return {"sampleCount": len(rows), "validCount": len(valid), "offscreenCount": sum(not r["onScreen"] for r in valid),
        "frameGaps": sum(max(0, int(b["frame"] - a["frame"] - 1)) for a, b in zip(rows, rows[1:])),
        "sampleFPS": 1 / statistics.median(intervals) if intervals else None,
        "shotCount": sum(max(0, b["shot"] - a["shot"]) for a, b in zip(rows, rows[1:])),
        "firstShotTime": first if shots else None, "lastShotTime": last if shots else None,
        "baselineCenterHeight": center, "peakOffsetHeight": peak,
        "steadyCenterHeight": mean,
        "steadyOffsetHeight": [mean[i] - center[i] for i in (0, 1)],
        "steadyVerticalSpanHeight": max((r["up"] for r in tail), default=0) - min((r["up"] for r in tail), default=0),
        "medianShotCycleVerticalSpanHeight": statistics.median(cycles) if cycles else None,
        "settleSeconds": settle, "warnings": warnings}


def sample_runtime(action, seconds, offset, limit):
    """/** @param action 开始 查询或结束 @param seconds 时长 @param offset 页起点 @param limit 页长度 @return 原生视口采样和统一统计 */"""
    import json
    import unreal
    from BBBMcpCapabilities import register_activity

    library = unreal.BBBRecoilProbeEditorLibrary
    methods = {"start": lambda: library.start_recoil_probe(seconds),
               "status": library.read_recoil_probe, "stop": library.stop_recoil_probe}
    if action not in methods or offset < 0 or limit < 0 or limit > 1200:
        raise RuntimeError("后坐力探针动作或分页范围无效")
    result = json.loads(methods[action]())
    if result.get("state") == "rejected":
        raise RuntimeError(result.get("error", "后坐力探针请求被拒绝"))
    if action == "start":
        register_activity("recoil:probe", lambda: json.loads(library.read_recoil_probe(False)), blocking=False, wait=False)
    result["summary"] = summarize(result)
    samples = result.get("samples", [])
    result["totalSamples"] = len(samples)
    result["offset"] = offset
    result["samples"] = samples[offset:offset + limit]
    result["nextOffset"] = offset + limit if limit and offset + limit < len(samples) else None
    return result
