# 资产入库与重定向验证

实际工具集名称必须通过 list_toolsets 发现。外部 retarget 入口的参数采用 params_json。

## UE5.8 重定向

create_retargeter 在创建时建立默认求解操作栈并分配源与目标 IK Rig。仅有链映射而没有操作栈会导出静止姿势，不能以批量导出返回成功作为动画通过依据。

initialize_retarget_ops(retargeter_path, dry_run=true) 返回操作栈与链映射。dry_run=false 仅初始化已经独占签出或待添加的空栈，拒绝重复初始化非空栈。失败后先检查资产状态，不自动重试写入。

batch_retarget 必须提供 target_path，使用 UE5.8 run_batch_retarget 接口。search 与 replace 是动画名称替换，不是目录迁移。默认拒绝已有目标；overwrite_existing=true 仅允许覆盖已独占签出或待添加的目标。每个导出资产独立保存，拒绝越界路径与数量不一致。

导出后使用 probe_animation_component_poses 抽样验证骨骼确实变化、根位移、循环接缝与死亡末帧。渲染验证需要有 RHI 的唯一宿主，NullRHI 不能提供有效视觉证据。不保存其他会话的脏包。
