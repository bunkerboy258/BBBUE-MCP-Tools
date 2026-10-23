# 批量人物指骨异常检查与修复

## 2026-10-23 当前四指硬约束

用户再次指出第一节仍有长轴扭转，当前重建改为明确的最短摆动，不再通过横向坐标框对齐指根。先把实际骨长方向以无扭转摆动对齐共同前向，再重建指根旋转；指根绕长轴的附加扭转严格为0。指根仅允许俯视平面内的小幅摆动，`root_spread_degrees` 默认正负3度，允许配置范围0至5度；指根向掌心的卷曲归零，第二、第三节保留正向内卷。报告新增 `maximumRootAxialTwistDegrees` 和 `maximumRootSpreadDegrees`，检查方案摘要包含算法版本及展开限制。

重建轴逐帧读取动画实际子骨平移，避免把参考骨长方向与动画局部骨长方向混用；先去除原始指根展开，再提取掌心卷曲量，避免重复处理时因投影缩短而改变卷曲。保存回读另外计算实际指根相对中性基准的轴向扭转，超0.01度拒绝；继续检查非目标轨、元数据及重复求解稳定性。首个无扭转版本在重复求解检查中发现0.201度漂移，因此未作为成功验收，随后修正实际骨长与投影计算。

最终原生批次 `2191df32e20fb67a` 已实际保存该动画24骨、86采样。输入指根最大卷曲84.414度；保存回读的指根轴向扭转最大0.00001837度、卷曲最大0.00001550度、俯视展开最大0.478495度，重复求解最大差0.00002867度。其他骨轨、位移缩放及元数据保持。当前摘要 `56feb90c139045ba91636e31cf13d754af5a394788b94afb658b6502820e2258`；前台打开批次 `e82b5ddca030053f`，待用户播放复核。首轮与上版保存摘要均已被此结果替代。

用户拒绝首轮保留参考偏置的结果，要求激进清除错误旋转。当前人物四指修复使用 `geometry_chain=true`，不使用下面旧的宽容关节配置。左右手分别在掌空间建立共同前向和掌心方向；四指指根对齐共同前向，仅允许上述小幅俯视摆动；中末节相对卷曲限于0至120度。这是本工具参数，不是人体医学界限。完整重建每节旋转，清除侧弯、轴向扭转和反向弯曲，不保留原始错误偏置。拇指独立，本次不修改。

同一公共入口的 `profile` 示例：

```json
{
  "geometry_chain": true,
  "root_spread_degrees": 3,
  "mesh_path": "/Game/_Project/Characters/BBBC_UA/BasicOutfit/Meshes/SK_UA_BasicArms",
  "reference_animation": "/Game/_Project/Characters/BBBC_UA/Animation/UsedAnimation/rifle/MM_Rifle_Idle_Hipfire"
}
```

先 `inspect`，再把返回的 `planSignature` 作为 `expected_plan_signature`，逐资产 `signature` 作为 `expected_signatures`，用同一配置调用 `repair`。参考握姿只确定左右掌心方向；实际骨长、父骨和局部轴从网格骨架读取，不把四元数欧拉角当作生物屈曲方向。末节虚拟方向由参考骨架相邻骨长方向构建。变换含非单位缩放时拒绝。

上版曾在原生批次 `ee9c3d5f14862f39` 重建双手24骨、全部86个采样并保存。逐骨核对其他旋转、全部位移缩放和元数据保持，但用户继续指出第一节问题；旧摘要 `20497201ee9605d9562d54086e3a04b556863142be4fd8cde1231e812cf22c99` 已被本节最终结果替代。没有重新烘焙武器专属动作或修改LS人工层。

实现 `BBBFingerPlanarTools.py` 经现有入口热加载，无需重启编辑器。保留逐轨保存回读；不另选测试动画，不以约束数值代替用户观感验收。

## 首轮结果已被用户否决

用户明确指定 `/Game/_Project/Characters/BBBC_UA/Animation/UsedAnimation/shotgun/MM_Shotgun_Reload`。使用已有 MM_Rifle_Idle_Hipfire 首尾参考、实际参考骨架及保留固定偏置的24关节配置；只处理这一条动画，没有继续选择其他动画或生成视觉测试。

原生批次 `2bee996b8654fa4c` 曾写入11骨、634个采样，元数据保持，但用户在第67帧附近指出仍有侧折和反向翻折。该宽容规则已不用于当前四指修复。旧摘要 `ddf3075204b68f93d4e0857f9bf7d3a9ff86f24d66f6ff93d2d1ea214c469c67` 已由上面的硬约束结果替代；旧数值通过不代表视觉通过。

