# 正式握姿彩色三视图

`Scripts/BBBGripVisualReview.py` 是离线只读 CLI。复用原 `visual_rifle02.py` 的 Pillow 三角面绘制、颜色、XZ / YZ / XY 投影、尺寸与明暗逻辑；没有候选旋转覆盖，没有拟合器，不启动 UE，不生成 PIE 或引擎截图，不修改角色或武器资产。

## 使用前提

1. 先完成武器相对右手方向的判断与制作，保存正式动画、挂接和左手 IK。
2. 通过原生 `editor.sample_skeletal_mesh_surface` 分别采样角色正式握姿动画与武器参考网格。角色需要双手时，应明确包含 `hand_l` 与 `hand_r`，最低权重沿用本任务采样设置；右手采样无法生成左手图。
3. 所有采样必须是 LOD0、组件空间厘米、`readOnly=true`、`localRotationOverrides={}`。字符网格和动画必须与正式 recipe 一致，骨骼组件姿势必须与正式解一致；校准尚未保存时会拒绝绘制。
4. 每把武器独立确认真实面片区域。不要复制其他型号的面片编号或连通组件序号。区域清单同时绑定武器资产路径和原始采样 JSON 的 SHA256。

## 区域清单

清单属于当前任务临时输入，放在 `Saved/temp/明确任务目录/`。正式 recipe 已有的 `calibration.right_palm.weapon_triangle_ids` 可以作为本枪右手握持区域输入；左手、扳机、护圈及机匣区域仍须依据该枪实际采样明确选择。工具不猜测区域，不内置型号或组件编号。

```json
{
    "format": "BBBGripVisualRegions",
    "schema": 1,
    "weapon_mesh": "/Game/明确武器/Mesh/明确网格",
    "weapon_sample_sha256": "原始武器采样JSON字节的SHA256",
    "regions": {
        "right_grip": [明确面片编号],
        "left_grip": [明确面片编号],
        "trigger": [明确扳机与护圈面片编号],
        "receiver": [明确邻近机匣面片编号]
    }
}
```

上面的中文占位必须替换成实际值。允许增加其他具名参考区域。请求缺失区域、重复编号、未知编号或另一份采样的清单均会报错，不静默丢弃。

## CLI

```powershell
& '<已安装NumPy和Pillow的Python>' -B E:/UE5.8/BBBUE-MCP-Tools/Scripts/BBBGripVisualReview.py `
    --project-root E:/BBB_Evac `
    --character E:/BBB_Evac/Saved/temp/明确任务/正式双手原生采样.json `
    --weapon E:/BBB_Evac/Saved/temp/明确任务/本枪原生采样.json `
    --recipe E:/BBB_Evac/Content/本枪/Source/Animation/正式制作源.json.source `
    --regions E:/BBB_Evac/Saved/temp/明确任务/本枪视觉区域.json `
    --side both --palm `
    --reference-region trigger --reference-region receiver `
    --output-dir E:/BBB_Evac/Saved/temp/明确任务/正式双手视觉检查
```

`--side` 支持 `left`、`right`、`both`。左右手独立输出 `left_three_views.png`、`right_three_views.png`；`--palm` 显示灰蓝掌部，五指颜色与历史工具一致。需要排除机匣遮挡时，使用另一输出子目录去掉 `--reference-region receiver`，同时保留含机匣参考图用于检查食指。

增加 `--reverse-depth` 可反转三个投影各自的观察深度，输出 `left_reverse_three_views.png`、`right_reverse_three_views.png`。仍使用相同的 XZ / YZ / XY 轴、投影坐标和原三角面排序方法，只反转遮挡次序，帮助检查护木背后的指端及掌内面。正侧、反侧应分别指定输出子目录，保留各自来源报告；反侧同样没有逐像素深度缓冲，不能把排序产生的遮挡当作穿透结论。

输出必须在明确项目 `Saved/temp` 的任务子目录，项目根必须存在 `.uproject`。所有来源保护检查通过后才创建输出目录。缺一只手时 `both` 整体失败，不把另一只手图当作双手完成。

## 审阅与限制

`visual_review.json` 保存输入绝对路径、SHA256、实际资产、动画时间、recipe 验证指纹、实际挂接矩阵、每手覆盖数量和图片路径，状态始终为 `pending_visual_inspection`。**生成图片不代表握持已通过。** 执行代理必须打开每张图，详细回答是否符合真实握持、是否自然，按照报告中的检查清单逐项判断；发现异常需修正正式资产、重新采样、重新绘图。

