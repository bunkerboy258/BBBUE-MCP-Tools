# 当前编辑器摄影序列与媒体 UI 材质

`cinematic` 域在唯一资产编辑宿主中创建保存摄影序列并调用原生 Movie Render Queue. 不创建独立编辑器进程. 使用前登记干员并确认目标地图已保存且未运行 PIE.

| 工具 | 主要参数与行为 |
| --- | --- |
| `cinematic.create_shot` | `asset_path` `location` `rotation` 明确序列与世界机位. 朝向为 Pitch Yaw Roll. `dolly_cm` 沿视线恒速推进. `fov` 为水平视场角. 默认 60 帧 30 FPS. 默认拒绝覆盖. |
| `cinematic.render_shot` | `asset_path` `expected_level` `file_prefix` 明确已保存序列和当前地图. 默认 3840×2160 与 8 个时间采样. 输出到当前项目 `Saved/temp/<file_prefix>/frame_0000.png`. 目录必须不存在. |
| `cinematic.inspect_render` | 回读最近渲染状态 错误信息与实际 PNG 数量. |
| `cinematic.create_media_ui_material` | `asset_path` `texture_path` 创建 UI 材质. `alpha_only` 以纹理 Alpha 和顶点颜色绘制标题. 可指定 UV 起点与尺寸. 否则建立 `VideoTexture` 普通二维参数. 默认拒绝覆盖. |

序列使用原生 CineCameraActor 的 Spawnable 模板与 Camera Cut Binding ID. 电影渲染采用当前宿主内的 PIE Executor. 队列已有任务或编辑器已在 PIE 时拒绝执行. 队列与回调仅清理本工具创建的内容. 渲染结束前活动保持占用. 按批次返回的 `next` 继续查询即可.

`excluded_actor_names` 只销毁渲染临时游戏世界中明确列出的对象. Pawn 在临时世界隐藏且停用 Tick. 不保存或修改原地图对象. 渲染保留纹理流送与现有 LOD 防止小显存设备强制加载全部材质. 大地图需核对首尾帧是否完成植被与纹理加载.

媒体材质采用普通 Texture2D 采样. 运行时绑定 UMediaTexture 时应在 UpdateResource 前启用 NewStyleOutput. 标题材质仅取透明度 所有字色由 Slate 顶点色统一控制.

2026-11-05 在 UE5.8 当前可见编辑器实际完成八个序列和两项 UI 材质的创建 保存与脏包回读. 第一镜原生 MRQ 输出完整 60 帧 4K PNG 并核对首尾画面. 此证据不替代后续视频编码 包体菜单或跨网络联机验收.