批次 `f9e3dc3b6014ca64` 已成功打开该动画的前台编辑器。唯一制作参数和这次修复证据保存在角色 `Source/Animation/MM_Shotgun_Reload_FingerRepair.json.source`。既有各武器LS及已烘焙专属动作未重建；通过当前样板后再安排制作链路的基准采纳与同步。

原生回读发现UE浮点四元数有微小模长误差，角距离计算现先单位化再比较，避免未修改骨轨被错误报告为旋转变化。未增加备份、兼容路径或临时资产。

## 早期宽容模式记录

2026-10-23 后续已在前台 UE5.8 注册入口并完成原生只读调用。曾抽样 UsedAnimation/shotgun/MM_Shotgun_Reload 与 OtherAnimation/BigLocomotionPackV05/M4A1/Reload/anim_m4a1_aim_reload，生成原生蒙皮原始/候选图，未写入任何动画。视觉发现固定参考偏置和共同展开应保留，因此补入下述规则；修订规则尚未做实际资产保存验收。用户随后明确由其指定下一条动画，处理烘焙后打开窗口，由用户报告效果；排队中的额外校准已取消，不继续自行挑选或批量修改资产。

当前八项离线边界检查通过，新增共同展开中心与离群指根修正。原生检查不代表最终人体自然度已验收。

### 当前人工验收流程

1. 等待用户提供明确动画资产路径。
2. 基于该人物和明确正确参考完成校准，保留特殊操作窗口；先确认修改范围。
3. 对指定动画处理并保存最终骨轨，保留元数据与非目标骨轨；使用实际回读结果。
4. 打开该动画的前台编辑窗口，由用户报告效果；根据反馈继续修正。
5. 不将当前候选参数直接套用到整库，不自行添加新的实测动画。

### 原生校准补充

`skeleton_neutral=true` 时读取实际参考骨架，利用指骨方向与掌面确定屈曲平面，参考握姿仅用于确定内弯符号；`preserve_reference_offsets` 默认 true，保留正确握姿里的固定关节偏置。`root_spread_limit_degrees` 显式给出展开允许范围，以参考握姿及掌面法线建立指根规则。生成的 `center_root_spread=true` 按同手四个指根的中位展开角建立逐帧共同中心，限制个别指根偏离，不把整手共同展开强行收回固定握姿。参数仍需在用户指定动作上复核，不视为通用人体界限。

检查返回 `planSignature`，修复时同时提供 `expected_plan_signature` 和逐资产 `expected_signatures`，防止检查后规则、例外或资产变化。MCP 校准调用的 asset_paths 需包含明确参考资产以声明操作范围，不能传空数组。最严重帧按异常程度排序选取，避免先选到时间靠前但问题较轻的帧。

2026-10-23 用户批准规则与实现，随后明确暂不重启共享编辑器。入口源码、算法、原生适配和原彩色三视图接入已完成；语法及独立算法边界检查通过。新入口尚未在当前编辑器注册，代表动画原生检查、实际保存回读及图像验收待工具集重新加载后完成。本轮没有修改人物动画，没有运行 PIE，不得把数学检查当成人体自然度或完整原生验收。

`Tests/test_finger_animation_math.py` 七项通过：正常与等价四元数保持、非零参考下离轴消除、镜像轴符号、展开修复保留屈曲、奇异姿态例外保留、连续区间允许域与重复修复不漂移、非法校准拒绝。五份 Python 模块语法解析通过。

## 唯一入口

`editor.process_animation_fingers(asset_paths, profile_json, action)`。

Python内部参数名为 profile_json，MCP 对外使用结构化对象字段 `profile`，由现有契约自动编码。调用时无需手动转义 JSON 字符串。

- `calibrate`：明确中性及卷曲绝对参考，生成四指第二、三节候选轴；指根展开轴必须显式提供，参考差异不足的关节列入 unresolved，不猜测轴。输出配置须人工检查。拇指独立显式配置。
- `inspect`：批量读取原生局部骨轨，输出异常连续区间、最严重帧、源骨轨 signature、候选修复和时间步长峰值，不写动画。
- `repair`：使用同一配置、`reference_reviewed=true`、空 unresolved 和检查阶段返回的逐资产 `expected_signatures`。预检整批后，只写指定指骨旋转，原生逐轨回读，复核异常消除和元数据，再保存。

