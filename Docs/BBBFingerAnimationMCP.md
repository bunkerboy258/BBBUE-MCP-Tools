# 批量人物指骨异常检查与修复

## 2026-10-24 FAL 修复已按用户要求撤销

用户取消FAL的全部9条角色动画手指修复。装备、换弹与后坐力从未修改的正式LS读取原旋转；两套握姿从human_manual_edit制作源的finger_rotations恢复；近战与使用返回两对成品从正式动作源保存的完整逐帧组件姿势还原局部旋转。只恢复本轮改动指骨的旋转，全部其他骨轨、位移缩放、帧数、曲线、通知及加法设置保持。源姿势恢复存在浮点运算，不宣称所有包与旧二进制逐字节一致。换弹恢复后的原始骨轨签名与修复前完全一致。

公共入口支持明确恢复来源，不执行方向约束算法：profile.restore_sequences将目标包映射到sequence及可选bones；profile.restore_records将目标映射到同型号Source/Animation下的source_record，动作组件快照另需sample_asset。仍先inspect获取planSignature与逐目标signature，再按expected_plan_signature和expected_signatures调用repair。绑定通过实际同骨架角色模板和Guid文本核对；官方烘焙只在瞬态副本执行，按成品采样率并保持末帧有效范围，正式LS不写入。正式输出只替换指定指骨旋转并验证非目标轨及元数据，再保存。

恢复实现BBBFingerSequenceRestore.py由现有入口热加载。LS恢复批次2d25988aeed758d5、制作记录恢复批次4fd6b840437835b1均保存回读通过；九条成品最终全轨核对通过。本轮新增FAL_FingerRepair.json.source已删除，不保留这次已取消修复的生效记录。恢复不等于再次通过人体自然度验收；已确认人工握姿不应套用指根归零规则。

## 四指逐节单轴屈曲

`editor.process_animation_fingers` 的 `geometry_chain` 模式逐帧处理左右手的食指、中指、无名指和小指，共 24 根指骨。指根、中节和末节使用同一约束。掌心方向由指定握姿的第 0 帧确定，指骨的零屈曲方向和局部屈曲轴由实际蒙皮网格的绑定父链计算。每节将源动画的指骨方向投影到屈曲平面，重建只含 0～120 度向内屈曲的旋转。反向屈曲回到中性，轴向扭转和侧摆归零。含 `root_spread_degrees` 的旧配置须去掉该字段。

`profile` 示例：

```json
{
  "geometry_chain": true,
  "mesh_path": "/Game/_Project/Characters/BBBC_UA/BasicOutfit/Meshes/SK_UA_BasicArms",
  "reference_animation": "/Game/_Project/Characters/Animation/UsedAnimation/Continuous/Idle/MM_Rifle_Idle_Hipfire"
}
```

先用 `inspect` 取得 `planSignature` 和逐资产 `signature`，再使用同一配置调用 `repair`，传入 `expected_plan_signature` 及 `expected_signatures`。只写四指的旋转。原始位移、缩放、拇指、腕部、帧数、曲线与通知均保留。实际网格 RAW 求值与源骨轨旋转必须一致，保存前通过 `readbackHinges` 复核各指节的离轴和反向旋转，保留阈值为浮点回读容差 0.01 度。实现位于 `Scripts/BBBFingerPlanarTools.py`。人工握姿仍应单独处理。

UE 5.9 在 `AS_SG550_Reload_Fingers_Repaired` 对照副本上逐帧烘焙并回读 265 个采样。全指节最大离轴残差约 0.000032 度，最大反向屈曲残差约 0.000015 度，指根最大向内屈曲约 82.05 度。观感由用户在动画编辑器播放对照。

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
