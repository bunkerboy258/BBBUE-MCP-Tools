"""/** 高频任务的简短调用路线与完成判据 */"""

ROUTES = {
    "object.set_properties": {
        "use_when": "已知对象与属性值，修改并核实目标字段",
        "difference": "object.list_properties 查字段类型；object.get_properties 读取值",
        "workflow": [
            {"tool": "object.list_properties", "when": "字段名称或类型待确认", "inputs": ["instance", "query"]},
            {"tool": "object.set_properties", "when": "目标与值已经明确", "inputs": ["instance", "values"]},
            {"evidence": "批次 completed、字段回读匹配、保存证据"},
        ],
    },
    "blueprint.annotate_blueprint_graph": {
        "use_when": "为节点或区块添加注释并结合布局整理",
        "difference": "inspect_blueprint_graph 读取逻辑；optimize_blueprint_node_layout 整理位置",
        "workflow": [
            {"tool": "blueprint.inspect_blueprint_graph", "when": "读取逻辑与当前快照", "inputs": ["graph_path", "view=logic"]},
            {"tool": "blueprint.annotate_blueprint_graph", "when": "预览注释范围与布局质量", "inputs": ["graph_path", "annotations", "dry_run=true"]},
            {"tool": "blueprint.annotate_blueprint_graph", "when": "范围确认后按当前快照应用", "inputs": ["graph_path", "annotations", "dry_run=false"]},
            {"tool": "blueprint.inspect_blueprint_graph", "when": "分别回读逻辑与几何", "inputs": ["graph_path", "view"]},
            {"evidence": "快照匹配、注释与成员范围正确、连线逻辑一致、布局质量与保存证据"},
        ],
    },
    "animation.sample_weapon_handling_runtime": {
        "use_when": "采样武器装备或换弹的实际运行时事实",
        "difference": "run_pie_input_sequence 注入输入；采样事实与图像各自提供验收证据",
        "workflow": [
            {"environment": "test", "when": "独立测试", "inputs": ["test_options.map", "实际玩家与渲染需求"]},
            {"tool": "app.StartPIE", "when": "启动所属测试世界", "inputs": ["options"]},
            {"tool": "animation.sample_weapon_handling_runtime", "when": "启动对应运行时采样", "inputs": ["action=start", "seconds"]},
            {"tool": "animation.run_pie_input_sequence", "when": "已有采样与实际玩法输入", "inputs": ["steps"]},
            {"tool": "inspect_tasks", "when": "按业务版本等待所属 weapon:probe 活动结束", "inputs": ["batch", "after_revision", "wait_seconds=30"]},
            {"tool": "animation.sample_weapon_handling_runtime", "when": "输入与采样活动完成后读取事实", "inputs": ["action=status"]},
            {"tool": "app.StopPIE", "when": "证据交付后结束所属 PIE", "inputs": []},
            {"evidence": "输入注入、实际状态与时序满足任务判据、测试宿主收尾"},
        ],
    },
}

PURPOSES = {
    "editor.inspect_animation_notifies": "读取通知事件及时间位置",
    "editor.add_animation_notify_events": "按明确事件类型与时间添加通知",
    "blueprint.inspect_blueprint_graph": "读取图表逻辑、快照或几何",
    "blueprint.optimize_blueprint_node_layout": "整理现有节点位置并返回布局质量",
    "animation.run_pie_input_sequence": "按给定步骤注入玩法输入",
    "object.list_properties": "查找反射字段名称与类型",
    "object.get_properties": "读取指定反射字段当前值",
    "asset.save_assets": "保存明确给出的目标资产",
    "assets.resave_assets": "按明确资产范围执行重新保存",
}


def guidance(contract, available):
    """/** @param contract\t当前契约 @param available\t实际注册目录 @return 当前目标的短用途与路线 */"""
    import copy
    identity = contract["id"]
    access = contract["access"]
    result = {"use_when": PURPOSES.get(identity, {"read": "读取目标当前状态", "write": "修改明确目标并核验结果", "pie": "在所属测试世界执行操作"}[access]),
              "complete_when": {"read": "返回目标状态", "write": "批次完成并交付回读与保存证据", "pie": "批次与活动达到对应完成状态"}[access]}
    if "dry_run" in contract["parameters"].get("properties", {}):
        result["complete_when"] = "预览返回计划；正式应用交付回读与保存证据"
    route = ROUTES.get(identity)
    if route is not None:
        result.update({key: copy.deepcopy(value) for key, value in route.items() if key != "workflow"})
        if all(item.get("tool") in available or item.get("tool") == "inspect_tasks" for item in route["workflow"] if "tool" in item):
            result["workflow"] = copy.deepcopy(route["workflow"])
    return result
