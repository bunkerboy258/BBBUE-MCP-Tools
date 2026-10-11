import argparse
from copy import deepcopy
import json
from pathlib import Path
import random
from statistics import median
import subprocess
import sys
from time import perf_counter
import types


sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Scripts"))
import BBBBlueprintLayout as current


def main():
    """/** @return 同输入同质量的历史提交与当前排版比较 */"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--repeats", type=int, default=3)
    representative = parser.add_mutually_exclusive_group()
    representative.add_argument("--snapshot-stdin", action="store_true")
    representative.add_argument("--graph")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 20:
        raise RuntimeError("重复次数必须为 1 至 20")

    source = subprocess.run(["git", "show", args.baseline + ":Scripts/BBBBlueprintLayout.py"], cwd=ROOT, check=True, capture_output=True, encoding="utf-8").stdout
    baseline = types.ModuleType("baseline_layout")
    exec(compile(source, "baseline_layout", "exec"), baseline.__dict__)
    fixtures = []
    snapshot = None
    if args.graph:
        from MCP.mcp_call import McpSession
        with McpSession(timeout_seconds=120) as session:
            session.describe_tool("blueprint.inspect_blueprint_graph")
            identity = session.submit_batch([{"tool": "blueprint.inspect_blueprint_graph", "arguments": {"graph_path": args.graph}}], "代表图只读基准")["batch"]
            result = session.wait_batch(identity, 180)
            if result["status"] != "completed":
                raise RuntimeError(str(result))
            snapshot = result["results"][0]
            session.control_task("close", identity)

    if args.snapshot_stdin:
        snapshot = json.loads(sys.stdin.readline())

    if snapshot is not None:
        from BBBBlueprintAnnotations import layout_inputs
        nodes, edges, comments, offsets = layout_inputs(snapshot, snapshot["geometry"])
        fixtures.append(("representative", nodes, edges, comments))

    generator = random.Random(4721)
    for size, density in ((35, 0.08), (90, 0.015)):
        keys = [str(index).zfill(3) for index in range(size)]
        nodes = {key: {"id": key, "exec": index % 3 == 0, "x": generator.randrange(-3000, 3000), "y": generator.randrange(-3000, 3000), "width": generator.randrange(80, 600), "height": generator.randrange(40, 300)} for index, key in enumerate(keys)}
        edges = [{"source": source, "target": target, "kind": "exec" if nodes[source]["exec"] and nodes[target]["exec"] else "data", "sourceOrder": 0, "targetOrder": 0} for index, source in enumerate(keys) for target in keys[index + 1:] if generator.random() < density]
        fixtures.append(("generated:" + str(size), nodes, edges, []))

    report = []
    for name, nodes, edges, comments in fixtures:
        inputs = deepcopy((nodes, edges, comments))
        results = []
        times = []
        for module in (baseline, current):
            samples = []
            result = None
            for attempt in range(args.repeats):
                started = perf_counter()
                result = module.calculate_layout(nodes, edges, comments)
                samples.append((perf_counter() - started) * 1000)

            results.append(result)
            times.append(median(samples))

        if results[0] != results[1] or inputs != (nodes, edges, comments):
            raise RuntimeError("排版质量或输入一致性失败 " + name)

        report.append({"fixture": name, "nodes": len(nodes), "edges": len(edges), "baselineMs": times[0], "currentMs": times[1], "identical": True, "quality": results[1]["after"]})

    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