目录仅处理明确列出的绝对 AnimSequence，最多128个，不递归修改引用者。加法动画和涉及目标指骨的变换修正曲线拒绝单独修复；需要先提供明确合成结果。修复受现有资产写入策略约束，不覆盖第三方原资产。

## 校准格式

传入 `profile_json` 的对象示例：

```json
{
  "neutral_animation": "/Game/明确的中性参考",
  "curled_animation": "/Game/明确的卷曲参考",
  "minimum_calibration_degrees": 10,
  "hinge_limits_degrees": [0, 120],
  "tolerance_degrees": 3,
  "overrides": {}
}
```

以上角度仅演示接口，不是人体通用医学界限或本人物已确认参数。两参考之间的旋转向量作为候选屈曲轴，不代表它已经经过解剖校准；参考中混有侧弯时必须用 overrides 更正。输出 `referenceReviewRequired=true`。必须逐骨确认参考姿态、轴方向与允许范围。

## 检查与修复格式

```json
{
  "skeleton": "/Game/明确骨架.明确骨架",
  "rules": {
    "index_02_l": {
      "kind": "hinge",
      "neutral": [0, 0, 0, 1],
      "axis": [0, 0, -1],
      "limits_degrees": [0, 120],
      "tolerance_degrees": 3,
      "maximum_step_degrees": 25
    }
  },
  "reference_reviewed": false,
  "unresolved": [],
  "exceptions": {},
  "expected_signatures": {}
}
```

这是单骨格式示例，不能直接当成实际人物校准。`neutral` 为该骨实际正常参考局部 XYZW 四元数；`axis` 在参考骨坐标中定义，使用 `neutral * delta` 重建局部旋转。

`hinge` 处理第二、三节：分解校准轴屈曲和离轴残差，保留合法屈曲并约束过伸，移除异常样本的侧折与扭转。原先合格的样本不改，允许松开回到伸直。

`spread` 处理第一节：轴是掌面法线转换到参考指根坐标的方向，限制绕展开轴的有符号角，保留其余旋转。每根指根以自己的正确参考定义自然扇形，不统一所有指根角度；不能直接把末端指向当作指根展开角。

例外格式为 `exceptions[动画包路径][骨名]=[[起始帧,结束帧]]`，闭区间，保留特殊食指操作、钩拉等动作。全部帧号使用原始动画采样帧，非 Sequencer 显示帧。`expected_signatures[动画包路径]` 使用 inspect 返回的 signature；动画改变后必须重新检查。改规则后也应重新检查，不能沿用旧图作审核。

异常区间内对合法轴角进行四次局部平滑，所有结果仍约束在允许域内。报告修前修后最大相邻采样旋转角；若修复超过显式 maximum_step_degrees 且比原轨更恶化，则拒绝并要求时间连续性复核。此边界检查不等于已重建动作意图或修好全部原有抖动。

## 视觉

配置可加入：

```json
{
  "visual": {
    "mesh_path": "/Game/明确人物网格",
    "python_executable": "C:/Users/silencgai/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe",
    "maximum_frames": 2
  }
}
```

在异常最严重的采样时刻，分别原生采样原姿势和候选指骨旋转，再复用 BBBGripVisualReview 的 hand_triangles/render 绘制双手彩色三视图。保留输出 candidateOnly=true 和 visualAcceptance=pending，不冒称已保存结果或人工通过；本工具不包含武器接触验收。maximum_frames为每资产1至4帧，优先选各骨最严重帧，具体覆盖在结果中列明。

图片位于 `Saved/temp/FingerAnimation_<唯一编号>`，采样 JSON 使用后删除。阅图验收后删除该次任务目录。绘图 Python 需 NumPy/Pillow；不用编辑器内安装依赖。

## 保存边界

修复前拒绝 PIE、目标脏包、骨架或采样数不匹配和过期检查。保持全部非目标骨轨、目标骨的位移与缩放，以及采样率、时长、曲线、通知、同步标记和参考设置；不生成动画副本、历史兼容或曲线备份资产。全批预检后按资产顺序保存，不承诺跨资产事务回滚，失败后先核对已保存结果再继续。

只处理绝对动画骨轨，返回 sequenceLayersChecked=false。Sequencer 的无键默认偏移和有键人工层不会自动清零，需要在制作侧独立核对最终求值。

实现文件：BBBFingerAnimationMath.py、BBBFingerAnimationTools.py、BBBFingerAnimationReview.py；现有 BBBGenericEditorToolset 注册入口，MCP scope 限定 asset_paths。
