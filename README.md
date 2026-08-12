# 舔狗模拟器

一个隐私优先的本地角色聊天实验室：导入微信、QQ 等社交平台的文字聊天记录，或写下自己舔他人/被舔的经历；明确标记“舔狗”和“被舔者”后，用本地模型模拟双方的聊天风格。

> 这是对关系模式的虚构模拟，不是真实人物复活工具。请只处理你有权使用的数据，涉及他人聊天记录前应取得同意。

## 已实现

- 本地 UI 导入 TXT、CSV、TSV、JSON，自动识别多个说话人。
- 双重标签设计：原始昵称映射到“舔狗/被舔者”，玩家再选择自己本轮扮演谁。
- 两套样本生成方向。模型扮演舔狗时只把舔狗消息标为 `assistant`；扮演被舔者时反过来，避免双方语气串位。
- 支持大段经历自述。自述被明确保存为“非逐字关系背景”，不会伪造成对话监督样本。
- 玩家扮演舔狗：玩家先发消息，被舔者可随机沉默，达到最大沉默数后再回复。
- 玩家扮演被舔者：舔狗主动发消息；玩家不回复时按设定的等待时间追发，达到最大条数即停止。
- 双方昵称、头像、经典/暖纸/深夜/自定义聊天背景可配置，并保存在浏览器本地。
- 默认“聊天记忆 + Ollama”路径兼容 Windows、macOS、Linux 和纯 CPU；另有进阶 QLoRA 脚本。
- 训练数据、头像偏好和模型默认不离开本机。

## 5 分钟启动

### 1. 准备环境

