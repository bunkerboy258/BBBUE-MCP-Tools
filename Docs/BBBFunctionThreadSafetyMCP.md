# 蓝图函数线程安全 MCP

工具 configure_blueprint_function_thread_safety 位于 BBBBlueprintGraphToolset
参数 blueprint_path function_name thread_safe dry_run
默认 dry_run 只读检查 函数逻辑须先经过线程安全审查
写入仅改变函数入口声明 保留现有文档元数据 编译成功才保存
执行前须完成目标正式资产的 Perforce 独占签出 独立副本不提交资产
PIE 期间拒绝操作 入口缺失 编译失败 保存失败均报错