图使用原生采样的顶点位置，不重新蒙皮、不覆盖候选旋转。武器按实际右手组件姿势、正式插槽上下文及已保存 SpawnOffset 依次挂接。视图围绕手部裁剪，武器远离手部的三角面不绘制，参考区域过大也不会改变手部缩放。

原绘制方法按三角面平均深度排序，没有逐像素深度缓冲；必须结合三个投影判断，不能将单图遮挡当成接触或无穿透证明。该采样是线性蒙皮，不含 Morph、布料、Mesh Deformer 和实际材质；报告明确记录这些不支持项及原生计数，不能冒充运行时最终观感验收。允许合理轻微武器穿模，禁止为了数值间隙让掌心或指端悬空。

## 来源保护测试

```powershell
& '<已安装NumPy和Pillow的Python>' -B -m unittest discover -s Tests -p test_grip_visual_review.py -v
```

测试覆盖候选覆盖拒绝、错误动画、跨武器区域、过期采样摘要、缺参考区域、左手不足、输出路径越界、未保存校准、过期骨骼姿势和反侧表面切换。真实样本验收还需使用正式原生 JSON 生成并打开图片，不能仅凭夹具测试通过交付。

### 2026-10-18 真实输入验证

- 七项来源保护及反侧表面测试通过。
- `R2Visual_HumanSavedNative.json` 与 `Rifle02_Weapon.json`：正式 Rifle02 右手绘制成功，2179 个手部三角面、200 个视域内握把三角面；同一旧输入请求左手明确失败，缺五指及掌部，没有创建假左手输出。
- `Rifle02_BothHandsSavedNative.json` 与同一武器采样：正式双手分别绘制成功，左手 2173 个手部三角面、132 个视域内护木三角面，右手 2179 个手部三角面、200 个视域内握把三角面。
- 本次区域输入分别来自本枪正式 recipe 的 `calibration.left_palm.weapon_triangle_ids` 和 `calibration.right_palm.weapon_triangle_ids`，使用实际武器采样字节摘要绑定，没有内置组件编号。输出位于项目 `Saved/temp/WeaponGrip14/NormalizedVisual_Rifle02/`。
- 已打开左右图片，确认左右独立、掌部及五指颜色可见。左手护木在部分投影遮挡指端，需由执行代理联合三个投影继续评估接触；工具交付状态仍为待视觉复核，不替代握持通过结论。

## 正式动作关键帧分支

新增参数 `--action-recipe` 与 `--action-index` 必须一起使用。`--recipe` 仍指向同型号正式握姿制作源，用于角色及武器网格、插槽上下文和已保存校准；动作分支不要求角色姿势等于静态握姿。动作源必须位于该项目 `Content` 内的正式 `Source/Animation/*.json.source`，其 `weapon` 和 `grip_fingerprint` 必须分别匹配握姿源型号及当前验证指纹。

动作源 `actions[明确序号].asset` 必须是本型号下的成品动作资产。角色原生采样的实际 `animation` 必须精确对应该资产，仍禁止 `localRotationOverrides`，不接受离线候选旋转或位置。挂接使用该关键帧真实 `hand_r` 组件姿势，不使用静态骨架姿势替换。

```powershell
& '<已安装NumPy和Pillow的Python>' -B E:/UE5.8/BBBUE-MCP-Tools/Scripts/BBBGripVisualReview.py `
    --project-root E:/BBB_Evac `
    --character E:/BBB_Evac/Saved/temp/明确任务/正式动作关键帧原生双手采样.json `
    --weapon E:/BBB_Evac/Saved/temp/明确任务/本枪原生采样.json `
    --recipe E:/BBB_Evac/Content/本枪/Source/Animation/正式握姿制作源.json.source `
    --action-recipe E:/BBB_Evac/Content/本枪/Source/Animation/正式动作制作源.json.source `
    --action-index 1 `
    --regions E:/BBB_Evac/Saved/temp/明确任务/本枪视觉区域.json `
    --side both --palm --reverse-depth `
    --reference-region receiver --reference-region bolt --reference-region magazine `
    --output-dir E:/BBB_Evac/Saved/temp/明确任务/换弹关键帧反侧检查
```

`--action-index` 从零开始。需要展示机匣、枪栓、弹匣等机构时，必须在该枪区域清单中独立声明相应 `receiver`、`bolt`、`magazine` 面片区域；没有内置机构猜测。

