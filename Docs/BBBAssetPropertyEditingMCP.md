# 资产子对象嵌套属性编辑

`editor.configure_asset_properties` 接受自有资产的完整对象路径，也接受该资产下明确的子对象路径。接口验证 Outer 链和所属包，沿用写入保护，保存资产本体。嵌套字典仅更新指定字段，不把未指定的结构成员重置为默认值。指定字段在保存前后逐项回读，不一致时报警。

动画节点示例：

```json
{
  "asset_path": "/Game/_Project/Characters/BBBC_UA/Animation/blueprints/BBBABP_UA.BBBABP_UA:AnimGraph.AnimGraphNode_MotionMatching_0",
  "properties": {"node": {"bUseInertialBlend": true}}
}
```

使用引擎原始反射字段名称。枚举沿用 `enumType` 和 `value` 的显式类型表示；Python 只读字段不能通过普通赋值修改。接口返回 `structTexts`，保留结构的引擎导出文本。确需恢复被损坏的只读结构字段时，可以把刚读出的完整文本作为既有 `structType` / `structText` 输入，只替换明确字段，随后比较所有结构成员，避免通过重新构造默认结构丢失其他配置。不要使用 `object.set_properties` 整份 JSON 回写动画节点结构。

蓝图修改后仍须编译并读取图表核对。当前接口不自动运行 PIE 或验收表现。

2026-11-02：三项隔离检查覆盖嵌套更新保留兄弟字段、跨资产子对象拒绝和回读失败禁止保存。实际主动画蓝图恢复 `ExclusiveAlwaysLeader`，开启 `bUseInertialBlend`，重启编辑器后逐字段回读确认其他 MM 配置未变。动态效果由用户验收。
