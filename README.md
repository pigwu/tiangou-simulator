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
- 三种可对比运行方式：聊天记忆、纯 LoRA、LoRA + 聊天记忆混合模式；后两者只有在适配器权重、训练凭证和 Ollama 角色标签都存在时才允许进入聊天。
- 训练数据、头像偏好和模型默认不离开本机。
- 支持多个本地“关系项目”：聊天源数据、双方角色、检索记忆、训练集、适配器、评测与日志按项目隔离，切换项目不会覆盖上一段关系。

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

脚本兼容 Windows PowerShell 5.1 与 PowerShell 7。启动成功后会自动打开浏览器；请保持 PowerShell 窗口运行，按 `Ctrl+C` 可停止本地服务。如启动失败，请查看项目目录中的 `local-backend-error.log` 和 `local-frontend-error.log`。

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

## Windows 微信 4.x 导出 CSV

本项目不内置微信解密代码，也不会上传微信数据库、密钥或导出的聊天。请只处理你本人有权使用的数据，先在微信桌面端通过“迁移与备份 → 备份与恢复”保留可恢复副本。第三方工具可能随微信更新失效，使用前请自行检查其源码、许可证和最新 Issue。

截至 2026-08-13，Windows 微信 4.x 最直接的 CSV 路径是第三方项目 [Ray0612/WeChat-Export-Tool](https://github.com/Ray0612/WeChat-Export-Tool)。其 v1.2.0 公开说明支持微信 4.x 以及 CSV、Excel、HTML、PDF、TXT、JSON；本模拟器只读取其中的文字。

### 从 GitHub 下载并导出

1. 打开 [WeChat-Export-Tool Releases](https://github.com/Ray0612/WeChat-Export-Tool/releases)，下载 `WXexport-tool-v1.2.0.zip` 并完整解压。不要直接在压缩包预览中运行。
2. 双击解压目录中的 `启动工具.bat` 或 `WeChatExport.exe`，设置一个独立工作目录，例如桌面的 `wx_export`。
3. 设置微信数据库位置。微信 4.x 不应继续选择旧版常见的 `Documents\WeChat Files`；请选择真正包含 `db_storage` 的微信 4.x 数据根目录。
4. 在微信已经登录的同一个 Windows 用户会话中点击“获取密钥”，工具提示关闭微信时再完全退出微信，等待状态变为成功。不要把密钥发给任何人，也不要写进 Issue、截图或本仓库。
5. 点击“连接数据库”。成功后再点击“浏览会话”，选择一位联系人和所需时间范围。
6. 导出格式选择 CSV，输出目录选择第 2 步的工作目录。导出文件通常类似 `联系人_20260813_091357.csv`。
7. 回到舔狗模拟器，在“聊天记录”页面上传该 CSV；确认哪一个“发送者”是舔狗、哪一个是被舔者，再生成对应方向的角色记忆。

导出目录可以在 PowerShell 中打开：

```powershell
explorer "$env:USERPROFILE\Desktop\wx_export"
```

该工具不同导出配置可能产生中英文表头，本项目均支持：

```csv
时间,发送者,消息内容,类型
2026-08-13 09:00:00,甲,在吗,文本
2026-08-13 09:01:00,乙,在,文本
```

```csv
timestamp,sender,content,type
2026-08-13 09:00:00,甲,在吗,文字
2026-08-13 09:01:00,乙,在,文字
```

本项目已直接兼容这些表头；若存在 `type/类型` 列，只有 `文字/文本/text/1` 等文字类型会进入角色样本，`ZSTD` 等非文字占位会被过滤。

### 如何确认选中了正确的微信 4.x 数据目录

正确根目录下面至少应能找到类似文件：

```text
db_storage\session\session.db
db_storage\message\message_0.db
db_storage\contact\contact.db
```

例如本次实际排障中，旧目录 `C:\Users\<用户名>\Documents\WeChat Files` 是错误目标，正确目标是 `D:\xwechat_files`。每台电脑的盘符和目录名可能不同，请以“下面存在 `db_storage` 和上述数据库”为准，不要照抄示例盘符。

不读取数据库内容也能在 PowerShell 中检查目录结构：

```powershell
$WechatRoot = "D:\xwechat_files" # 改为你自己的候选目录
Test-Path "$WechatRoot\db_storage\session\session.db"
Test-Path "$WechatRoot\db_storage\message\message_0.db"
Test-Path "$WechatRoot\db_storage\contact\contact.db"
```

三项都返回 `True` 才说明该示例结构匹配。请勿在求助时公开密钥、数据库文件或聊天正文。

### “获取密钥失败”的处理顺序

- 先确认使用的是工具 README 明确支持的微信 4.x，而不是把旧版微信教程套在 4.x 上。
- 先登录微信，再点击工具的“获取密钥”；只有出现工具提示后才完整退出微信。
- 在任务管理器确认微信相关进程已经退出，然后等待工具状态更新；不要反复快速点击。
- 若状态已经是 `captured`，且工具显示已有完整密钥，就不要继续反复获取。此时“连接数据库”失败应优先检查数据目录，而不是怀疑密钥。
- 密钥只应保存在本机工具自己的工作区。不要把它复制到 README、聊天窗口、GitHub Issue 或日志附件中。

### 每次都显示 “WCDB 超时”

本次排障的根因是数据库目录选错，而不是密钥错误：工具仍指向微信 3.x 常见的旧目录，WCDB 找不到微信 4.x 的正确数据库。按以下顺序处理：

1. 查看密钥状态；若已经 `captured`，停止重复抓取。
2. 把“微信数据库位置”改为包含 `db_storage` 的 4.x 根目录，而不是导出工作目录，也不是旧的 `WeChat Files`。
3. 用上面的三个 `Test-Path` 命令确认 `session.db`、`message_0.db`、`contact.db` 存在。
4. 保存设置后重新点击“连接数据库”；成功标志是工具能列出会话数量，而不是只看密钥状态。
5. 仍超时时，完全退出导出器后重新打开，查看工作目录下的 `logs\*.log`。分享日志前删除密钥、账号、联系人和本机路径等敏感信息。

### WeChatMsg 与 WechatExporter 应该怎么选

- [LC044/WeChatMsg](https://github.com/LC044/WeChatMsg) 当前仓库明确写着“很久没有（也不会）更新了”。不建议把它作为当前微信 4.x Windows 的首选导出方案。
- [BlueMatthew/WechatExporter](https://github.com/BlueMatthew/WechatExporter) 读取的是**未设置备份密码的 iTunes/iPhone/iPad 本地备份**，不是当前 Windows 微信桌面数据库。它主要导出 Text、HTML、PDF，不直接提供本项目首选的 CSV。适合手上已有 iOS 本地备份的用户：使用 iTunes 做未加密备份 → 下载其 Windows Release → 运行 `WechatExport.exe` → 按界面选择备份并导出；若目标是本模拟器，仍需把 Text 整理成本文后面的标准 TXT/CSV 格式。
- [sjzar/chatlog](https://github.com/sjzar/chatlog) 已在 2025-10-20 移除代码并声明项目不再可用，因此不再作为本项目的操作建议。

第三方项目与本仓库互相独立；上述说明只是兼容指引，不代表本项目审计、担保或捆绑它们。

## QQ 与其他平台

优先使用客户端自身的“消息管理器/导出聊天记录”功能，并选择文本或网页格式。若只能获得 HTML，可先复制所需对话为纯文本，或整理为 CSV。由于不同 QQ 版本的导出格式差异很大，本项目不声称能直接读取其专有备份文件。

大量数据最省事的通用格式：

```text
[2025-03-16 22:18] 小周: 到家了吗？
[2025-03-16 22:26] 阿晚: 嗯
```

CSV 表头可使用 `sender,content,timestamp`；也支持 `发送人/发送者`、`内容/消息内容`、`时间` 等中文别名。JSON 例子：

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
| NVIDIA 8–12 GB 显存 | Qwen2.5 3B 或兼容的 7B | QLoRA；可尝试混合模式 | Windows 推荐 WSL2，原生环境视 bitsandbytes 版本而定 |
| NVIDIA 16 GB+ 显存 | Qwen2.5 7B / Qwen3 8B | QLoRA / 混合模式 | 数据少时 3B 往往已经足够 |

UI 内置的能力目录还包括 Gemma 3 4B、Llama 3.2 3B 和 Mistral 7B Instruct v0.3。中文基础推理默认优先推荐 Qwen；Mistral 的中文表现通常弱于 Qwen，但它是当前目录中为 Ollama 官方 Safetensors LoRA 直载路径单独标注的选项。目录只存模型 ID、资源预算、官方网址和命令，不存储权重。实际下载大小以对应模型页面为准。

为什么默认不强制微调：聊天记录常常不够多，直接微调容易记忆原句、过拟合并暴露隐私；检索最相似的历史片段再交给本地模型生成，对设备要求低，也更容易删除或更正某段记忆。

## 三种塑造方式与混合模式

| 方式 | 实际推理路径 | 擅长 | 局限 |
|---|---|---|---|
| 聊天记忆 | 基础 Ollama 模型 + 相似历史片段 | 记住关系事实和类似情境；低配置可用 | 新场景检索不到片段时，角色风格会变淡 |
| LoRA 微调 | 已注册的 LoRA 角色模型；不注入历史片段 | 检查模型是否在新场景保持句长、用词和语气 | 不适合精确记住具体经历；需要训练硬件 |
| 混合模式 | 已注册的 LoRA 角色模型 + 相似历史片段 | LoRA 负责表达风格，记忆负责事实和情境 | 配置最复杂；仍需防止过拟合和错误检索 |

三种方式现在是后端真正分开的路径，不只是 UI 名称不同。纯 LoRA 模式返回的 `memory_count` 必须为 0；混合模式会返回实际注入的记忆数量。切换玩家身份后仍要重新生成对应方向的数据，否则 LoRA 和记忆都会学错对话方。

聊天记忆现使用完全本地的混合排序：中文字符词组 TF-IDF、原词命中、记录新旧程度与 MMR 去重共同决定候选，不需要下载额外向量模型。聊天侧栏会展示本轮实际引用的记忆、相关度与入选原因，便于发现错误标签或错误检索。大段经历会先切成多个事件片段，不再只固定读取开头一段。若以后需要更强的同义句理解，可在此基础上选装本地 `bge-m3` 等向量模型，但不作为默认依赖。

经历自述没有逐轮“对方输入 → 目标角色回复”标签，因此只能选择聊天记忆。LoRA 和混合模式要求导入至少能形成一轮监督样本的双方聊天记录。

## 多人物项目与本地数据管理

首次使用新版 UI 时，先在顶部输入一个项目名，例如“大学那段关系”。每个项目都位于 `local_data/projects/<随机项目ID>/`，其中独立保存：

- 导入的文字记录或经历自述与双方标签；
- 舔狗/被舔者各自的训练集、验证集、测试集、角色配置和评测报告；
- LoRA 适配器、训练任务状态、checkpoint 与日志；
- 浏览器端按项目隔离的昵称、头像和聊天背景偏好。

旧版直接写在 `local_data/` 根目录的数据会显示为“原有项目”。它仍可聊天和训练，但为了避免误删历史数据，UI 不允许递归删除它。建议为今后的每段关系新建独立项目。

项目卡片显示源消息数量和本地磁盘占用。选择“导出项目 ZIP”会导出源数据、配置、报告和训练凭证，默认不包含可能很大的 `adapters/` 模型权重；因此 ZIP 本身仍可能含有私密聊天文字，只适合保存在可信设备。删除受管项目时必须完整输入项目名，且项目不能有正在运行的训练任务。删除会移除该项目目录，无法从本项目恢复；不会删除 Ollama 中已经注册的模型标签，也不会影响其他关系项目。

### 在 UI 中启用混合模式

1. 导入并确认双方聊天记录，正确映射舔狗和被舔者。
2. 选择本轮玩家身份；模型会训练成另一方。每个方向应分别训练和使用不同角色标签，避免覆盖，例如 `tiangou-dog:latest` 和 `tiangou-receiver:latest`。
3. 在“选择塑造方式”中选择“混合模式”。UI 会优先选中当前 Ollama 官方列出可直接加载 Safetensors LoRA 的架构；也可手动改选其他模型。
4. 输入最终要注册到 Ollama 的角色标签并选择训练轮数，点击“生成混合模式配置”。这一步只生成按角色隔离的数据、训练配置、可用时的 Modelfile 和命令，例如 `dog-dataset.jsonl`、`dog-training-config.json`、`Modelfile.dog`；**不会训练或下载模型**。
   - 数据会先去掉完全重复的消息和问答，并按消息时间间隔切成独立会话。
   - 最近的完整会话会留作验证集和测试集，不会把相邻消息随机拆到训练与测试两边。
   - 对应文件为 `dog-validation.jsonl`、`dog-test.jsonl`（被舔者方向同理）；会话太少时 UI 会明确显示没有可靠测试集。
5. 安装训练依赖后，可以复制 UI 显示的命令手工训练，也可以使用“本地训练任务”面板：
   - 面板先检查训练集路径、角色方向、基础模型、Python 依赖、PyTorch CUDA/MPS、显存与剩余磁盘；不通过时不会启动。
   - 完整输入“确认本地训练”后才会创建后台进程。首次训练可能由 Transformers 从 Hugging Face 下载你选择的基础模型；这仍然不会把模型加入仓库，但会占用本机磁盘。
   - UI 显示真实训练步骤、loss、最近日志和实际进度；同一时间只允许训练一个角色，训练期间也不能覆盖该角色的数据集。
   - 可以停止任务并保留已有 checkpoint。只有 checkpoint 能证明与当前数据 SHA-256 和基础模型匹配时，UI 才允许恢复，避免从旧角色或旧数据错误续训。
   - 关闭浏览器页面不会停止训练，但关闭 `start.ps1` 窗口、结束后端进程或关机可能中断训练。重新启动后，UI 会从磁盘读取任务、日志和 checkpoint 状态。
   - 完成后 `local_data/adapters/dog-lora/` 或 `receiver-lora/` 应包含适配器权重和 `training-result.json`。两种角色使用独立目录，不会互相覆盖。
6. 若 UI 给出 `ollama create` 命令，训练完成后再执行；若没有给出，说明所选架构不在 Ollama 当前官方 Safetensors `ADAPTER` 支持列表中，需要使用相应生态先合并/转换，再自行注册为第 2 步填写的 Ollama 标签。
7. 回到 UI 点击“检查角色模型并进入”。项目会同时验证训练配置标签、适配器权重、训练凭证和 Ollama 标签，缺少任一项都不会把基础模型冒充成混合模式。

### 进阶 LoRA 训练

```powershell
pip install -r requirements-train.txt
python -m backend.train_lora --model Qwen/Qwen2.5-3B-Instruct
```

推荐复制 UI 实际生成的命令，而不是照抄上面的示例模型。训练前先在 UI 生成 `local_data/dog-dataset.jsonl` / `receiver-dataset.jsonl` 和对应的 `dog-training-config.json` / `receiver-training-config.json`。手工执行命令或在 UI 中明确输入确认文字后，Transformers 才会从所选模型的 Hugging Face 页面下载权重并启动训练。LoRA 输出和任务日志都在 `local_data/`，均已被 Git 忽略。UI 中的用时是训练前区间估算；首次下载模型的时间不计入其中，任务启动后则显示训练器上报的真实步骤和 loss。

训练脚本完成后会额外写入 `training-result.json`，记录完成时间、基础模型、数据集 SHA-256、样本数、轮数、实际用时、完成步数和训练损失。存在验证集时会在每轮计算验证 loss、保留最佳 checkpoint 并启用早停，同时记录最佳验证 loss。它是本地可复核凭证，不代表模型质量已经达标，但能防止“只生成配置就假装训练完成”。UI 生成的目录会按模型角色分成 `dog-lora` 和 `receiver-lora`；手工调用脚本时若不传 `--output`，才使用脚本的通用默认目录。

训练完成后使用适配器有两条路：

1. 使用 Transformers/PEFT 加载 UI 所示 Hugging Face 基础模型，再通过 `PeftModel.from_pretrained(base_model, "local_data/adapters/dog-lora")`（或 `receiver-lora`）挂载对应角色适配器。
2. 使用 Ollama `Modelfile` 中的 `ADAPTER` 指令创建新本地标签。基础模型必须与训练时完全一致；不一致可能产生不可预测输出。根据截至 2026-08-13 的 [Ollama Modelfile 文档](https://docs.ollama.com/modelfile)，Safetensors Adapter 明确列出的架构是 Llama 2/3/3.1、Mistral/Mixtral、Gemma 1/2；没有列出 Qwen、Gemma 3 或 Llama 3.2。UI 只会对目录中明确标注为可直载的路径生成 `ollama create` 命令，其他模型不能因为 LoRA 训练成功就假定能直接注册。

基础版聊天 API 默认走 Ollama 标签；未真正完成 LoRA、生成训练凭证并注册新标签前，LoRA 与混合模式不会进入聊天。

### 如何验证混合模式真的生效

重新生成角色数据后，UI 会按完整会话自动保留一批不参与训练的测试对话。点击“运行本地对比”会用最多 3 个测试问题比较：

1. 基础模型：不带角色记忆；
2. 聊天记忆：基础模型 + 只来自训练部分的记忆；
3. LoRA：角色模型，不带记忆；
4. 混合模式：同一个角色模型 + 只来自训练部分的记忆。

LoRA 与混合模式只有在适配器、训练凭证、数据哈希、基础模型和 Ollama 角色标签全部通过检查时才会加入评测；否则会明确跳过。评测展示句长/标点等表层风格接近度、与真实留出回复的相似度、模式内部重复率、原句照抄风险和平均耗时，并把完整本地报告写入 `local_data/dog-evaluation.json` 或 `receiver-evaluation.json`。这些自动指标用于发现退化，不代表完整的语义或人物相似度，更不等于人的主观判断；最终仍建议匿名盲选。

检查点：

- LoRA 模式的响应元数据中 `method=lora` 且 `memory_count=0`；
- 混合模式中 `method=hybrid`，相关查询通常有 `memory_count>0`；
- 对应角色的 `local_data/dog-training-config.json` 或 `receiver-training-config.json` 中，基础模型、角色方向和标签与当前实验一致；
- 对应角色的 `local_data/adapters/dog-lora/training-result.json` 或 `receiver-lora/training-result.json` 数据集哈希和样本数可复核；
- `ollama list` 中存在相同角色标签；
- 在未见过的问题上，LoRA 相比基础模型仍稳定接近目标角色；混合模式在涉及历史事实时又优于纯 LoRA；
- 回复不能只是复述训练原句。最好进行匿名人工盲测，而不是只看单次感觉。

只有上述对照成立，才能说混合模式同时利用了风格适配和聊天记忆；文件存在只能证明流程执行过，不能单独证明泛化质量。

## 常见问题与本次排障结论

### 运行 `.\scripts\start.ps1` 后打不开界面

请先在项目根目录运行脚本，而不是在 `scripts` 目录或其他目录运行：

```powershell
cd "C:\Users\<用户名>\Documents\ChatGPT\舔狗模拟器"
.\scripts\start.ps1
```

当前启动器已兼容 Windows PowerShell 5.1、中文路径和 IPv4 本地地址，并会等待前后端健康检查通过后再打开浏览器。仍打不开时：

```powershell
# 仅当当前 PowerShell 会话提示“禁止运行脚本”时使用
Set-ExecutionPolicy -Scope Process Bypass
.\scripts\start.ps1

# 检查服务是否已经启动
Invoke-RestMethod http://127.0.0.1:8000/api/health
Start-Process http://127.0.0.1:3000
```

若失败，查看项目根目录的 `local-backend-error.log`、`local-frontend-error.log`、`local-backend.log` 和 `local-frontend.log`。不要只截取 PowerShell 最后一行；错误日志前后 30 行更有用。

### “聊天记忆”为什么只说同一句话

先看页面右上角状态。只有显示“本地模型已连接”时，回复才真正经过 Ollama 和已生成的角色记忆；“后端已连接 · Ollama 未连接”表示 UI/后端虽然在线，但本机模型不可用。旧版本在这种情况下会静默返回固定演示句，造成“记忆只会一句话”的错觉；当前版本会明确标出“未使用聊天记忆”，并且已加入多轮上下文和重复回复重试。

`start.ps1` 不会自动安装 Ollama，也不会下载模型。Windows 上的检查与修复：

```powershell
# 安装 Ollama 后，重新打开 PowerShell
ollama --version

# 下载与 UI 选择相同的模型；二选一即可
ollama pull qwen2.5:1.5b  # 低磁盘占用，约 1 GB
ollama pull qwen2.5:3b    # 默认均衡，约 2 GB

# 确认模型存在、服务可访问
ollama list
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

随后关闭旧的模拟器 PowerShell 窗口，重新运行 `.\scripts\start.ps1` 并刷新页面。若 UI 选择的是 `qwen2.5:3b`，本地却只下载了 `qwen2.5:1.5b`，仍会提示模型不存在；选择项和 `ollama list` 中的标签必须一致。模型权重不会进入 Git 仓库，但本地生成回复必须至少下载一个模型。

### 显示“Ollama 调用失败”

先直接检查 Ollama，不要急着重新下载模型：

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

- 无法连接：启动 Ollama，再运行 `ollama list`。
- 能返回模型列表：确认 UI 选择的标签确实在列表中；当前 UI 会优先选择已经下载的标签，并在模型详情中显示“✓ Ollama 已安装”。
- Ollama 接口正常、模拟器仍失败：完全关闭旧的 `start.ps1` PowerShell 窗口后重新启动。旧后端进程不会自动加载刚更新的 Python 源码。

Windows 的“系统代理”可能存在于系统设置中，即使 PowerShell 没有 `HTTP_PROXY` 环境变量，Python HTTP 客户端仍可能让 `127.0.0.1:11434` 经过代理，表现为 Ollama 自己能生成、模拟器却调用失败。当前后端已将所有 Ollama 请求固定为本机直连，不再继承系统代理；必须重启后端才会生效。新版也会显示 Ollama 的实际 HTTP 状态和错误详情，不再统一隐藏成一句“调用失败”。

### CSV 能导入，但角色语气不对

- 在“确认对话双方”里按 CSV 的“发送者”值映射双方，不要按头像或备注名猜测。
- 玩家选择“我是被舔者”时，模型角色是舔狗；玩家选择“我是舔狗”时，模型角色是被舔者。
- 每次切换玩家身份或修正双方标签后，必须重新点击“生成角色记忆”，否则本地保存的样本方向仍是上一次的角色。
- 先确认导入条数和说话人数量合理。若只有一名发送者，通常是 CSV 表头不匹配、导出范围不完整或对方消息未被导出。

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

- [Ray0612/WeChat-Export-Tool](https://github.com/Ray0612/WeChat-Export-Tool)：Windows 微信 4.x 本地数据库与 CSV 导出兼容指引。
- [LC044/WeChatMsg](https://github.com/LC044/WeChatMsg)：历史上的微信聊天记录提取与可视化生态；当前仓库声明不再更新。
- [BlueMatthew/WechatExporter](https://github.com/BlueMatthew/WechatExporter)：通过未加密 iTunes/iOS 本地备份导出的参考方案。
- [sjzar/chatlog](https://github.com/sjzar/chatlog)：历史参考；代码已移除，当前不可用。
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