动作条目可选 `weapon_animation` 字符串，表示应使用的本型号武器动画。提供时，武器原生采样的实际 `animation` 必须精确匹配；未提供时，仍只接受无动画武器采样。每份武器采样都需要区域清单绑定其实际字节 SHA256，不允许沿用另一帧采样的摘要。

输出 `review_scope.mode=actual_action_as_original_finger_pose`，明确记录：**这是实际动作 AS 原始手指姿势，没有模拟运行时握姿曲线混合，不能冒称最终 runtime 画面。** 同时记录动作序号、种类、资产、角色和武器采样时间、武器是否使用静态参考。动作源路径与 SHA256 加入 `sources.action_recipe`。动作图仅用于审阅真实 AS 中段的手与机构关系，不能替代运行时动画图、握姿曲线混合和附件生命周期的最终验收。

新增来源防错测试覆盖动作资产精确匹配、跨武器与旧握姿指纹拒绝、负序号及越界、武器动画明确绑定、正式动作源路径，以及实际动作姿势可不同于静态握姿但不模拟运行时混合。

2026-10-18 动作分支来源保护测试加入后，共十三项测试通过；使用同一 Rifle02 正式双手输入重跑静态入口，左右 PNG 的 SHA256 与扩展前分别完全相同。动作分支真实关键帧采样仍需单独验收，夹具测试不替代实际动作看图。

### Rifle02 换弹关键帧真实输入验收

已使用 `Rifle02_ReloadSaved_Frame8.json`、`Frame29.json`、`Frame43.json`、`Frame56.json` 四份原生采样，经正式 `Rifle02_Action_Authoring.json.source` 的 `action-index=1` 校验通过，对应 `ANI_BBB_Rifle_02_CharacterReload_Grip`，采样时间分别约为 0.266667、0.966667、1.433333、1.866667 秒。每帧左右手正常及反侧共十六张图输出到 `Saved/temp/WeaponGrip14/Rifle02_ActionVisualReview/Frame{帧号}/{normal,reverse}/`，各目录均有独立 `visual_review.json`。

全部十六张已打开确认来源及绘制。当前测试区域输入只有左右握持区，第二十九帧左手远离护木，图中没有弹匣参考，因此不能验收取匣接触。原始动作右手拇指伸直抬起，与已接受的静态握姿不同；这正是没有模拟运行时握姿层混合的实际 AS 原始姿势，不能将其当作最终运行时姿态通过。武器使用无动画静态原生参考，不包含动态弹匣位置、脱离和挂接生命周期。需要机构验收时必须增加本枪明确参考区域，并提供实际动作所指定的武器动画采样或其他已核验的运行状态证据。

后续已根据该枪实际原生骨架增加机构区域：三角面三个顶点的主权重骨均等于 `Trigger_joint` 时进入 trigger（58 面），等于 `Root_joint` 时进入 receiver（2162 面），等于 `Magazine_joint` 时进入 magazine（140 面），等于 `Slide_joint` 时进入 bolt（72 面）。Root_joint 包括机匣、护木、握把、护圈等所有固定部分，不能冒称独立机匣分割。原生骨名、选择方式、面数及静态参考限制写入区域源的 `selection_basis`、`reference_limitations`，工具同时将这两项带入报告。

第 8、29、43 帧左手含机构参考的正常及反侧六张图已生成并打开，输出在 `Saved/temp/WeaponGrip14/Rifle02_ActionMechanismReview/Frame{帧号}/{normal,reverse}/`。第 29 帧虽能看到静态弹匣，但它仍是装上状态参考，不能证明实际取匣或插匣时的动态接触；主执行代理应按该限制决定是否补采明确武器动画。

### 真实武器动画采样

已使用 `Rifle02_WeaponReload_Frame8.json`、`Frame29.json`、`Frame43.json`，精确匹配正式动作条目指定的 `ANI_BBB_Rifle_02_Reload`，分别生成与实际角色同时间的左手机构参考正常及反侧图。输出为 `Saved/temp/WeaponGrip14/Rifle02_DynamicMechanismReview/Frame{帧号}/{normal,reverse}/`，六张均已打开。

每帧新建独立 `Rifle02_DynamicVisualRegions_Frame{帧号}.json`，绑定该帧武器原生 JSON 的实际字节 SHA256，机构区域重新依据实际命名骨权重取得；握持面同时验证静态与动态采样的面编号及三顶点拓扑完全相等。没有复用过期采样摘要。

