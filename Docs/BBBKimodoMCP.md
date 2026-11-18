# Kimodo 动画生成 MCP

`BBBKimodoToolset` 将 UE 5.9 的 Kimodo 与 AnimGenOffline 生成流程接到编辑器 MCP。

## 工具

- `animation.prepare_kimodo_generation_batch`：按目标 SkeletalMesh、Animation/work 序列路径、Animation/Sequence 输出路径和 JSON 动作描述建立 LevelSequence Spawnable、Animation Mixer Track 与 Kimodo 生成区段。该工具只准备工程，不启动推理；不覆盖已存在的资产。路径数组在 UE Python 边界转换为普通列表，字段名按 UE 5.9 反射结果写入。
- `animation.inspect_kimodo_generation_batch`：读取异步区段准备进度、错误和输出路径。
- `animation.open_kimodo_generation_sequence`：在 Sequencer 打开批次内指定工作序列。

`jobs_json` 的每个动作项包含 `sequence_path`、`output_asset_path`、`start_frame`、`seed`、`prompt`。每段默认五秒，`start_frame` 使用 30 fps 显示帧且间隔五秒。

## 使用

1. 在 UE 5.9 启用 Kimodo 与 AnimGenOffline，并重启编辑器加载插件。
2. 在 Editor Preferences 的 Kimodo 设置里由用户本机保存 Hugging Face Token。令牌需要获得 `meta-llama/Meta-Llama-3-8B-Instruct` 的访问权限；Kimodo 设置留空时可使用 `HF_TOKEN` 环境变量或 Hugging Face 缓存。MCP 工具不读取或返回令牌，不能把令牌放进工具参数或聊天。
3. 设置模型为 GPU、Text Encoder Placement 为 CPU、Text Encoder Precision 为 4 bit (NF4)。
4. 调用 prepare 工具并轮询 inspect，直到 `status=ready`。首个工作序列会自动打开。
5. 在 Sequencer 按 `Ctrl+Alt+R` 运行 Generate All Animations。生成完成后使用 AnimGenOffline 的 Export All Animations 导出至各区段指定的正式路径。
6. 用 `open_kimodo_generation_sequence` 切换到批次中后续工作序列，重复生成与导出；最后通过资产工具回读 AnimSequence 类型、骨架和保存状态。

批次输入必须把每个序列与输出动画放在同一个武器型号目录，工作源放 `Animation/work`，正式序列放 `Animation/Sequence`。目标网格保持只读。生成结果是全身角色动作，不创建武器网格、物品配置或蒙太奇。

## 验收

本轮已通过 UE 5.9 编辑器核对工具发现、结构化参数、数组传递及反射字段，并成功准备六个生成区段。当前 GPU / CPU 编码器 / NF4 设置已回读；本机 Kimodo 令牌、`HF_TOKEN` 环境变量与 Hugging Face 缓存均为空，因此本轮尚未运行模型推理，也没有正式 AnimSequence 可回读。用户在编辑器本机保存有权限的令牌后，再按上述步骤生成、导出并回读六个结果。最终动作观感以编辑器生成结果为准。
