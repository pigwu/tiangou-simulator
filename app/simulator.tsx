"use client";
/* eslint-disable @next/next/no-img-element -- 用户本地 Data URL 头像无法交给图片优化器 */

import { ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";

type Step = "import" | "train" | "chat";
type Role = "dog" | "receiver";
type InputMode = "records" | "story";
type Method = "memory" | "lora" | "hybrid";
type ChatMessage = { id: string; role: "me" | "model" | "notice"; text: string; time: string };
type ImportedMessage = { sender: string; content: string; timestamp?: string };
type ModelInfo = { id: string; name: string; ollama_tag: string; hf_id: string; quant_disk_gb: number; full_disk_gb: number; runtime_ram_gb: number; min_lora_vram_gb: number; chinese: string; note: string; memory_compatible: boolean; disk_compatible: boolean; lora_compatible: boolean; ollama_adapter_supported: boolean; recommended: boolean; ollama_url: string; huggingface_url: string; ollama_command: string; lora_command: string };
type Hardware = { system: string; ram_gb: number; gpu_name: string; vram_gb: number; free_disk_gb: number; ollama_installed: boolean };
type Estimate = { min_minutes: number; max_minutes: number; disk_gb: number; peak_memory_gb: number; confidence: string; compatible: boolean; basis: string };
type DataReport = { source_messages: number; usable_messages: number; duplicate_messages_removed: number; duplicate_examples_removed: number; session_count: number; example_count: number; train_count: number; validation_count: number; test_count: number; split_strategy: string; warnings: string[] };
type MemoryEvidence = { kind: "dialogue" | "narrative"; source_id: string; source_time: string; score: number; reason: string; preview: string };
type EvaluationSummary = { method: string; label: string; samples: number; similarity: number; style_score: number; verbatim_rate: number; duplicate_rate: number; average_latency_ms: number };
type EvaluationResult = { sample_count: number; summary: EvaluationSummary[]; skipped: { method: string; reason: string }[] };
type TrainingReceipt = { completed_at?: string; example_count?: number; epochs?: number; train_loss?: number; runtime_seconds?: number; best_eval_loss?: number };
type TrainingJob = { status: "idle" | "running" | "completed" | "failed" | "cancelled"; role: Role; message?: string; started_at?: string; progress?: { phase?: string; step?: number; total_steps?: number; percent?: number; epoch?: number; loss?: number; eval_loss?: number }; log_tail?: string[] };
type TrainingDiagnostics = { ready: boolean; blockers: string[]; warnings: string[]; missing_packages: string[]; checkpoint?: string; can_resume: boolean; completed: boolean; required_disk_gb: number; free_disk_gb: number; required_vram_gb: number; available_vram_gb: number; job: TrainingJob };
type LocalProject = { id: string; name: string; managed: boolean; created_at?: string; updated_at?: string; dog_name: string; receiver_name: string; message_count: number; narrative_chars: number; roles_ready: Role[]; size_bytes: number };
type ProjectSource = { input_mode?: InputMode; messages?: ImportedMessage[]; narrative?: string; narrator_role?: Role; dog_speaker?: string; receiver_speaker?: string; dog_name?: string; receiver_name?: string };

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
  const [projects, setProjects] = useState<LocalProject[]>([]);
  const [activeProjectId, setActiveProjectId] = useState("");
  const [newProjectName, setNewProjectName] = useState("");
  const [projectBusy, setProjectBusy] = useState(false);
  const [projectError, setProjectError] = useState("");
  const [deleteAcknowledgement, setDeleteAcknowledgement] = useState("");
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
  const [installedModels, setInstalledModels] = useState<string[]>([]);
  const [hardware, setHardware] = useState<Hardware | null>(null);
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [method, setMethod] = useState<Method>("memory");
  const [loraModelTag, setLoraModelTag] = useState("tiangou-dog:latest");
  const [trainCommand, setTrainCommand] = useState("");
  const [registerCommand, setRegisterCommand] = useState("");
  const [setupError, setSetupError] = useState("");
  const [setupWarning, setSetupWarning] = useState("");
  const [training, setTraining] = useState(false);
  const [trained, setTrained] = useState(false);
  const [progress, setProgress] = useState(0);
  const [dataReport, setDataReport] = useState<DataReport | null>(null);
  const [evaluation, setEvaluation] = useState<EvaluationResult | null>(null);
  const [evaluating, setEvaluating] = useState(false);
  const [trainingReceipt, setTrainingReceipt] = useState<TrainingReceipt | null>(null);
  const [epochs, setEpochs] = useState(2);
  const [diagnostics, setDiagnostics] = useState<TrainingDiagnostics | null>(null);
  const [job, setJob] = useState<TrainingJob | null>(null);
  const [jobAcknowledgement, setJobAcknowledgement] = useState("");
  const [jobActionBusy, setJobActionBusy] = useState(false);
  const [allowSilence, setAllowSilence] = useState(true);
  const [maxIgnored, setMaxIgnored] = useState(3);
  const [waitSeconds, setWaitSeconds] = useState(15);
  const [chat, setChat] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [ignored, setIgnored] = useState(0);
  const [memoryEvidence, setMemoryEvidence] = useState<MemoryEvidence[]>([]);
  const [backend, setBackend] = useState<"checking" | "online" | "offline">("checking");
  const [ollamaOnline, setOllamaOnline] = useState<boolean | null>(null);
  const [appearanceReady, setAppearanceReady] = useState(false);
  const [appearanceProjectId, setAppearanceProjectId] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const silenceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastPlayerMessage = useRef("");
  const endRef = useRef<HTMLDivElement>(null);

  const speakers = useMemo(() => Array.from(new Set(messages.map((item) => item.sender))), [messages]);
  const modelRole: Role = playerRole === "dog" ? "receiver" : "dog";
  const roleName = (role: Role) => (role === "dog" ? "舔狗" : "被舔者");
  const importReady = inputMode === "records" ? messages.length > 0 && dogSpeaker !== receiverSpeaker : narrative.trim().length >= 30;
  const selectedModel = models.find((item) => item.id === model);
  const normalizedLoraTag = loraModelTag.trim() || `tiangou-${modelRole}:latest`;
  const roleModelReady = method === "memory" || installedModels.includes(normalizedLoraTag);
  const methodName = method === "memory" ? "聊天记忆" : method === "lora" ? "LoRA 微调" : "混合模式";
  const activeProject = projects.find((item) => item.id === activeProjectId);
  const formatBytes = (bytes: number) => bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(1)} GB` : bytes >= 1024 ** 2 ? `${(bytes / 1024 ** 2).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`;

  useEffect(() => {
    fetch(`${API}/api/system`).then((r) => r.ok ? r.json() : Promise.reject()).then((data) => {
      setHardware(data.hardware);
      setModels(data.models || []);
      const installed: string[] = data.installed_models || [];
      setInstalledModels(installed);
      setBackend("online");
      setOllamaOnline(installed.length > 0);
      const downloaded = (data.models || []).find((item: ModelInfo) => installed.includes(item.ollama_tag));
      const recommended = (data.models || []).find((item: ModelInfo) => item.recommended);
      if (downloaded) setModel(downloaded.id);
      else if (recommended) setModel(recommended.id);
    }).catch(() => { setBackend("offline"); setOllamaOnline(false); });
    fetch(`${API}/api/projects`).then((r) => r.ok ? r.json() : Promise.reject()).then((data) => {
      const items: LocalProject[] = data.projects || [];
      setProjects(items);
      const saved = localStorage.getItem("tiangou-active-project") || "";
      setActiveProjectId(items.some((item) => item.id === saved) ? saved : (items[0]?.id || ""));
    }).catch(() => setProjectError("无法读取本地项目列表"));
  }, []);

  useEffect(() => {
    if (!activeProjectId) return;
    localStorage.setItem("tiangou-active-project", activeProjectId);
    let stopped = false;
    fetch(`${API}/api/projects/${activeProjectId}`).then((response) => response.ok ? response.json() : Promise.reject()).then((data) => {
      if (stopped) return;
      const source: ProjectSource = data.source || {};
      setInputMode(source.input_mode || "records");
      setMessages(source.messages || []); setFilename(source.messages?.length ? "已保存的本地记录" : "");
      setNarrative(source.narrative || ""); setNarratorRole(source.narrator_role || "dog");
      setDogSpeaker(source.dog_speaker || data.dog_name || "舔狗"); setReceiverSpeaker(source.receiver_speaker || data.receiver_name || "被舔者");
      setDogName(source.dog_name || data.dog_name || "舔狗"); setReceiverName(source.receiver_name || data.receiver_name || "被舔者");
      setStep("import"); setTrained(false); setDataReport(null); setEvaluation(null); setChat([]); setDiagnostics(null); setJob(null); setDeleteAcknowledgement(""); setProjectError("");
      try {
        const saved = JSON.parse(localStorage.getItem(`tiangou-appearance-${activeProjectId}`) || localStorage.getItem("tiangou-appearance") || "{}");
        if (saved.dogName) setDogName(saved.dogName);
        if (saved.receiverName) setReceiverName(saved.receiverName);
        setDogAvatar(saved.dogAvatar || ""); setReceiverAvatar(saved.receiverAvatar || "");
        setChatBackground(saved.chatBackground || "classic"); setCustomBackground(saved.customBackground || "");
      } catch { /* 浏览器存储不可用时仍可继续 */ }
      setAppearanceProjectId(activeProjectId);
      setAppearanceReady(true);
    }).catch(() => { if (!stopped) setProjectError("无法打开所选本地项目"); });
    return () => { stopped = true; };
  }, [activeProjectId]);

  useEffect(() => {
    if (!appearanceReady || appearanceProjectId !== activeProjectId) return;
    try {
      if (activeProjectId) localStorage.setItem(`tiangou-appearance-${activeProjectId}`, JSON.stringify({ dogName, receiverName, dogAvatar, receiverAvatar, chatBackground, customBackground }));
    } catch { /* 图片过大时仅在当前会话保留 */ }
  }, [appearanceReady, appearanceProjectId, activeProjectId, dogName, receiverName, dogAvatar, receiverAvatar, chatBackground, customBackground]);

  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth" }), [chat, busy]);

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
    if (silenceTimer.current) clearTimeout(silenceTimer.current);
  }, []);

  useEffect(() => {
    if (step !== "train" || method === "memory" || !trained) return;
    let stopped = false;
    const refresh = async () => {
      try {
        const running = job?.status === "running";
        const query = `?project_id=${encodeURIComponent(activeProjectId)}`;
        const response = await fetch(`${API}${running ? `/api/training-jobs/${modelRole}${query}` : `/api/training-diagnostics/${modelRole}${query}`}`);
        if (!response.ok) return;
        const data = await response.json();
        if (!stopped) {
          if (running) setJob(data);
          else { setDiagnostics(data); setJob(data.job || null); }
        }
      } catch { /* 后端离线时保留上次状态 */ }
    };
    void refresh();
    const interval = job?.status === "running" ? setInterval(refresh, 1500) : null;
    return () => { stopped = true; if (interval) clearInterval(interval); };
  }, [step, method, trained, modelRole, activeProjectId, job?.status]);

  useEffect(() => {
    if (step !== "train") return;
    const controller = new AbortController();
    fetch(`${API}/api/estimate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model_id: model, method, message_count: messages.length, narrative_chars: narrative.length, epochs }),
      signal: controller.signal,
    }).then((r) => r.ok ? r.json() : Promise.reject()).then(setEstimate).catch(() => {
      if (method === "memory") {
        setEstimate({ min_minutes: 1, max_minutes: 2, disk_gb: 0.1, peak_memory_gb: 1, confidence: "离线估算", compatible: true, basis: "本地整理与索引" });
      } else if (selectedModel) {
        setEstimate({ min_minutes: 8, max_minutes: 60, disk_gb: selectedModel.full_disk_gb + 1, peak_memory_gb: selectedModel.min_lora_vram_gb, confidence: "离线粗略估算", compatible: selectedModel.lora_compatible, basis: method === "hybrid" ? "LoRA 风格训练 + 聊天记忆索引；连接后端后显示设备化估算" : "LoRA 风格训练；连接后端后显示设备化估算" });
      } else {
        setEstimate(null);
      }
    });
    return () => controller.abort();
  }, [step, model, method, messages.length, narrative.length, epochs, selectedModel]);

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

  async function refreshProjects(selectId?: string) {
    const response = await fetch(`${API}/api/projects`);
    if (!response.ok) throw new Error("无法刷新本地项目");
    const data = await response.json();
    const items: LocalProject[] = data.projects || [];
    setProjects(items);
    setActiveProjectId((current) => selectId || (items.some((item) => item.id === current) ? current : (items[0]?.id || "")));
  }

  async function createLocalProject() {
    const name = newProjectName.trim();
    if (!name) return;
    setProjectBusy(true); setProjectError("");
    try {
      const response = await fetch(`${API}/api/projects`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "无法创建项目");
      setNewProjectName("");
      await refreshProjects(data.id);
    } catch (error) {
      setProjectError(error instanceof Error ? error.message : "无法创建项目");
    } finally { setProjectBusy(false); }
  }

  async function deleteLocalProject() {
    if (!activeProject?.managed || deleteAcknowledgement !== activeProject.name) return;
    setProjectBusy(true); setProjectError("");
    try {
      const response = await fetch(`${API}/api/projects/${activeProject.id}`, { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ acknowledgement: deleteAcknowledgement }) });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "无法删除项目");
      try { localStorage.removeItem(`tiangou-appearance-${activeProject.id}`); } catch { /* ignore */ }
      setDeleteAcknowledgement(""); setActiveProjectId(""); setMessages([]); setNarrative("");
      await refreshProjects();
    } catch (error) {
      setProjectError(error instanceof Error ? error.message : "无法删除项目");
    } finally { setProjectBusy(false); }
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
    setSetupError("");
    setSetupWarning("");
    let prepared = false;
    try {
      const response = await fetch(`${API}/api/dataset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: activeProjectId,
          messages,
          dog_speaker: dogSpeaker,
          receiver_speaker: receiverSpeaker,
          dog_name: dogName,
          receiver_name: receiverName,
          model_role: modelRole,
          narrative: inputMode === "story" ? narrative : "",
          narrator_role: narratorRole,
          method,
          model_id: model,
          epochs,
          lora_model_tag: normalizedLoraTag,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "生成角色数据失败");
      setTrainCommand(data.train_command || "");
      setRegisterCommand(data.register_command || "");
      setSetupWarning(data.warning || "");
      setDataReport(data.data_report || null);
      setEvaluation(null);
      setTrainingReceipt(null);
      setDiagnostics(null);
      setJob(null);
      setJobAcknowledgement("");
      setBackend("online");
      await refreshProjects();
      prepared = true;
    } catch (error) {
      setSetupError(error instanceof Error ? error.message : "生成角色数据失败");
    }
    for (const value of [38, 64, 86, 100]) {
      await new Promise((resolve) => setTimeout(resolve, 240));
      setProgress(value);
    }
    setTraining(false);
    setTrained(prepared);
  }

  async function enterChat() {
    setSetupError("");
    if (method !== "memory") {
      try {
        const response = await fetch(`${API}/api/training-status`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ project_id: activeProjectId, model_tag: normalizedLoraTag, model_role: modelRole }),
        });
        if (!response.ok) throw new Error("无法检查 LoRA 训练状态");
        const data = await response.json();
        if (!data.ready) {
          const missing = Array.isArray(data.missing) ? data.missing.join("、") : "训练凭证或角色模型";
          setSetupError(`混合模式尚未就绪：缺少${missing}。完成界面所示命令后再检查。`);
          return;
        }
        setTrainingReceipt(data.receipt || null);
        setInstalledModels((items) => items.includes(normalizedLoraTag) ? items : [...items, normalizedLoraTag]);
      } catch (error) {
        setSetupError(error instanceof Error ? error.message : "无法检查角色模型");
        return;
      }
    }
    setChat([]);
    setMemoryEvidence([]);
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
          project_id: activeProjectId,
          model: method === "memory" ? (selectedModel?.ollama_tag || "qwen2.5:3b") : normalizedLoraTag,
          method,
          model_role: modelRole,
          player_role: playerRole,
          dog_speaker: dogSpeaker,
          receiver_speaker: receiverSpeaker,
          dog_name: dogName,
          receiver_name: receiverName,
          ignored_count: nextIgnored,
          max_ignored: maxIgnored,
          history: chat
            .filter((item) => item.role === "me" || item.role === "model")
            .slice(-16)
            .map((item) => ({ role: item.role === "me" ? "user" : "assistant", content: item.text })),
        }),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(typeof error.detail === "string" ? error.detail : `本地模型调用失败（HTTP ${response.status}）`);
      }
      const data = await response.json();
      setChat((items) => [...items, { id: crypto.randomUUID(), role: "model", text: data.reply, time: now() }]);
      setMemoryEvidence(data.memory_evidence || []);
      setBackend("online");
      setOllamaOnline(true);
    } catch (error) {
      const fallback = modelRole === "dog"
        ? ["在忙吗？看到的话回我一下就好。", "我是不是打扰到你了……没事，你先忙。", "刚刚路过你说过的那家店，突然想到你了。"]
        : ["刚看到。", "今天有点忙，晚点再说吧。", "你不用一直等我消息的。"];
      const detail = error instanceof Error ? error.message : "本地模型调用失败";
      setChat((items) => {
        const modelReplies = items.filter((item) => item.role === "model");
        const used = new Set(modelReplies.slice(-fallback.length).map((item) => item.text));
        const reply = fallback.find((item) => !used.has(item)) || fallback[modelReplies.length % fallback.length];
        return [
          ...items,
          { id: crypto.randomUUID(), role: "notice", text: `未使用聊天记忆：${detail}。下面是演示回复。`, time: now() },
          { id: crypto.randomUUID(), role: "model", text: reply, time: now() },
        ];
      });
      setOllamaOnline(false);
      setMemoryEvidence([]);
    } finally {
      if (proactive) setIgnored(nextIgnored);
      if (!proactive && silenceTimer.current) {
        clearTimeout(silenceTimer.current);
        silenceTimer.current = null;
      }
      setBusy(false);
    }
  }

  async function runEvaluation() {
    setEvaluating(true);
    setSetupError("");
    try {
      const response = await fetch(`${API}/api/evaluate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_model: selectedModel?.ollama_tag || "qwen2.5:3b",
          project_id: activeProjectId,
          role_model: normalizedLoraTag,
          model_role: modelRole,
          player_role: playerRole,
          dog_speaker: dogSpeaker,
          receiver_speaker: receiverSpeaker,
          dog_name: dogName,
          receiver_name: receiverName,
          limit: 3,
        }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "本地评测失败");
      setEvaluation(data);
      setBackend("online");
      setOllamaOnline(true);
    } catch (error) {
      setSetupError(error instanceof Error ? error.message : "本地评测失败");
    } finally {
      setEvaluating(false);
    }
  }

  async function startLocalTraining(resume = false) {
    setJobActionBusy(true);
    setSetupError("");
    try {
      const response = await fetch(`${API}/api/training-jobs`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: activeProjectId, model_role: modelRole, resume, acknowledgement: jobAcknowledgement }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "无法启动本地训练");
      setJob(data);
      setJobAcknowledgement("");
    } catch (error) {
      setSetupError(error instanceof Error ? error.message : "无法启动本地训练");
    } finally {
      setJobActionBusy(false);
    }
  }

  async function cancelLocalTraining() {
    if (!window.confirm("确定停止当前训练吗？已保存的 checkpoint 会保留，可稍后恢复。")) return;
    setJobActionBusy(true);
    setSetupError("");
    try {
      const response = await fetch(`${API}/api/training-jobs/${modelRole}/cancel?project_id=${encodeURIComponent(activeProjectId)}`, { method: "POST" });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : "无法停止训练");
      setJob(data);
    } catch (error) {
      setSetupError(error instanceof Error ? error.message : "无法停止训练");
    } finally {
      setJobActionBusy(false);
    }
  }

  useEffect(() => {
    if (step !== "chat" || playerRole !== "receiver" || busy || ignored >= maxIgnored) return;
    const delay = chat.length === 0 ? 1200 : waitSeconds * 1000;
    timer.current = setTimeout(() => void requestReply("（对方还没有回复。请主动发一条消息，语气随等待次数逐渐着急，但不要提及这是模拟器。）", true), delay);
    return () => { if (timer.current) clearTimeout(timer.current); };
  // requestReply 使用当前角色状态；计时器会在每次相关状态变化时重建。
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, playerRole, chat.length, ignored, maxIgnored, waitSeconds, busy]);

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
        <div className="privacy"><i className={backend === "online" && ollamaOnline === false ? "checking" : backend} /> {backend === "online" ? (ollamaOnline ? "本地模型已连接" : "后端已连接 · Ollama 未连接") : backend === "checking" ? "正在连接本地服务" : "演示模式 · 启动后端可训练"}</div>
      </header>

      <section className="hero">
        <div>
          <p className="eyebrow">把过去的消息，变成一场新的对话</p>
          <h1>这一次，换个身份<br />看看故事会怎么继续。</h1>
        </div>
        <p className="hero-note">聊天记录、训练数据与模型默认只停留在你的电脑。<br />不上传，不围观，也不替任何人做情感承诺。</p>
      </section>

      <section className="project-switcher" aria-label="本地项目管理">
        <div className="project-list"><span>当前关系项目</span>{projects.length ? <select value={activeProjectId} onChange={(event) => setActiveProjectId(event.target.value)}>{projects.map((item) => <option key={item.id} value={item.id}>{item.name} · {item.dog_name} / {item.receiver_name}</option>)}</select> : <b>还没有本地项目</b>}{activeProject && <small>{activeProject.message_count ? `${activeProject.message_count} 条消息` : `${activeProject.narrative_chars} 字自述`} · {formatBytes(activeProject.size_bytes)} · {activeProject.managed ? "独立隔离" : "旧数据兼容"}</small>}</div>
        <div className="project-create"><input value={newProjectName} maxLength={60} onChange={(event) => setNewProjectName(event.target.value)} placeholder="新项目名，例如：大学那段关系" /><button onClick={createLocalProject} disabled={projectBusy || !newProjectName.trim()}>新建项目</button></div>
        {activeProject && <details className="project-tools"><summary>导出或删除</summary><a href={`${API}/api/projects/${activeProject.id}/export`} download>导出项目 ZIP（不含模型权重）</a>{activeProject.managed ? <><label>输入项目名“{activeProject.name}”确认永久删除<input value={deleteAcknowledgement} onChange={(event) => setDeleteAcknowledgement(event.target.value)} /></label><button onClick={deleteLocalProject} disabled={projectBusy || deleteAcknowledgement !== activeProject.name}>永久删除本地项目</button></> : <p>原有兼容项目不能在这里递归删除，可先导出后继续保留。</p>}</details>}
        {projectError && <div className="project-error">{projectError}</div>}
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
            <div className="input-tabs"><button className={inputMode === "records" ? "active" : ""} onClick={() => setInputMode("records")}>聊天记录</button><button className={inputMode === "story" ? "active" : ""} onClick={() => { setInputMode("story"); setMethod("memory"); setTrained(false); setSetupError(""); }}>经历自述</button></div>
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
            <button className="primary" disabled={!activeProjectId || !importReady} onClick={() => setStep("train")}>{activeProjectId ? "身份确认，下一步" : "请先新建或选择项目"} <span>→</span></button>
          </div>
        </section>
      )}

      {step === "train" && (
        <><section className="workspace train-grid">
          <div className="panel role-choice">
            <div className="panel-head"><span>03</span><div><h2>这次，你想做谁？</h2><p>模型会扮演另一个人</p></div></div>
            <div className="choice-cards">
              <button className={playerRole === "dog" ? "selected" : ""} onClick={() => { setPlayerRole("dog"); setLoraModelTag("tiangou-receiver:latest"); setTrained(false); }}><i>汪</i><b>我是舔狗</b><small>你主动发消息<br />模型扮演被舔者</small></button>
              <button className={playerRole === "receiver" ? "selected" : ""} onClick={() => { setPlayerRole("receiver"); setLoraModelTag("tiangou-dog:latest"); setTrained(false); }}><i>等</i><b>我是被舔者</b><small>模型会主动发消息<br />你决定回不回复</small></button>
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
            <div className="method-tabs"><button className={method === "memory" ? "active" : ""} onClick={() => { setMethod("memory"); setEstimate(null); setTrained(false); setSetupError(""); setSetupWarning(""); }}>聊天记忆 <small>轻量</small></button><button disabled={inputMode === "story"} className={method === "lora" ? "active" : ""} onClick={() => { setMethod("lora"); setEstimate(null); setTrained(false); setSetupError(""); setSetupWarning(""); }}>LoRA 微调 <small>风格</small></button><button disabled={inputMode === "story" || !models.length} className={method === "hybrid" ? "active" : ""} onClick={() => { setMethod("hybrid"); setEstimate(null); setTrained(false); setSetupError(""); setSetupWarning(""); const direct = models.find((item) => item.ollama_adapter_supported); if (direct) setModel(direct.id); }}>混合模式 <small>推荐</small></button></div>
            <div className="model-select"><label>基础模型<select value={model} onChange={(e) => { setModel(e.target.value); setEstimate(null); setTrained(false); }}>{models.length ? models.map((item) => <option key={item.id} value={item.id}>{item.recommended ? "★ " : ""}{item.name} · 量化约 {item.quant_disk_gb} GB</option>) : <><option value="qwen25-15b">Qwen2.5 1.5B · 约 1 GB</option><option value="qwen25-3b">Qwen2.5 3B · 约 2 GB</option><option value="qwen25-7b">Qwen2.5 7B · 约 5 GB</option><option value="qwen3-8b">Qwen3 8B · 约 5.2 GB</option></>}</select></label><span className="fit">{selectedModel?.recommended ? "本机推荐" : selectedModel && (method !== "memory" ? selectedModel.lora_compatible : selectedModel.memory_compatible) ? "本机可用" : selectedModel ? "配置可能不足" : "默认推荐"}</span></div>
            {method !== "memory" && <label className="adapter-tag">Ollama 角色模型标签<input value={loraModelTag} onChange={(e) => { setLoraModelTag(e.target.value); setTrained(false); setSetupError(""); }} placeholder={`tiangou-${modelRole}:latest`} /><small>这是训练后注册的角色标签，不是基础模型标签；舔狗和被舔者必须使用不同标签。</small></label>}
            {selectedModel && <div className="model-detail"><div><b>{selectedModel.name}</b><span>中文 {selectedModel.chinese} · {selectedModel.note}</span></div><div className="requirements"><span>{installedModels.includes(selectedModel.ollama_tag) ? "✓ 基础 Ollama 模型已安装" : "基础 Ollama 模型未安装"}</span>{method !== "memory" && <span>{selectedModel.ollama_adapter_supported ? "✓ Ollama 官方列出该 LoRA 架构" : "需合并/转换后再注册 Ollama"}</span>}{method !== "memory" && <span>{roleModelReady ? `✓ 角色标签 ${normalizedLoraTag} 已注册` : `角色标签 ${normalizedLoraTag} 尚未注册`}</span>}<span>推理内存 ≥ {selectedModel.runtime_ram_gb} GB</span><span>LoRA 显存 ≥ {selectedModel.min_lora_vram_gb} GB</span><span>完整权重约 {selectedModel.full_disk_gb} GB</span></div><div className="model-links"><a href={selectedModel.ollama_url} target="_blank" rel="noreferrer">Ollama 模型页 ↗</a><a href={selectedModel.huggingface_url} target="_blank" rel="noreferrer">Hugging Face ↗</a><code>{method === "memory" ? selectedModel.ollama_command : selectedModel.lora_command}</code></div></div>}
            {method !== "memory" && <label className="epochs-control">训练轮数<input type="number" min="0.1" max="20" step="0.5" value={epochs} onChange={(event) => { setEpochs(Math.min(20, Math.max(0.1, Number(event.target.value) || 0.1))); setTrained(false); setDiagnostics(null); }} /><small>小数据默认 2 轮；有验证集时会早停并保留最佳 checkpoint。修改后需重新生成配置。</small></label>}
            <div className="explain"><b>{method === "memory" ? "相似记录开卷参考" : method === "lora" ? "只验证 LoRA 学到的风格" : "LoRA 风格 + 聊天记忆事实"}</b><p>{method === "memory" ? "基础模型检索最相近的历史片段，适合 CPU 和快速开始；新场景中的风格泛化有限。" : method === "lora" ? "推理时不注入历史片段，只使用已注册的 LoRA 角色模型，适合与其他模式做严格对比。" : "已注册的 LoRA 负责新场景中的表达风格，检索记忆补充关系事实和相似情境；两部分缺一不可。"}</p></div>
            {estimate && <div className={`estimate ${estimate.compatible ? "" : "warning"}`}><div><small>预计用时</small><b>{estimate.min_minutes}–{estimate.max_minutes} 分钟</b></div><div><small>新增磁盘</small><b>约 {estimate.disk_gb} GB</b></div><div><small>峰值资源</small><b>{estimate.peak_memory_gb} GB</b></div><p>{estimate.compatible ? `估算可信度：${estimate.confidence}` : "当前设备不建议用此配置训练"}<br />{estimate.basis}</p></div>}
            <div className="no-download">此页面不会在未确认时下载或训练模型。LoRA/混合模式先生成本地配置；只有你在下方完整输入确认文字后，训练任务才会启动，首次训练可能从 Hugging Face 下载所选基础模型。适配器权重、匹配当前数据和角色方向的训练凭证、Ollama 角色标签同时存在才算可用。</div>
            {setupError && <div className="setup-error">{setupError}</div>}
            {setupWarning && method !== "memory" && <div className="setup-warning">{setupWarning}</div>}
            {training || trained ? <div className="progress"><div><b>{trained ? (method === "memory" ? "角色记忆已准备好" : "训练数据与命令已准备好（尚未证明已训练）") : (method === "memory" ? "正在整理角色记忆…" : "正在生成训练数据、Modelfile 与命令…")}</b><span>{progress}%</span></div><i><em style={{ width: `${progress}%` }} /></i></div> : null}
            {dataReport && <div className="data-report">
              <div><small>独立会话</small><b>{dataReport.session_count}</b></div><div><small>训练样本</small><b>{dataReport.train_count}</b></div><div><small>验证样本</small><b>{dataReport.validation_count}</b></div><div><small>测试样本</small><b>{dataReport.test_count}</b></div>
              <p>采用{dataReport.split_strategy}；已移除 {dataReport.duplicate_messages_removed + dataReport.duplicate_examples_removed} 条重复消息或问答。{dataReport.warnings.length ? ` 注意：${dataReport.warnings.join("；")}` : "留出集不会参与训练，可用于检验泛化。"}</p>
            </div>}
            {trained && method !== "memory" && <div className="generated-commands"><b>{registerCommand ? "接下来在项目根目录依次运行" : "先在项目根目录训练 LoRA"}</b><code>{trainCommand}</code>{registerCommand && <code>{registerCommand}</code>}<small>{registerCommand ? "训练完成前不要运行第二条。注册成功后返回此页，点击下方按钮重新检查。" : "当前基础架构不在 Ollama 官方 Safetensors ADAPTER 列表中。训练完成后需合并/转换并自行注册为上面的角色标签，或改选标注为可直载的模型。"}</small></div>}
            {trained && method !== "memory" && <div className="local-training">
              <div className="local-training-head"><div><b>本地训练任务</b><small>只在你确认后启动，不上传数据。关闭浏览器不会停止；请保持启动器窗口和电脑运行。</small></div><span className={`job-status ${job?.status || "idle"}`}>{job?.status === "running" ? "训练中" : job?.status === "completed" ? "已完成" : job?.status === "failed" ? "失败" : job?.status === "cancelled" ? "已取消" : "未启动"}</span></div>
              {diagnostics && <div className="diagnostic-grid"><span><b>{diagnostics.available_vram_gb} / {diagnostics.required_vram_gb} GB</b>显存 / 建议</span><span><b>{diagnostics.free_disk_gb} / {diagnostics.required_disk_gb} GB</b>剩余 / 预计磁盘</span><span><b>{diagnostics.missing_packages.length ? diagnostics.missing_packages.length : "✓"}</b>缺少依赖</span></div>}
              {diagnostics?.blockers.length ? <div className="diagnostic-blockers"><b>暂不能从 UI 训练</b>{diagnostics.blockers.map((item) => <span key={item}>· {item}</span>)}{diagnostics.missing_packages.length > 0 && <code>pip install -r requirements-train.txt</code>}</div> : diagnostics?.warnings.length ? <div className="diagnostic-warnings">{diagnostics.warnings.map((item) => <span key={item}>· {item}</span>)}</div> : null}
              {job?.status === "running" && <><div className="job-progress"><div><b>{job.progress?.phase === "saving" ? "正在保存适配器" : "正在训练"}</b><span>{Math.round(job.progress?.percent || 0)}%</span></div><i><em style={{ width: `${job.progress?.percent || 1}%` }} /></i><small>步骤 {job.progress?.step || 0} / {job.progress?.total_steps || "计算中"}{job.progress?.epoch != null ? ` · 第 ${job.progress.epoch.toFixed(2)} 轮` : ""}{job.progress?.loss != null ? ` · loss ${job.progress.loss}` : ""}</small></div><button className="cancel-training" onClick={cancelLocalTraining} disabled={jobActionBusy}>停止并保留 checkpoint</button></>}
              {job?.log_tail && job.log_tail.length > 0 && <details className="training-log" open={job.status === "failed"}><summary>查看最近训练日志</summary><pre>{job.log_tail.join("\n")}</pre></details>}
              {job?.status !== "running" && !diagnostics?.completed && <div className="training-confirm"><label>输入“确认本地训练”<input value={jobAcknowledgement} onChange={(event) => setJobAcknowledgement(event.target.value)} placeholder="确认本地训练" /></label><button onClick={() => startLocalTraining(Boolean(diagnostics?.can_resume))} disabled={jobActionBusy || !diagnostics?.ready || jobAcknowledgement !== "确认本地训练"}>{jobActionBusy ? "正在启动…" : diagnostics?.can_resume ? "从 checkpoint 恢复" : "开始本地训练"}</button></div>}
              {diagnostics?.completed && <div className="job-completed">当前数据已经有匹配的训练凭证。下一步按上方命令注册 Ollama 角色标签，再检查进入。</div>}
            </div>}
            {trainingReceipt && <div className="training-receipt"><b>训练凭证已核验</b><span>{trainingReceipt.example_count ?? "—"} 个样本 · {trainingReceipt.epochs ?? "—"} 轮 · 实际 {trainingReceipt.runtime_seconds ? `${Math.round(trainingReceipt.runtime_seconds / 60)} 分钟` : "未记录"}</span><small>训练 loss {trainingReceipt.train_loss ?? "—"}{trainingReceipt.best_eval_loss != null ? ` · 最佳验证 loss ${trainingReceipt.best_eval_loss}` : " · 未提供验证 loss"}</small></div>}
            <button className="primary" onClick={trained ? enterChat : buildDataset} disabled={training}>{training ? "正在处理…" : trained ? (method === "memory" ? "进入聊天" : roleModelReady ? `进入${methodName}` : "检查角色模型并进入") : method === "memory" ? "生成角色记忆" : method === "lora" ? "生成 LoRA 训练配置" : "生成混合模式配置"}<span>→</span></button>
            {trained && <div className="evaluation-panel"><div><b>用没参与训练的对话检验效果</b><small>同一问题对比基础模型、记忆、LoRA 与混合模式；最多运行 3 个本地测试问题。</small></div><button onClick={runEvaluation} disabled={evaluating || !dataReport?.test_count}>{evaluating ? "正在评测…" : "运行本地对比"}</button>{evaluation && <div className="evaluation-table">{evaluation.summary.map((item) => <div key={item.method}><b>{item.label}</b><span>句长/标点 {Math.round(item.style_score * 100)}%</span><span>参考回复相似 {Math.round(item.similarity * 100)}%</span><span>重复 {Math.round(item.duplicate_rate * 100)}%</span><small>{(item.average_latency_ms / 1000).toFixed(1)} 秒</small></div>)}{evaluation.skipped.length > 0 && <p>LoRA/混合模式未运行：角色模型尚未通过训练凭证检查。</p>}</div>}</div>}
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
            <div className="rule-summary"><span>{playerRole === "receiver" ? "主动追发" : "允许沉默"}<b>{playerRole === "receiver" ? `${ignored} / ${maxIgnored} 条` : allowSilence ? "已开启" : "已关闭"}</b></span><span>等待上限<b>{waitSeconds} 秒</b></span><span>运行方式<b>{methodName}</b></span>{method !== "memory" && <span>角色模型<b>{normalizedLoraTag}</b></span>}</div>
            {method !== "lora" && <div className="memory-evidence"><b>本轮记忆依据</b>{memoryEvidence.length ? memoryEvidence.slice(0, 3).map((item) => <details key={`${item.source_id}-${item.score}`}><summary>{item.kind === "narrative" ? "经历背景" : item.source_id} · {item.reason}</summary><p>{item.preview}</p><small>相关度 {Math.round(item.score * 100)}%{item.source_time ? ` · ${item.source_time}` : ""}</small></details>) : <p>发送消息后显示本轮实际使用的记忆；LoRA 模式不会注入记忆。</p>}</div>}
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
        <ol><li><span>1</span><b>先备份微信数据</b><p>微信 4.x Windows 数据通常位于 xwechat_files；先用“迁移与备份”保留可恢复副本，本项目不会读取数据库或密钥。</p></li><li><span>2</span><b>导出结构化 CSV</b><p>当前可参考 Ray0612/WeChat-Export-Tool；选择正确的 xwechat_files 目录并只导出你有权使用的一对一文字会话。</p></li><li><span>3</span><b>核对时间与隐私</b><p>保留时间列供会话切分，删除身份证、地址和账号；涉及他人数据时先取得明确许可。完整排障步骤见 README。</p></li></ol>
      </section>
      <footer><b>舔狗模拟器</b><span>本地优先 · 仅供自我探索与娱乐 · 请尊重聊天对象的隐私与同意</span><a href="https://github.com/pigwu/tiangou-simulator">GitHub ↗</a></footer>
    </main>
  );
}
