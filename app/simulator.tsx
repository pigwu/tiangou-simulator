"use client";
/* eslint-disable @next/next/no-img-element -- 用户本地 Data URL 头像无法交给图片优化器 */

import { ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";

type Step = "import" | "train" | "chat";
type Role = "dog" | "receiver";
type InputMode = "records" | "story";
type ChatMessage = { id: string; role: "me" | "model" | "notice"; text: string; time: string };
type ImportedMessage = { sender: string; content: string; timestamp?: string };
type ModelInfo = { id: string; name: string; ollama_tag: string; hf_id: string; quant_disk_gb: number; full_disk_gb: number; runtime_ram_gb: number; min_lora_vram_gb: number; chinese: string; note: string; memory_compatible: boolean; disk_compatible: boolean; lora_compatible: boolean; recommended: boolean; ollama_url: string; huggingface_url: string; ollama_command: string; lora_command: string };
type Hardware = { system: string; ram_gb: number; gpu_name: string; vram_gb: number; free_disk_gb: number; ollama_installed: boolean };
type Estimate = { min_minutes: number; max_minutes: number; disk_gb: number; peak_memory_gb: number; confidence: string; compatible: boolean; basis: string };

const API = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
const demoMessages: ImportedMessage[] = [
  { sender: "小周", content: "到家了吗？外面好像下雨了", timestamp: "22:18" },
  { sender: "阿晚", content: "嗯", timestamp: "22:26" },
  { sender: "小周", content: "那就好，记得把头发吹干", timestamp: "22:27" },
  { sender: "小周", content: "明天早上还要不要我带咖啡？", timestamp: "22:31" },
  { sender: "阿晚", content: "不用啦 明天不一定去", timestamp: "22:45" },
  { sender: "小周", content: "好，那你需要的时候叫我", timestamp: "22:46" },
];

function now() {
  return new Date().toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" });
}

export default function Simulator() {
  const [step, setStep] = useState<Step>("import");
  const [inputMode, setInputMode] = useState<InputMode>("records");
  const [messages, setMessages] = useState<ImportedMessage[]>([]);
  const [filename, setFilename] = useState("");
  const [narrative, setNarrative] = useState("");
  const [narratorRole, setNarratorRole] = useState<Role>("dog");
  const [dogSpeaker, setDogSpeaker] = useState("小周");
  const [receiverSpeaker, setReceiverSpeaker] = useState("阿晚");
  const [dogName, setDogName] = useState("小周");
  const [receiverName, setReceiverName] = useState("阿晚");
  const [dogAvatar, setDogAvatar] = useState("");
  const [receiverAvatar, setReceiverAvatar] = useState("");
  const [chatBackground, setChatBackground] = useState("classic");
  const [customBackground, setCustomBackground] = useState("");
  const [playerRole, setPlayerRole] = useState<Role>("receiver");
  const [model, setModel] = useState("qwen25-3b");
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [hardware, setHardware] = useState<Hardware | null>(null);
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [method, setMethod] = useState("memory");
  const [training, setTraining] = useState(false);
  const [trained, setTrained] = useState(false);
  const [progress, setProgress] = useState(0);
  const [allowSilence, setAllowSilence] = useState(true);
  const [maxIgnored, setMaxIgnored] = useState(3);
  const [waitSeconds, setWaitSeconds] = useState(15);
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [ignored, setIgnored] = useState(0);
  const [backend, setBackend] = useState<"checking" | "online" | "offline">("checking");
  const [appearanceReady, setAppearanceReady] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const silenceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastPlayerMessage = useRef("");
  const endRef = useRef<HTMLDivElement>(null);

  const speakers = useMemo(() => Array.from(new Set(messages.map((item) => item.sender))), [messages]);
  const modelRole: Role = playerRole === "dog" ? "receiver" : "dog";
  const roleName = (role: Role) => (role === "dog" ? "舔狗" : "被舔者");
  const importReady = inputMode === "records" ? messages.length > 0 && dogSpeaker !== receiverSpeaker : narrative.trim().length >= 30;
  const selectedModel = models.find((item) => item.id === model);

  useEffect(() => {
    fetch(`${API}/api/health`).then((r) => setBackend(r.ok ? "online" : "offline")).catch(() => setBackend("offline"));
    fetch(`${API}/api/system`).then((r) => r.ok ? r.json() : Promise.reject()).then((data) => {
      setHardware(data.hardware);
      setModels(data.models || []);
      const recommended = (data.models || []).find((item: ModelInfo) => item.recommended);
      if (recommended) setModel(recommended.id);
    }).catch(() => undefined);
    const restore = setTimeout(() => {
      try {
        const saved = JSON.parse(localStorage.getItem("tiangou-appearance") || "{}");
        if (saved.dogName) setDogName(saved.dogName);
        if (saved.receiverName) setReceiverName(saved.receiverName);
        if (saved.dogAvatar) setDogAvatar(saved.dogAvatar);
        if (saved.receiverAvatar) setReceiverAvatar(saved.receiverAvatar);
        if (saved.chatBackground) setChatBackground(saved.chatBackground);
        if (saved.customBackground) setCustomBackground(saved.customBackground);
      } catch { /* 浏览器存储不可用时仍可继续 */ }
      setAppearanceReady(true);
    }, 0);
    return () => clearTimeout(restore);
  }, []);

  useEffect(() => {
    if (!appearanceReady) return;
    try {
      localStorage.setItem("tiangou-appearance", JSON.stringify({ dogName, receiverName, dogAvatar, receiverAvatar, chatBackground, customBackground }));
    } catch { /* 图片过大时仅在当前会话保留 */ }
  }, [appearanceReady, dogName, receiverName, dogAvatar, receiverAvatar, chatBackground, customBackground]);

  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), [chat, busy]);

  useEffect(() => {
    if (step !== "chat" || playerRole !== "receiver" || busy || ignored >= maxIgnored) return;
    const delay = chat.length === 0 ? 1200 : waitSeconds * 1000;
    timer.current = setTimeout(() => void requestReply("（对方还没有回复。请主动发一条消息，语气随等待次数逐渐着急，但不要提及这是模拟器。）", true), delay);
    return () => { if (timer.current) clearTimeout(timer.current); };
  // requestReply 使用当前角色状态；计时器会在每次相关状态变化时重建。
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, playerRole, chat.length, ignored, maxIgnored, waitSeconds, busy]);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
    if (silenceTimer.current) clearTimeout(silenceTimer.current);
  }, []);

  useEffect(() => {
    if (step !== "train") return;
    const controller = new AbortController();
    fetch(`${API}/api/estimate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: model, method, message_count: messages.length, narrative_chars: narrative.length, epochs: 2 }),
      signal: controller.signal,
    }).then((r) => r.ok ? r.json() : Promise.reject()).then(setEstimate).catch(() => {
      setEstimate(method === "memory" ? { min_minutes: 1, max_minutes: 2, disk_gb: 0.1, peak_memory_gb: 1, confidence: "离线估算", compatible: true, basis: "本地整理与索引" } : null);
    });
    return () => controller.abort();
  }, [step, model, method, messages.length, narrative.length]);

  async function importFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setFilename(file.name);
    const body = new FormData();
    body.append("file", file);
    try {
      const response = await fetch(`${API}/api/import`, { method: "POST", body });
      if (!response.ok) throw new Error();
      const data = await response.json();
      setMessages(data.messages || []);
      const names = data.speakers || [];
      if (names[0]) setDogSpeaker(names[0]);
      if (names[1]) setReceiverSpeaker(names[1]);
      if (names[0]) setDogName(names[0]);
      if (names[1]) setReceiverName(names[1]);
      setBackend("online");
    } catch {
      const text = await file.text();
      const parsed = text.split(/\r?\n/).map((line) => {
        const match = line.match(/^(?:\[[^\]]+\]\s*)?([^:：]{1,30})[:：]\s*(.+)$/);
        return match ? { sender: match[1].trim(), content: match[2].trim() } : null;
      }).filter(Boolean) as ImportedMessage[];
      setMessages(parsed.length ? parsed : demoMessages);
      setBackend("offline");
    }
  }

  function useDemo() {
    setMessages(demoMessages);
    setFilename("演示聊天.txt");
    setDogSpeaker("小周");
    setReceiverSpeaker("阿晚");
    setDogName("小周");
    setReceiverName("阿晚");
  }

  async function importStoryFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    setFilename(file.name);
    setNarrative((await file.text()).slice(0, 200_000));
  }

  function readImage(event: ChangeEvent<HTMLInputElement>, setter: (value: string) => void) {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > 3 * 1024 * 1024) {
      alert("图片请控制在 3 MB 以内");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => setter(String(reader.result || ""));
    reader.readAsDataURL(file);
  }

  async function buildDataset() {
    setTraining(true);
    setProgress(12);
    try {
      const response = await fetch(`${API}/api/dataset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages,
          dog_speaker: dogSpeaker,
          receiver_speaker: receiverSpeaker,
          dog_name: dogName,
          receiver_name: receiverName,
          model_role: modelRole,
          narrative: inputMode === "story" ? narrative : "",
          narrator_role: narratorRole,
        }),
      });
      if (response.ok) setBackend("online");
    } catch { setBackend("offline"); }
    for (const value of [38, 64, 86, 100]) {
      await new Promise((resolve) => setTimeout(resolve, 240));
      setProgress(value);
    }
    setTraining(false);
    setTrained(true);
  }

  function enterChat() {
    setChat([]);
    setIgnored(0);
    setStep("chat");
  }

  async function requestReply(text: string, proactive = false) {
    setBusy(true);
    const nextIgnored = proactive ? ignored + 1 : ignored;
    try {
      const response = await fetch(`${API}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          model: selectedModel?.ollama_tag || "qwen2.5:3b",
          model_role: modelRole,
          player_role: playerRole,
          dog_speaker: dogSpeaker,
          receiver_speaker: receiverSpeaker,
          dog_name: dogName,
          receiver_name: receiverName,
          ignored_count: nextIgnored,
          max_ignored: maxIgnored,
        }),
      });
      if (!response.ok) throw new Error();
      const data = await response.json();
      setChat((items) => [...items, { id: crypto.randomUUID(), role: "model", text: data.reply, time: now() }]);
      setBackend("online");
    } catch {
      const fallback = modelRole === "dog"
        ? ["在忙吗？看到的话回我一下就好。", "我是不是打扰到你了……没事，你先忙。", "刚刚路过你说过的那家店，突然想到你了。"]
        : ["刚看到。", "今天有点忙，晚点再说吧。", "你不用一直等我消息的。"];
      setChat((items) => [...items, { id: crypto.randomUUID(), role: "model", text: fallback[Math.min(nextIgnored, fallback.length - 1)], time: now() }]);
    } finally {
      if (proactive) setIgnored(nextIgnored);
      if (!proactive && silenceTimer.current) {
        clearTimeout(silenceTimer.current);
        silenceTimer.current = null;
      }
      setBusy(false);
    }
  }

  async function send(event: FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    lastPlayerMessage.current = text;
    setChat((items) => [...items, { id: crypto.randomUUID(), role: "me", text, time: now() }]);
    if (playerRole === "receiver") {
      setIgnored(0);
      await requestReply(text);
      return;
    }
    const mustReply = ignored >= Math.max(0, maxIgnored - 1);
    const silent = allowSilence && !mustReply && Math.random() < 0.48;
    if (silent) {
      const count = ignored + 1;
      setIgnored(count);
      setChat((items) => [...items, { id: crypto.randomUUID(), role: "notice", text: `对方暂未回复 · ${count}/${maxIgnored}`, time: now() }]);
      if (!silenceTimer.current) {
        silenceTimer.current = setTimeout(() => void requestReply(lastPlayerMessage.current), waitSeconds * 1000);
      }
      return;
    }
    setIgnored(0);
    await requestReply(text);
  }

  return (
    <main className="shell">
      <header className="topbar">
        <button className="brand" onClick={() => setStep("import")} aria-label="返回首页">
          <span className="brand-mark">舔</span>
          <span><b>舔狗模拟器</b><small>LOCAL PERSONA LAB</small></span>
        </button>
        <div className="privacy"><i className={backend} /> {backend === "online" ? "本地服务已连接" : backend === "checking" ? "正在连接本地服务" : "演示模式 · 启动后端可训练"}</div>
      </header>

      <section className="hero">
        <div>
          <p className="eyebrow">把过去的消息，变成一场新的对话</p>
          <h1>这一次，换个身份<br />看看故事会怎么继续。</h1>
        </div>
        <p className="hero-note">聊天记录、训练数据与模型默认只停留在你的电脑。<br />不上传，不围观，也不替任何人做情感承诺。</p>
      </section>

      <nav className="steps" aria-label="项目步骤">
        {(["import", "train", "chat"] as Step[]).map((item, index) => (
          <button key={item} className={step === item ? "active" : ""} onClick={() => (item === "import" || messages.length) && setStep(item)}>
            <span>0{index + 1}</span>{item === "import" ? "整理聊天" : item === "train" ? "塑造角色" : "开始对话"}
          </button>
        ))}
      </nav>

      {step === "import" && (
        <section className="workspace import-grid">
          <div className="panel upload-panel">
            <div className="panel-head"><span>01</span><div><h2>提供你们的故事</h2><p>批量聊天记录或一段亲历自述，二选一即可</p></div></div>
            <div className="input-tabs"><button className={inputMode === "records" ? "active" : ""} onClick={() => setInputMode("records")}>聊天记录</button><button className={inputMode === "story" ? "active" : ""} onClick={() => setInputMode("story")}>经历自述</button></div>
            {inputMode === "records" ? <>
              <label className="dropzone">
                <input type="file" accept=".txt,.csv,.tsv,.json" onChange={importFile} />
                <span className="upload-icon">↥</span>
                <b>{filename || "把聊天记录拖到这里"}</b>
                <small>{messages.length ? `已识别 ${messages.length} 条消息` : "微信 / QQ / 其他平台 · 最大 50 MB"}</small>
              </label>
              <div className="import-actions"><button className="text-button" onClick={useDemo}>没有记录？使用演示数据</button><a href="#guide">如何批量获取记录 ↗</a></div>
              <div className="format-row"><span>TXT</span><span>CSV</span><span>JSON</span><em>自动忽略图片、转账与系统通知</em></div>
            </> : <>
              <textarea className="story-input" value={narrative} onChange={(e) => setNarrative(e.target.value)} placeholder="例如：我们在大学社团认识。那段时间总是我先找她……\n\n可以写关系背景、具体事件、谁更主动、对方平时如何回复，以及你记得的原话。" />
              <div className="story-tools"><label>故事中的“我”是<select value={narratorRole} onChange={(e) => setNarratorRole(e.target.value as Role)}><option value="dog">舔狗</option><option value="receiver">被舔者</option></select></label><label className="file-text">从 TXT 导入<input type="file" accept=".txt" onChange={importStoryFile} /></label></div>
              <div className="narrative-note">自述只作为关系背景与人物记忆，不会被伪装成逐句聊天训练数据。已输入 {narrative.length} 字。</div>
            </>}
          </div>

          <div className="panel label-panel">
            <div className="panel-head"><span>02</span><div><h2>确认对话双方</h2><p>身份与昵称分开标注，训练时不会串位</p></div></div>
            {inputMode === "records" && messages.length ? <div className="preview-list">{messages.slice(0, 4).map((message, index) => <div key={index} className={message.sender === dogSpeaker ? "line dog" : "line receiver"}><b>{message.sender}</b><p>{message.content}</p><small>{message.timestamp || ""}</small></div>)}</div> : inputMode === "story" && narrative ? <div className="story-preview">{narrative.slice(0, 340)}{narrative.length > 340 ? "…" : ""}</div> : <div className="empty-preview"><span>“</span><p>提供内容后，这里会展示片段<br />并让你确认谁是谁。</p></div>}
            {inputMode === "records" ? <div className="role-mapping">
              <label><span className="role-dot dog-dot" />舔狗<select value={dogSpeaker} onChange={(e) => { setDogSpeaker(e.target.value); setDogName(e.target.value); }}>{(speakers.length ? speakers : ["小周", "阿晚"]).map((name) => <option key={name}>{name}</option>)}</select></label>
              <span className="swap">⇄</span>
              <label><span className="role-dot receiver-dot" />被舔者<select value={receiverSpeaker} onChange={(e) => { setReceiverSpeaker(e.target.value); setReceiverName(e.target.value); }}>{(speakers.length ? speakers : ["阿晚", "小周"]).map((name) => <option key={name}>{name}</option>)}</select></label>
            </div> : <div className="story-names"><label>舔狗昵称<input value={dogName} onChange={(e) => setDogName(e.target.value)} /></label><label>被舔者昵称<input value={receiverName} onChange={(e) => setReceiverName(e.target.value)} /></label></div>}
            <button className="primary" disabled={!importReady} onClick={() => setStep("train")}>身份确认，下一步 <span>→</span></button>
          </div>
        </section>
      )}

      {step === "train" && (
        <><section className="workspace train-grid">
          <div className="panel role-choice">
            <div className="panel-head"><span>03</span><div><h2>这次，你想做谁？</h2><p>模型会扮演另一个人</p></div></div>
            <div className="choice-cards">
              <button className={playerRole === "dog" ? "selected" : ""} onClick={() => { setPlayerRole("dog"); setTrained(false); }}><i>汪</i><b>我是舔狗</b><small>你主动发消息<br />模型扮演被舔者</small></button>
              <button className={playerRole === "receiver" ? "selected" : ""} onClick={() => { setPlayerRole("receiver"); setTrained(false); }}><i>等</i><b>我是被舔者</b><small>模型会主动发消息<br />你决定回不回复</small></button>
            </div>
            <div className="rule-box">
              <div><span>模型身份</span><b>{roleName(modelRole)} · {modelRole === "dog" ? dogName : receiverName}</b></div>
              <div><span>{playerRole === "receiver" ? "最多主动追发" : "最多连续不回复"}</span><label><input type="number" min="1" max="9" value={maxIgnored} onChange={(e) => setMaxIgnored(Number(e.target.value))} /> 条</label></div>
              <div><span>{playerRole === "receiver" ? "每次等待" : "最长沉默"}</span><label><input type="number" min="5" max="3600" value={waitSeconds} onChange={(e) => setWaitSeconds(Number(e.target.value))} /> 秒</label></div>
              {playerRole === "dog" && <label className="toggle-row"><span><b>允许被舔者不回复</b><small>模拟已读或暂时沉默</small></span><input aria-label="允许被舔者不回复" type="checkbox" checked={allowSilence} onChange={(e) => setAllowSilence(e.target.checked)} /></label>}
            </div>
          </div>

          <div className="panel model-panel">
            <div className="panel-head"><span>04</span><div><h2>选择塑造方式</h2><p>已按设备能力提供安全默认值</p></div></div>
            {hardware && <div className="hardware-strip"><span><b>{hardware.system}</b>系统</span><span><b>{hardware.ram_gb} GB</b>内存</span><span><b>{hardware.gpu_name}</b>{hardware.vram_gb ? `${hardware.vram_gb} GB 显存/统一内存` : "CPU 推理"}</span><span><b>{hardware.free_disk_gb} GB</b>剩余磁盘</span></div>}
            <div className="method-tabs"><button className={method === "memory" ? "active" : ""} onClick={() => { setMethod("memory"); setTrained(false); }}>聊天记忆 <small>推荐</small></button><button className={method === "lora" ? "active" : ""} onClick={() => { setMethod("lora"); setTrained(false); }}>LoRA 微调 <small>进阶</small></button></div>
            <div className="model-select"><label>基础模型<select value={model} onChange={(e) => { setModel(e.target.value); setTrained(false); }}>{models.length ? models.map((item) => <option key={item.id} value={item.id}>{item.recommended ? "★ " : ""}{item.name} · 量化约 {item.quant_disk_gb} GB</option>) : <><option value="qwen25-15b">Qwen2.5 1.5B · 约 1 GB</option><option value="qwen25-3b">Qwen2.5 3B · 约 2 GB</option><option value="qwen25-7b">Qwen2.5 7B · 约 5 GB</option><option value="qwen3-8b">Qwen3 8B · 约 5.2 GB</option></>}</select></label><span className="fit">{selectedModel?.recommended ? "本机推荐" : selectedModel && (method === "lora" ? selectedModel.lora_compatible : selectedModel.memory_compatible) ? "本机可用" : selectedModel ? "配置可能不足" : "默认推荐"}</span></div>
            {selectedModel && <div className="model-detail"><div><b>{selectedModel.name}</b><span>中文 {selectedModel.chinese} · {selectedModel.note}</span></div><div className="requirements"><span>推理内存 ≥ {selectedModel.runtime_ram_gb} GB</span><span>LoRA 显存 ≥ {selectedModel.min_lora_vram_gb} GB</span><span>完整权重约 {selectedModel.full_disk_gb} GB</span></div><div className="model-links"><a href={selectedModel.ollama_url} target="_blank" rel="noreferrer">Ollama 模型页 ↗</a><a href={selectedModel.huggingface_url} target="_blank" rel="noreferrer">Hugging Face ↗</a><code>{method === "memory" ? selectedModel.ollama_command : selectedModel.lora_command}</code></div></div>}
            <div className="explain"><b>{method === "memory" ? "几分钟即可开始" : "需要独立显卡与更多时间"}</b><p>{method === "memory" ? "从聊天里检索最相近的语气和表达，搭配本地模型生成。CPU、Windows、macOS 与 Linux 均可用。" : "只训练模型的少量参数，角色风格更稳定。NVIDIA 8 GB+ 显存或 Apple Silicon 16 GB+ 内存推荐。"}</p></div>
            {estimate && <div className={`estimate ${estimate.compatible ? "" : "warning"}`}><div><small>预计用时</small><b>{estimate.min_minutes}–{estimate.max_minutes} 分钟</b></div><div><small>新增磁盘</small><b>约 {estimate.disk_gb} GB</b></div><div><small>峰值资源</small><b>{estimate.peak_memory_gb} GB</b></div><p>{estimate.compatible ? `估算可信度：${estimate.confidence}` : "当前设备不建议用此配置训练"}<br />{estimate.basis}</p></div>}
            <div className="no-download">此页面不会自动下载模型。选择只会生成适配配置；请阅读上方模型页并自行执行命令。</div>
            {training || trained ? <div className="progress"><div><b>{trained ? (method === "memory" ? "角色记忆已准备好" : "训练数据与配置已准备好（尚未训练）") : (method === "memory" ? "正在整理角色记忆…" : "正在生成训练数据与配置…")}</b><span>{progress}%</span></div><i><em style={{ width: `${progress}%` }} /></i></div> : null}
            <button className="primary" onClick={trained ? enterChat : buildDataset} disabled={training || Boolean(estimate && !estimate.compatible)}>{training ? "正在处理…" : trained ? (method === "memory" ? "进入聊天" : "用基础模型预览聊天") : method === "memory" ? "生成角色记忆" : "生成训练配置（不下载模型）"}<span>→</span></button>
          </div>
        </section>
        <section className="appearance panel">
          <div className="panel-head"><span>05</span><div><h2>装扮聊天界面</h2><p>昵称、头像和背景仅保存在这台设备</p></div></div>
          <div className="appearance-grid">
            <label className="avatar-upload">{dogAvatar ? <img src={dogAvatar} alt="舔狗头像预览" /> : <i>舔</i>}<span>舔狗头像<small>点击上传</small></span><input type="file" accept="image/*" onChange={(e) => readImage(e, setDogAvatar)} /></label>
            <label className="name-field">舔狗昵称<input value={dogName} maxLength={20} onChange={(e) => setDogName(e.target.value)} /></label>
            <label className="avatar-upload">{receiverAvatar ? <img src={receiverAvatar} alt="被舔者头像预览" /> : <i className="receiver-avatar">被</i>}<span>被舔者头像<small>点击上传</small></span><input type="file" accept="image/*" onChange={(e) => readImage(e, setReceiverAvatar)} /></label>
            <label className="name-field">被舔者昵称<input value={receiverName} maxLength={20} onChange={(e) => setReceiverName(e.target.value)} /></label>
          </div>
          <div className="background-picker"><span>聊天背景</span>{["classic", "paper", "night", "custom"].map((item) => <label key={item} className={`bg-swatch ${item} ${chatBackground === item ? "selected" : ""}`}><input type="radio" name="background" checked={chatBackground === item} onChange={() => setChatBackground(item)} />{item === "classic" ? "经典" : item === "paper" ? "暖纸" : item === "night" ? "深夜" : "自定义"}</label>)}{chatBackground === "custom" && <label className="file-text">选择背景图<input type="file" accept="image/*" onChange={(e) => readImage(e, setCustomBackground)} /></label>}</div>
        </section></>
      )}

      {step === "chat" && (
        <section className="chat-stage">
          <aside className="chat-rules">
            <button className="back" onClick={() => setStep("train")}>← 返回设定</button>
            <p className="eyebrow">本轮身份</p><h2>你是{roleName(playerRole)}</h2><p>对方是 {roleName(modelRole)} · {modelRole === "dog" ? dogName : receiverName}</p>
            <div className="rule-summary"><span>{playerRole === "receiver" ? "主动追发" : "允许沉默"}<b>{playerRole === "receiver" ? `${ignored} / ${maxIgnored} 条` : allowSilence ? "已开启" : "已关闭"}</b></span><span>等待上限<b>{waitSeconds} 秒</b></span><span>运行方式<b>{method === "memory" ? "角色记忆" : "LoRA 微调"}</b></span></div>
            <button className="danger-text" onClick={() => { setChat([]); setIgnored(0); }}>清空本轮对话</button>
          </aside>
          <div className="phone">
            <div className="phone-head"><button>‹</button><div><b>{modelRole === "dog" ? dogName : receiverName}</b><small>{busy ? "正在输入…" : "本地角色 · 在线"}</small></div><span>•••</span></div>
            <div className={`conversation bg-${chatBackground}`} style={chatBackground === "custom" && customBackground ? { backgroundImage: `linear-gradient(rgba(238,238,238,.72), rgba(238,238,238,.72)), url(${customBackground})` } : undefined}>
              <div className="date-chip">今天 {now()}</div>
              {!chat.length && playerRole === "receiver" && <div className="waiting">对方正在想怎么开口…</div>}
              {!chat.length && playerRole === "dog" && <div className="waiting">你是舔狗，请先主动发一条消息</div>}
              {chat.map((message) => message.role === "notice" ? <div className="notice" key={message.id}>{message.text}</div> : <div key={message.id} className={`bubble-row ${message.role}`}><div className="avatar">{(message.role === "me" ? (playerRole === "dog" ? dogAvatar : receiverAvatar) : (modelRole === "dog" ? dogAvatar : receiverAvatar)) ? <img src={message.role === "me" ? (playerRole === "dog" ? dogAvatar : receiverAvatar) : (modelRole === "dog" ? dogAvatar : receiverAvatar)} alt="" /> : message.role === "me" ? "我" : (modelRole === "dog" ? "舔" : "被")}</div><div><p>{message.text}</p><small>{message.time}</small></div></div>)}
              {busy && <div className="bubble-row model"><div className="avatar">{(modelRole === "dog" ? dogAvatar : receiverAvatar) ? <img src={modelRole === "dog" ? dogAvatar : receiverAvatar} alt="" /> : modelRole === "dog" ? "舔" : "被"}</div><div className="typing"><i /><i /><i /></div></div>}
              <div ref={endRef} />
            </div>
            <form className="composer" onSubmit={send}><button type="button" aria-label="语音">◉</button><input value={input} onChange={(e) => setInput(e.target.value)} placeholder={playerRole === "dog" ? "主动说点什么…" : "回复，或继续不理他…"} /><button className="send" disabled={!input.trim() || busy}>发送</button></form>
          </div>
        </section>
      )}

      <section className="guide" id="guide">
        <div><p className="eyebrow">HOW TO EXPORT</p><h2>聊天记录怎么拿到？</h2></div>
        <ol><li><span>1</span><b>优先使用官方备份</b><p>先用微信桌面版“迁移与备份”保留原始数据；本项目不会直接读取或破解微信数据库。</p></li><li><span>2</span><b>导出为结构化文本</b><p>可参考 chatlog、WeChatMsg 等开源工具，只导出你有权使用的一对一会话。</p></li><li><span>3</span><b>检查并取得同意</b><p>删除身份证、地址、账号等敏感内容；涉及他人数据时请先获得明确许可。</p></li></ol>
      </section>
      <footer><b>舔狗模拟器</b><span>本地优先 · 仅供自我探索与娱乐 · 请尊重聊天对象的隐私与同意</span><a href="https://github.com/pigwu/tiangou-simulator">GitHub ↗</a></footer>
    </main>
  );
}
