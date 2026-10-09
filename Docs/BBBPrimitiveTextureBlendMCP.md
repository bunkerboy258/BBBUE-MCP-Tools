# 共享图元纹理混合

`BBBGenericEditorToolset.create_primitive_texture_blend_material` 复制明确的源主材质到不存在的 `/Game/_Project/` 目标。参数为 source_path material_path texture_parameter alternate_parameter primitive_index。索引默认零。

工具要求原颜色纹理参数唯一并连接到表达式消费者。新增轻度纹理参数和一个图元标量 以零选择轻度纹理 以一选择原纹理。保留原颜色后处理链以及其它材质输入。只增加一个颜色纹理采样 不改来源材质 不创建逐实例动态材质。不修改几何或法线的感染程度。

创建前检查目标源控状态和图元索引占用。拒绝已有目标 错误类型 重复参数 无消费者或连接保存失败。批量组合调用不是事务 已创建对象不会自动删除或回滚。

僵尸正式共享皮肤实例绑定轻重两张来源纹理。出生感染度由 Mass 初始化处理器使用稳定实例身份一次确定 表现桥接将归一化感染度写入 SkeletalMesh 的 CustomPrimitiveData 索引零。载体复用时覆盖该值 生存期内不重新抽样。眼睛 服装和头发不改写。此方式减少逐实例材质对象 不能据此宣称骨骼网格已实现批量合并绘制。