动态武器分支要求角色与武器采样时间一致（误差不超过 0.0001 秒），避免同动画错误帧混入。元数据明确 `runtime_visibility_notifies_simulated=false`、`independent_hand_attachments_included=false`。目前共十四项测试通过。

Rifle02 的武器弹匣在 0.3333 至 1.2 秒由显示通知隐藏；0.82 至 1.2 秒的新弹匣为独立 hand_l 附件，本工具没有输入该附件。第 29 帧虽然原生武器动画仍可采出下移的 Magazine 几何，但它不能冒称运行时可见的新弹匣；本次视域内武器面数为零，不能将空手图认作实际新匣接触验收。该帧必须依赖真实附件网格、插槽和变换的独立来源证据继续审计。

## 独立手部静态附件与明确武器显隐

动作条目支持最小显式声明：

```json
{
    "attachments": [
        {
            "mesh": "/Game/明确型号/Mesh/实际静态弹匣",
            "bone": "hand_l",
            "local": ["此处必须替换成原生Notify完整精度的位置四元数缩放共十项数值"],
            "start": 0.82,
            "end": 1.2,
            "sample_sha256": "实际静态附件原生JSON字节SHA256",
            "source_note": "具体正式蒙太奇资产路径、Notify类及实例信息"
        }
    ],
    "hidden_weapon_regions": [
        {
            "region": "magazine",
            "start": 0.333333,
            "end": 1.2,
            "source_note": "具体正式蒙太奇资产路径、显示Notify类及实例信息"
        }
    ]
}
```

上例变换是占位说明，不能直接使用；必须替换成实际 Notify 的完整精度原生字段。两个窗口均采用 `start <= 实际动作采样时间 < end`，声明必须有非负有限起止时间及具体原生来源说明，不从武器名称或帧号推测。活动附件缺少原生采样时失败；窗口外只报告 inactive，不绘制。不允许同一动作重复声明同一附件网格或重复输入同一网格，避免来源歧义。

CLI 通过重复 `--attachment-sample <明确原生静态采样JSON>` 提供静态附件。每份输入必须是 `meshType=StaticMesh`、`source=RenderDataLOD0`、`space=mesh_component_centimeters`、`lod=0`、`readOnly=true`、`localRotationOverrides={}`，同时有实际 `vertices` / `triangles`。不要求、也不生成假骨架。资产必须精确匹配动作声明，原始文件字节 SHA256 必须与 `sample_sha256` 相同。

附件矩阵严格为 `实际角色挂接骨组件矩阵 @ 原生Notify局部变换`。真实静态三角面以中性灰加入原彩色三视图，保留原武器；附件不会替换武器网格。原生 RenderData 几何不包含材质 World Position Offset，报告明确记录该限制。

`hidden_weapon_regions` 只按本枪区域清单的实际面片编号排除武器几何，不排除独立手部附件；必须先通过该帧武器采样 SHA256 来源检查。未知区域、未知面片、缺原生来源说明均失败。工具只执行明确动作源所声明的窗口，不执行引擎 Notify，不模拟完整运行时可见性。

报告分开列出 `visible_weapon_triangle_count`、`visible_attachment_triangle_count`，并保存附件实际资产、挂接骨、本地与组件矩阵、窗口、active 状态、采样来源路径及摘要、总面数。`hidden_weapon_regions` 保存原生显示来源及实际排除面数。`review_scope.independent_hand_attachments_included` 仅在活动附件已实际加入时为 true；`explicit_weapon_region_visibility_applied` 标明是否排除了明确武器面。原始 AS 手指及未模拟运行时握姿曲线的说明仍然保留。

含独立附件的实际审阅应更新该任务 regions 的 `reference_limitations`，不要继续写“未包含新弹匣”这种已经失效的历史限制；应明确附件已按源字段加入、其余动画图与 Notify 生命周期仍未模拟。

新增附件及显隐来源测试后，共十九项测试通过：静态附件无假骨架的真实骨变换、窗口边界、缺样本、错资产、过期 SHA、候选覆盖、非原生来源、未知挂接骨及武器隐藏不删除独立附件。实际样本仍需主执行代理完成原生采集后看图核验。

### 实际独立新弹匣验收