- [Node.js 22 LTS](https://nodejs.org/)
- Python 3.11 或 3.12（Python 3.13 可运行基础后端，但深度学习包的兼容性通常落后）
- [Ollama](https://ollama.com/)

仓库不包含、安装过程也不会自动下载任何模型。确认磁盘空间与模型许可证后，由你主动下载默认中文模型：

```bash
ollama pull qwen2.5:3b
```

### 2. 一键启动

Windows PowerShell：

```powershell
.\scripts\start.ps1
```

macOS / Linux：

```bash
chmod +x scripts/start.sh
./scripts/start.sh
```

打开 <http://127.0.0.1:3000>。本地 API 文档位于 <http://127.0.0.1:8000/docs>。

也可以分开启动：

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn backend.main:app --reload
npm install
npm run dev
```

## 如何便捷获取大量聊天记录

本项目**不绕过微信/QQ 加密，也不直接读取正在使用的客户端数据库**。推荐流程是“官方备份留底 → 用户自主导出 → 在本地清洗”：

### 微信

1. 先在微信桌面端使用“迁移与备份 → 备份与恢复”，保存可恢复的原始副本。
2. 需要结构化文字时，可评估 [sjzar/chatlog](https://github.com/sjzar/chatlog)、[LC044/WeChatMsg](https://github.com/LC044/WeChatMsg) 或 [BlueMatthew/WechatExporter](https://github.com/BlueMatthew/WechatExporter)。这些是独立第三方项目，请自行核对系统支持、许可证与风险。
3. 只导出目标的一对一聊天，转换为下述任一格式，再从本 UI 导入。

### QQ 与其他平台

优先使用客户端自身的“消息管理器/导出聊天记录”功能，并选择文本或网页格式。若只能获得 HTML，可先复制所需对话为纯文本，或整理为 CSV。由于不同 QQ 版本的导出格式差异很大，本项目不声称能直接读取其专有备份文件。

大量数据最省事的通用格式：

```text
[2025-03-16 22:18] 小周: 到家了吗？
[2025-03-16 22:26] 阿晚: 嗯
```

CSV 表头可使用 `sender,content,timestamp`，也支持 `发送人,内容,时间`。JSON 例子：

```json
[
  {"sender": "小周", "content": "到家了吗？", "timestamp": "2025-03-16 22:18"},
  {"sender": "阿晚", "content": "嗯", "timestamp": "2025-03-16 22:26"}
]
```

导入时会过滤常见的撤回、拍一拍等系统提示，只处理文字。图片、语音、转账、位置不会进入训练集。

## 对话双方标签如何工作

```text
平台原始昵称 ──玩家确认──> 舔狗 / 被舔者
                                │
                       玩家选择本轮身份
                                │
             ┌──────────────────┴──────────────────┐
             │                                     │
       玩家 = 舔狗                           玩家 = 被舔者
       模型 = 被舔者                         模型 = 舔狗
       玩家必须先发                          模型主动发
       模型可沉默                            玩家可不回复
```

身份标签和展示信息相互独立：即使把昵称改成“小王”，训练中的角色仍由 `dog/receiver` 字段确定。重新切换玩家身份时应重新生成该方向的角色记忆，防止把错误的一方当成回答标签。

## 自述经历模式

粘贴大段文字并选择“故事中的我是舔狗还是被舔者”。建议包含：

- 双方如何认识、关系处于什么阶段；
- 哪一方更常主动，回复频率和长度；
- 典型事件、情绪转折和记得的原话；
- 你希望模拟器不要虚构的边界。

自述适合补足人物和关系背景，但不能可靠复刻说话风格。想提高语气相似度，仍建议再提供真实的、经授权的文字对话。

## 模型与硬件适配

| 设备 | 推荐模型 | 推荐方式 | 说明 |
|---|---|---|---|
| 8 GB 内存 / 纯 CPU | Qwen2.5 1.5B–3B 量化 | 聊天记忆 | 最广泛兼容，速度取决于 CPU |
| 16 GB 内存 / Apple Silicon | Qwen2.5 3B–7B | 聊天记忆；可尝试 MPS LoRA | 统一内存至少预留 8 GB |
| NVIDIA 8–12 GB 显存 | Qwen2.5 3B | QLoRA | Windows 推荐 WSL2，原生环境视 bitsandbytes 版本而定 |
| NVIDIA 16 GB+ 显存 | Qwen2.5 7B / Qwen3 8B | QLoRA | 数据少时 3B 往往已经足够 |

UI 内置的能力目录还包括 Gemma 3 4B 和 Llama 3.2 3B，分别适合多语言或英文经历；中文对话默认优先推荐 Qwen。目录只存模型 ID、资源预算、官方网址和命令，不存储权重。实际下载大小以对应模型页面为准。

为什么默认不强制微调：聊天记录常常不够多，直接微调容易记忆原句、过拟合并暴露隐私；检索最相似的历史片段再交给本地模型生成，对设备要求低，也更容易删除或更正某段记忆。

进阶 LoRA：

```bash
pip install -r requirements-train.txt
python -m backend.train_lora --model Qwen/Qwen2.5-3B-Instruct
```

训练前先在 UI 生成 `local_data/dataset.jsonl` 和 `local_data/training-config.json`。只有你亲自执行上述命令时，Transformers 才会从所选模型的 Hugging Face 页面下载权重并启动训练。LoRA 输出在 `local_data/adapters/`，均已被 Git 忽略。UI 中的用时是基于等效 token 数、模型参数量、训练轮数与检测到的显存作出的区间估算；首次下载模型的时间不计入其中。

训练完成后使用适配器有两条路：

1. 使用 Transformers/PEFT 加载 UI 所示 Hugging Face 基础模型，再通过 `PeftModel.from_pretrained(base_model, "local_data/adapters/role-lora")` 挂载适配器。
2. 使用支持 Safetensors LoRA 的 Ollama `Modelfile` 中的 `ADAPTER` 指令创建新本地标签。基础模型必须与训练时完全一致；不一致可能产生不可预测输出。详见 [Ollama Modelfile 文档](https://docs.ollama.com/modelfile)。

基础版聊天 API 默认走 Ollama 标签；未真正完成 LoRA 并注册新标签前，UI 的“用基础模型预览聊天”不会冒充已训练结果。

## 数据与安全边界

- `local_data/`、模型权重、头像与 `.env` 不会被 Git 提交。
- API 只监听 `127.0.0.1`，CORS 只允许本地开发页面。
- 建议导入前移除姓名、地址、电话、身份证号、账号、医疗与财务信息。
- “焦虑升级”只改变在意程度，提示词明确禁止威胁、辱骂、道德绑架和消息轰炸。
- 不要把模拟结果当作真实对方的态度或预测，也不要用它自动联系真实的人。

## 测试

```bash
python -m unittest discover -s tests -p "test_*.py"
npm run build
```

## 参考项目

- [sjzar/chatlog](https://github.com/sjzar/chatlog)：聊天数据导出与查询思路。
- [LC044/WeChatMsg](https://github.com/LC044/WeChatMsg)：微信聊天记录提取与可视化生态。
- [BlueMatthew/WechatExporter](https://github.com/BlueMatthew/WechatExporter)：跨平台微信记录导出参考。
- [hiyouga/LLaMA-Factory](https://github.com/hiyouga/LLaMA-Factory)：多模型高效微调与硬件适配参考。
- [open-webui/open-webui](https://github.com/open-webui/open-webui)：Ollama 本地聊天交互参考。

这些项目仅作为设计和兼容性调研参考，本仓库没有复制其源码，也不捆绑第三方导出工具。

## 路线图

- 后台训练任务、取消/恢复与显存诊断。
- HTML 导出适配器和导入前脱敏预览。
- 多轮会话保存、分支与导出。
- 将 LoRA 适配器合并/量化并自动注册到 Ollama。
- Tauri 桌面安装包。

## License

[MIT](LICENSE)
