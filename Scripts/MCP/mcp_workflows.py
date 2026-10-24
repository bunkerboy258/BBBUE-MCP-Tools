"""/** 高频任务的简短调用路线与完成判据 */"""

ROUTES = {
    "control_rig.build_hand_retarget_sequences": {
        "use_when": "按明确的接触帧把左手校正到指定的右手局部握持位置",
        "difference": "生成独立可编辑序列；bake_hand_retarget_sequences 再写出私有动画",
        "workflow": [
            {"tool": "control_rig.inspect_sequence_bindings", "when": "核对现有模板的角色、源动作和 Control Rig 轨道", "inputs": ["sequence_path"]},
            {"tool": "control_rig.build_hand_retarget_sequences", "when": "提供握持变换和不重叠的接触帧区间", "inputs": ["manifest", "write_paths"]},
            {"tool": "control_rig.bake_hand_retarget_sequences", "when": "将代表序列烘焙到新动画并核验允许差异", "inputs": ["manifest", "write_paths"]},
            {"evidence": "输出序列与动画各自保存回读；非左臂姿势、曲线、通知、根运动和叠加设置保持"},
        ],
    },
    "control_rig.bake_hand_retarget_sequences": {
        "use_when": "把左手 Control Rig 序列写入新的左臂修正动画",
        "difference": "使用官方 Sequencer 烘焙器；不修改源动作，也不遍历其它 Lyra 动画",
        "workflow": [
            {"tool": "control_rig.build_hand_retarget_sequences", "when": "尚未生成本次修正序列", "inputs": ["manifest", "write_paths"]},
            {"tool": "control_rig.bake_hand_retarget_sequences", "when": "逐项烘焙并保留其它骨骼、曲线与通知", "inputs": ["manifest", "write_paths"]},
            {"evidence": "目标动画新建、仅左臂白名单可变且所有保存后回读通过"},
        ],
    },
    "object.set_properties": {
        "use_when": "已知对象与属性值，修改并核实目标字段",
        "difference": "object.list_properties 查字段类型；object.get_properties 读取值",
        "workflow": [
            {"tool": "object.list_properties", "when": "字段名称或类型待确认", "inputs": ["instance", "query"]},
            {"tool": "object.set_properties", "when": "目标与值已经明确", "inputs": ["instance", "values"]},
            {"evidence": "批次 completed、字段回读匹配、保存证据"},
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
    "control_rig.build_hand_retarget_sequences": "按接触区间生成左手握持重定向序列",
    "control_rig.bake_hand_retarget_sequences": "只烘焙左臂并保留其它动画数据",
    "editor.inspect_animation_notifies": "读取通知事件及时间位置",
    "editor.add_animation_notify_events": "按明确事件类型与时间添加通知",
    "blueprint.inspect_blueprint_graph": "读取图表逻辑、快照或几何",
    "blueprint.format_blueprint_graph": "调用 Graph Formatter 原生命令整理节点并核对逻辑",
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