实际 `Rifle02_NewMagazineNative.json` 已由原生 RenderDataLOD0 导出 162 顶点、140 面，字节 SHA256 为 `1281546c843db728dd2dc07bbc7543b1299adebe4365976ac5055505430c85b4`。正式动作源使用原生 Notify 全精度变换，窗口内第 29 帧独立新匣实际加入；旧武器 magazine 的 140 面被显式隐藏。左手视域内有独立附件 111 面，右手视域内 26 面，分别报告，未替换武器。

第 29 帧双手正常及反侧四张图、第 8 和 43 帧左手各正常及反侧四张图均已生成并打开，路径为 `Saved/temp/WeaponGrip14/Rifle02_NewMagazineReview/Frame{帧号}/{normal,reverse}/`。第 8、43 帧同样输入附件原生样本，但均正确记录 inactive、不绘制附件；各帧 regions 的旧“未包含新匣”限制文字已更新为真实附件来源状态。

第一次实际新匣看图结论为需要调整，不能通过：第 29 帧匣体斜向偏向食指、中指，无名指及小指末端缺少稳定包握，掌内侧仅边缘局部接触。拇指与四指本身没有明显反关节或不连续上下折，但附件和它们的相对方向不利于共同包握。只读最近面查询辅助核实视觉疑点：无名指末节实际顶点离匣体最近约 1.461 厘米，小指末节最近约 0.693 厘米；这些是顶点距离诊断，不冒称完整三角面接触或自动自然度结论。应先由主执行代理修正正式新匣挂接变换，使匣体进入掌内侧与下三指共同包围的体积，再重新采集正式来源看图。此次没有修改正式动作源或 Notify。

主执行代理随后正式修改并保存 Native Notify、LS 和动作源，将弹匣宽面转入手部 C 形包握平面，再平移贴掌。最终 `Rifle02_NewMagazineReview_PalmFinal/Frame29/` 正反侧已由审阅代理打开，当前单帧实际握匣范围判为 `agent_visual_pass`，独立记录在 `visual_findings.json`，不登记为人工 accept。掌内不再整体分离，拇指与环小明确相对夹持，指列和弯曲连续；中指根部贴合而末节较放松，食指末端较放松，不声称全部指端紧贴。该通过只覆盖当前原始动作手部与真实附件的握持几何，不涵盖插入轨迹、运行时曲线混合、完整 Notify 生命周期或角色最终观感。

## 武器蒙太奇源时间

正式动作源可记录从实际武器蒙太奇片段回读的 `weapon_animation_play_rate`。当前支持从零开始、无循环的单段武器动画：原生武器采样时间必须等于角色动作秒数乘该有限正倍率，误差不超过 `0.0001` 秒；未指定时倍率为一。报告记录实际倍率及双方源时间，拒绝任意指定的不同武器帧。非零片段偏移和循环片段尚不支持。

同一 StaticMesh 的旧匣和新匣允许声明不同挂接变换，但原生样本 SHA256 必须一致，且通知窗口不得重叠。实际时间按左闭右开窗口选择挂接，共用一份真正的 RenderDataLOD0 采样；报告分别记录活动状态与变换，不以更改静态匣方向掩盖动作问题。两项新增回归覆盖无缝换窗、实际变换选择、重叠与来源冲突拒绝。

## 当前动作验收边界

双管装填等同时存在两个相同 StaticMesh 的真实独立附件时，每条声明可提供实际原生 Notify 对象路径作为唯一 `instance_id`。只有同网格各条目均有不同且非空的实例标识、并使用同一原生网格 SHA256 时，时间窗口才允许重叠；报告保留两个实例和各自挂接变换，网格输入仍只需一份。缺少标识、重复标识、同网格来源冲突继续拒绝。两项必要回归覆盖合法双弹药、两个实际变换及缺失/重复标识拒绝，视觉工具共24项检查通过。

上文历史 `BroadFace` 宽面握匣只通过了当时单帧几何自检，后续插匣机构诊断已拒绝它作为最终动作基准。当前 Rifle02 最终方案保留原插入兼容的匣体方向，以真实动作指骨卷曲及已证机构平移完成包握与装匣，具体最终证据见 `BBBWeaponActionAuthoring.md`。后续制作必须同时核对取匣、携行、插入及回握，不能仅凭一张自然握匣图通过完整动作。

右腕快照与正式校准的角差比较，在双方已经通过有限数值与单位范数校验后，分别归一化再取四元数内积。保持 `0.02` 度门槛，避免原生 float32 同向四元数范数略低于一造成误报；五项 handling 回归包含此实际数值案例及错误方向继续拒绝。
