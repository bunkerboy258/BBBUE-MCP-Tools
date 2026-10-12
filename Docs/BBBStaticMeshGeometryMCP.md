# 静态网格几何核验

使用 `rigid.inspect_static_mesh_geometry` 传入一至一百个唯一的静态网格包路径。此只读工具等待已有资产编译完成 返回源顶点数 非有限源顶点数 源包围盒有限性 实际渲染包围盒有限性 渲染中心与半尺寸 快速构建标记和简单碰撞形体数量。

局部扩展包围盒正常不能证明渲染数据正常 应同时检查 `sourceBoundsFinite` 与 `renderBoundsFinite`。正式断肢资产使用标准编辑器构建 部件保留一个简单碰撞形体 封口没有碰撞。

有限数值也可能是未初始化数据。还须将 `renderOrigin` 与 `renderExtent` 和 `editor.inspect_static_mesh_bounds` 返回的实际网格局部范围比较 拒绝零尺寸 负半尺寸或明显不一致的范围。
