# 资产入库与重定向验证

实际工具集名称必须通过 list_toolsets 发现。外部 retarget 入口的参数采用 params_json。

## UE5.8 重定向

create_retargeter 在创建时建立默认求解操作栈并分配源与目标 IK Rig。仅有链映射而没有操作栈会导出静止姿势，不能以批量导出返回成功作为动画通过依据。

initialize_retarget_ops(retargeter_path, dry_run=true) 返回操作栈与链映射。dry_run=false 仅初始化已经独占签出或待添加的空栈，拒绝重复初始化非空栈。失败后先检查资产状态，不自动重试写入。

batch_retarget 必须提供 target_path，使用 UE5.8 run_batch_retarget 接口。search 与 replace 是动画名称替换，不是目录迁移。默认拒绝已有目标；overwrite_existing=true 仅允许覆盖已独占签出或待添加的目标。每个导出资产独立保存，拒绝越界路径与数量不一致。

导出后使用 probe_animation_component_poses 抽样验证骨骼确实变化、根位移、循环接缝与死亡末帧。渲染验证需要有 RHI 的唯一宿主，NullRHI 不能提供有效视觉证据。不保存其他会话的脏包。

## 独立动画切片

create_animation_slice(source_path, destination_path, start_frame, end_frame) 将闭区间帧范围复制为新的 AnimSequence。源资产只读，拒绝已有目标、越界帧、加法动画、变换修正曲线、通知和同步标记；禁止 PIE 期间执行。浮点曲线和属性由引擎控制器裁剪时间范围，骨骼轨道显式重建；每帧每条骨骼轨道核对局部位置、旋转和缩放后单独保存，日志使用 [BBBAnimationSlice] PASS。失败时先核查目标是否已创建或保存，不直接重复写入。二进制新资产由调用方按项目规则办理 Perforce 待添加。

## PIE 组件反射验证

invoke_pie_object_function(object_path, function_name, arguments_json="[]") 调用正在运行的任意 PIE 世界中的 Actor 或 ActorComponent 反射函数，支持主客机组件的公开状态 getter；不接受普通资产、编辑器世界或非反射函数，不保存资产。返回目标世界路径及实际结果，日志使用 [BBBPIEObjectCall]。有副作用的调用仍需处于用户批准的任务范围，失败后检查实际状态，不自动重复提交。
