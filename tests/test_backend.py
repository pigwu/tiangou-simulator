import json
import asyncio
import hashlib
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from backend.dataset import build_examples, build_narrative_memory, prepare_dataset, retrieve_memories, retrieve_memory_items
import backend.main as backend_main
from backend.main import ChatRequest, DatasetRequest, memories_for_method, ollama_http_error, role_prompt
from backend.parsers import parse_upload
from backend.models import catalog, estimate
from backend.training_jobs import TrainingJobManager, diagnose_training
from backend.projects import create_export, create_project, delete_project, list_projects, project_dir, write_json


class ParserTests(unittest.TestCase):
    def test_parse_text_and_ignore_system_lines(self):
        data = "[22:01] A: 你好\n[22:02] B: 嗯\n[22:03] A: 撤回了一条消息".encode()
        messages = parse_upload("chat.txt", data)
        self.assertEqual([item["sender"] for item in messages], ["A", "B"])

    def test_parse_json_aliases(self):
        data = json.dumps([{"发送人": "甲", "内容": "在吗"}, {"发送人": "乙", "内容": "在"}], ensure_ascii=False).encode()
        self.assertEqual(len(parse_upload("chat.json", data)), 2)

    def test_parse_wechat_export_tool_csv_headers(self):
        data = "时间,发送者,消息内容,类型\n2026-08-13 09:00,甲,在吗,文本\n2026-08-13 09:00,甲,非文字占位,ZSTD\n2026-08-13 09:01,乙,在,文字\n".encode("utf-8-sig")
        messages = parse_upload("wechat.csv", data)
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["sender"], "甲")
        self.assertEqual(messages[0]["content"], "在吗")
        self.assertEqual(messages[0]["timestamp"], "2026-08-13 09:00")

    def test_parse_wechat_export_tool_english_headers(self):
        data = "timestamp,sender,content,type\n2026-08-13 09:00,甲,在吗,文字\n2026-08-13 09:01,乙,在,文字\n".encode()
        self.assertEqual(len(parse_upload("wechat.csv", data)), 2)


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.messages = [
            {"sender": "舔", "content": "吃饭了吗"},
            {"sender": "被", "content": "吃了"},
            {"sender": "舔", "content": "那就好"},
        ]

    def test_target_label_follows_model_role(self):
        dog = build_examples(self.messages, "舔", "被", "dog")
        receiver = build_examples(self.messages, "舔", "被", "receiver")
        self.assertEqual(dog[0]["messages"][-1]["content"], "那就好")
        self.assertEqual(receiver[0]["messages"][-1]["content"], "吃了")
        self.assertEqual(dog[0]["metadata"]["target_role"], "dog")

    def test_narrative_is_marked_non_verbatim(self):
        memory = build_narrative_memory("我们在社团认识。", "dog", "小周", "阿晚")
        self.assertEqual(memory["kind"], "narrative")
        self.assertIn("不代表任何逐字原话", memory["context"])

    def test_narrative_is_retrievable_without_dialogue(self):
        memory = build_narrative_memory("我们在社团认识，常常一起喝咖啡。", "dog", "小周", "阿晚")
        result = retrieve_memories("咖啡", [], narrative=memory)
        self.assertIn("关系背景", result[0])

    def test_dataset_holds_out_complete_recent_sessions(self):
        messages = []
        for day in range(1, 6):
            messages.extend([
                {"sender": "被", "content": f"第{day}天在吗", "timestamp": f"2026-08-{day:02d} 09:00"},
                {"sender": "舔", "content": f"第{day}天在", "timestamp": f"2026-08-{day:02d} 09:01"},
                {"sender": "被", "content": f"第{day}天吃饭吗", "timestamp": f"2026-08-{day:02d} 10:00"},
                {"sender": "舔", "content": f"第{day}天好呀", "timestamp": f"2026-08-{day:02d} 10:01"},
                {"sender": "被", "content": f"第{day}天去哪儿", "timestamp": f"2026-08-{day:02d} 11:00"},
                {"sender": "舔", "content": f"第{day}天都可以", "timestamp": f"2026-08-{day:02d} 11:01"},
            ])
        prepared = prepare_dataset(messages, "舔", "被", "dog")
        self.assertEqual(prepared["report"]["session_count"], 5)
        self.assertGreater(len(prepared["validation"]), 0)
        self.assertGreater(len(prepared["test"]), 0)
        train_sessions = {item["metadata"]["session_id"] for item in prepared["train"]}
        test_sessions = {item["metadata"]["session_id"] for item in prepared["test"]}
        self.assertTrue(train_sessions.isdisjoint(test_sessions))

    def test_dataset_removes_exact_duplicate_messages(self):
        messages = [
            {"sender": "被", "content": "在吗", "timestamp": "2026-08-01 09:00"},
            {"sender": "被", "content": "在吗", "timestamp": "2026-08-01 09:00"},
            {"sender": "舔", "content": "在", "timestamp": "2026-08-01 09:01"},
        ]
        prepared = prepare_dataset(messages, "舔", "被", "dog")
        self.assertEqual(prepared["report"]["duplicate_messages_removed"], 1)
        self.assertEqual(prepared["report"]["example_count"], 1)

    def test_hybrid_retrieval_prefers_related_memory_and_exposes_reason(self):
        examples = build_examples([
            {"sender": "被", "content": "明天喝咖啡吗", "timestamp": "2026-08-01 09:00"},
            {"sender": "舔", "content": "好呀我去买", "timestamp": "2026-08-01 09:01"},
            {"sender": "被", "content": "今晚打游戏吗", "timestamp": "2026-08-02 09:00"},
            {"sender": "舔", "content": "我今晚要加班", "timestamp": "2026-08-02 09:01"},
        ], "舔", "被", "dog")
        items = retrieve_memory_items("想喝咖啡", examples)
        self.assertTrue(items)
        self.assertIn("咖啡", items[0]["content"])
        self.assertIn("reason", items[0])

    def test_prompt_warns_against_repeating_recent_reply(self):
        request = ChatRequest(
            message="还在忙吗",
            model_role="dog",
            player_role="receiver",
            dog_speaker="舔",
            receiver_speaker="被",
            history=[
                {"role": "user", "content": "今天很忙"},
                {"role": "assistant", "content": "那你先忙吧。"},
            ],
        )
        prompt = role_prompt(request, [])
        self.assertIn("那你先忙吧。", prompt)
        self.assertIn("不要原句复读", prompt)

    def test_lora_and_hybrid_have_distinct_memory_paths(self):
        examples = build_examples(self.messages, "舔", "被", "dog")
        self.assertEqual(memories_for_method("lora", "吃饭", examples, None), [])
        self.assertGreater(len(memories_for_method("hybrid", "吃饭", examples, None)), 0)

        lora_prompt = role_prompt(ChatRequest(
            message="吃饭了吗", model="tiangou-role:latest", method="lora",
            model_role="dog", player_role="receiver", dog_speaker="舔", receiver_speaker="被",
        ), [])
        hybrid_prompt = role_prompt(ChatRequest(
            message="吃饭了吗", model="tiangou-role:latest", method="hybrid",
            model_role="dog", player_role="receiver", dog_speaker="舔", receiver_speaker="被",
        ), ["对方：吃了吗\n目标角色：吃了"])
        self.assertIn("不注入聊天记忆", lora_prompt)
        self.assertIn("补充关系事实", hybrid_prompt)

    def test_hybrid_dataset_writes_reproducible_training_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_paths = (
                backend_main.DATA_DIR, backend_main.DATASET_FILE,
                backend_main.PROFILE_FILE, backend_main.TRAINING_CONFIG_FILE,
            )
            backend_main.DATA_DIR = root
            backend_main.DATASET_FILE = root / "dataset.jsonl"
            backend_main.PROFILE_FILE = root / "profile.json"
            backend_main.TRAINING_CONFIG_FILE = root / "training-config.json"
            try:
                result = asyncio.run(backend_main.dataset(DatasetRequest(
                    messages=self.messages,
                    dog_speaker="舔", receiver_speaker="被",
                    dog_name="舔", receiver_name="被",
                    model_role="dog", method="hybrid",
                    model_id="mistral7b-v03", lora_model_tag="tiangou-test:latest",
                )))
                config = json.loads((root / "dog-training-config.json").read_text(encoding="utf-8"))
                self.assertEqual(config["method"], "hybrid")
                self.assertEqual(config["ollama_model_tag"], "tiangou-test:latest")
                self.assertIn("backend.train_lora", result["train_command"])
                self.assertIn("dog-dataset.jsonl", result["train_command"])
                self.assertIn("data_report", result)
                self.assertIn("ollama create tiangou-test:latest", result["register_command"])
                self.assertIn("ADAPTER", (root / "Modelfile.dog").read_text(encoding="utf-8"))
            finally:
                (
                    backend_main.DATA_DIR, backend_main.DATASET_FILE,
                    backend_main.PROFILE_FILE, backend_main.TRAINING_CONFIG_FILE,
                ) = old_paths

    def test_qwen_config_does_not_claim_direct_ollama_adapter_support(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_paths = (
                backend_main.DATA_DIR, backend_main.DATASET_FILE,
                backend_main.PROFILE_FILE, backend_main.TRAINING_CONFIG_FILE,
            )
            backend_main.DATA_DIR = root
            backend_main.DATASET_FILE = root / "dataset.jsonl"
            backend_main.PROFILE_FILE = root / "profile.json"
            backend_main.TRAINING_CONFIG_FILE = root / "training-config.json"
            try:
                result = asyncio.run(backend_main.dataset(DatasetRequest(
                    messages=self.messages,
                    dog_speaker="舔", receiver_speaker="被",
                    dog_name="舔", receiver_name="被",
                    model_role="dog", method="hybrid",
                    model_id="qwen25-15b", lora_model_tag="tiangou-qwen:latest",
                )))
                self.assertFalse(result["adapter_direct_supported"])
                self.assertIsNone(result["register_command"])
                self.assertFalse((root / "Modelfile.dog").exists())
            finally:
                (
                    backend_main.DATA_DIR, backend_main.DATASET_FILE,
                    backend_main.PROFILE_FILE, backend_main.TRAINING_CONFIG_FILE,
                ) = old_paths

    def test_story_only_cannot_claim_hybrid_training(self):
        with self.assertRaises(HTTPException) as context:
            asyncio.run(backend_main.dataset(DatasetRequest(
                messages=[], dog_speaker="舔", receiver_speaker="被",
                dog_name="舔", receiver_name="被", model_role="dog",
                narrative="这是一段足够长的关系经历自述，但它不是逐轮双方聊天记录，不能提供监督回复标签。",
                method="hybrid", model_id="mistral7b-v03",
            )))
        self.assertEqual(context.exception.status_code, 422)

    def test_dog_and_receiver_artifacts_are_isolated(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_data_dir = backend_main.DATA_DIR
            backend_main.DATA_DIR = root
            try:
                for role, tag in (("dog", "tiangou-dog:latest"), ("receiver", "tiangou-receiver:latest")):
                    asyncio.run(backend_main.dataset(DatasetRequest(
                        messages=self.messages,
                        dog_speaker="舔", receiver_speaker="被",
                        dog_name="舔", receiver_name="被",
                        model_role=role, method="hybrid",
                        model_id="mistral7b-v03", lora_model_tag=tag,
                    )))
                self.assertTrue((root / "dog-dataset.jsonl").exists())
                self.assertTrue((root / "receiver-dataset.jsonl").exists())
                dog_config = json.loads((root / "dog-training-config.json").read_text(encoding="utf-8"))
                receiver_config = json.loads((root / "receiver-training-config.json").read_text(encoding="utf-8"))
                self.assertNotEqual(dog_config["adapter_output"], receiver_config["adapter_output"])
                self.assertEqual(dog_config["model_role"], "dog")
                self.assertEqual(receiver_config["model_role"], "receiver")
            finally:
                backend_main.DATA_DIR = old_data_dir

    def test_training_status_requires_weights_receipt_and_registered_tag(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter = root / "adapters" / "role-lora"
            adapter.mkdir(parents=True)
            (adapter / "adapter_model.safetensors").write_bytes(b"test")
            dataset = root / "dataset.jsonl"
            dataset.write_text('{"messages": []}\n', encoding="utf-8")
            (adapter / "training-result.json").write_text(json.dumps({
                "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
                "base_model": "mistralai/Mistral-7B-Instruct-v0.3",
            }), encoding="utf-8")
            config_file = root / "dog-training-config.json"
            config_file.write_text(json.dumps({
                "adapter_output": str(adapter),
                "dataset": str(dataset),
                "base_model_huggingface": "mistralai/Mistral-7B-Instruct-v0.3",
                "model_role": "dog",
                "ollama_model_tag": "tiangou-test:latest",
            }), encoding="utf-8")
            old_data_dir = backend_main.DATA_DIR
            backend_main.DATA_DIR = root
            try:
                with patch.object(backend_main, "ollama_models", AsyncMock(return_value=["tiangou-test:latest"])):
                    status = asyncio.run(backend_main.training_status(
                        backend_main.TrainingStatusRequest(model_tag="tiangou-test:latest", model_role="dog")
                    ))
                self.assertTrue(status["ready"])
            finally:
                backend_main.DATA_DIR = old_data_dir


class ModelAdaptationTests(unittest.TestCase):
    def setUp(self):
        self.low = {"system": "Linux", "ram_gb": 8, "gpu_name": "CPU", "vram_gb": 0, "free_disk_gb": 20, "cuda": False, "mps": False, "ollama_installed": False}
        self.high = {"system": "Windows", "ram_gb": 32, "gpu_name": "RTX", "vram_gb": 16, "free_disk_gb": 200, "cuda": True, "mps": False, "ollama_installed": True}

    def test_catalog_recommends_by_hardware(self):
        low = catalog(self.low)
        high = catalog(self.high)
        self.assertEqual(next(item["id"] for item in low if item["recommended"]), "qwen25-15b")
        self.assertEqual(next(item["id"] for item in high if item["recommended"]), "qwen25-7b")

    def test_lora_estimate_flags_insufficient_vram(self):
        result = estimate("qwen25-3b", "lora", 5000, 0, profile=self.low)
        self.assertFalse(result["compatible"])
        self.assertGreater(result["disk_gb"], 1)

    def test_memory_mode_does_not_count_model_download(self):
        result = estimate("qwen25-7b", "memory", 10000, 0, profile=self.low)
        self.assertTrue(result["compatible"])
        self.assertLess(result["disk_gb"], 2)

    def test_hybrid_estimate_includes_lora_and_memory_index(self):
        lora = estimate("qwen25-3b", "lora", 5000, 0, profile=self.high)
        hybrid = estimate("qwen25-3b", "hybrid", 5000, 0, profile=self.high)
        self.assertGreater(hybrid["disk_gb"], lora["disk_gb"])
        self.assertIn("聊天记忆索引", hybrid["basis"])

    def test_ollama_missing_model_error_is_actionable(self):
        import httpx

        request = httpx.Request("POST", "http://127.0.0.1:11434/api/chat")
        response = httpx.Response(404, json={"error": "model 'qwen2.5:7b' not found"}, request=request)
        error = httpx.HTTPStatusError("not found", request=request, response=response)
        self.assertIn("ollama pull qwen2.5:7b", ollama_http_error(error, "qwen2.5:7b"))


class TrainingJobTests(unittest.TestCase):
    def test_diagnostics_rejects_unsafe_dataset_path(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as outside:
            data_dir = Path(directory)
            (data_dir / "adapters").mkdir()
            outside_dataset = Path(outside) / "dataset.jsonl"
            outside_dataset.write_text('{"messages": []}\n', encoding="utf-8")
            model = SimpleNamespace(hf_id="example/model", min_lora_vram_gb=8, full_disk_gb=6)
            config = {
                "method": "lora", "model_role": "dog", "base_model_huggingface": "example/model",
                "dataset": str(outside_dataset), "adapter_output": str(data_dir / "adapters" / "dog-lora"),
            }
            hardware = {"cuda": True, "mps": False, "system": "Linux", "vram_gb": 12, "free_disk_gb": 100}
            with patch("backend.training_jobs.importlib.util.find_spec", return_value=object()), patch(
                "backend.training_jobs.torch_capabilities", return_value={"cuda": True, "mps": False, "torch": "test"}
            ):
                result = diagnose_training(data_dir, "dog", config, model, hardware)
            self.assertFalse(result["ready"])
            self.assertTrue(any("路径不安全" in item or "不存在" in item for item in result["blockers"]))

    def test_job_manager_persists_completed_process_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data_dir = root / "local_data"
            output = data_dir / "adapters" / "dog-lora"
            output.mkdir(parents=True)
            manager = TrainingJobManager(root, data_dir)
            script = (
                "import json,time,pathlib; time.sleep(0.15); "
                f"pathlib.Path({str(output / 'training-result.json')!r}).write_text(json.dumps({{'ok': True}}), encoding='utf-8')"
            )
            state = manager.start("dog", [__import__("sys").executable, "-c", script], False, "test", output, "hash", "base")
            self.assertEqual(state["status"], "running")
            for _ in range(30):
                state = manager.status("dog")
                if state["status"] != "running":
                    break
                time.sleep(0.05)
            self.assertEqual(state["status"], "completed")
            restored = TrainingJobManager(root, data_dir).status("dog")
            self.assertEqual(restored["status"], "completed")


class ProjectManagementTests(unittest.TestCase):
    def test_projects_are_isolated_and_legacy_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "profile.json").write_text("{}", encoding="utf-8")
            first = create_project(root, "第一段关系")
            second = create_project(root, "第二段关系")
            write_json(project_dir(root, first["id"]) / "source.json", {"messages": [{"sender": "甲", "content": "只属于一"}]})
            write_json(project_dir(root, second["id"]) / "source.json", {"messages": [{"sender": "乙", "content": "只属于二"}]})
            projects = list_projects(root)
            self.assertEqual({item["id"] for item in projects}, {"legacy", first["id"], second["id"]})
            self.assertNotEqual(project_dir(root, first["id"]), project_dir(root, second["id"]))
            self.assertTrue((root / "profile.json").exists())

    def test_project_delete_requires_exact_name_and_refuses_legacy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = create_project(root, "需要确认")
            with self.assertRaises(ValueError):
                delete_project(root, project["id"], "确认")
            with self.assertRaises(ValueError):
                delete_project(root, "legacy", "原有项目")
            result = delete_project(root, project["id"], "需要确认")
            self.assertTrue(result["deleted"])
            self.assertFalse(project_dir(root, project["id"]).exists())

    def test_export_excludes_adapters_by_default(self):
        import zipfile

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = create_project(root, "可导出")
            path = project_dir(root, project["id"])
            write_json(path / "source.json", {"narrative": "本地故事"})
            adapter = path / "adapters" / "dog-lora"
            adapter.mkdir(parents=True)
            (adapter / "adapter_model.safetensors").write_bytes(b"weight")
            archive, _ = create_export(root, project["id"])
            try:
                with zipfile.ZipFile(archive) as handle:
                    names = handle.namelist()
                self.assertTrue(any(name.endswith("source.json") for name in names))
                self.assertFalse(any("adapter_model" in name for name in names))
            finally:
                archive.unlink(missing_ok=True)

    def test_dataset_artifacts_are_written_inside_selected_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = create_project(root, "隔离写入")
            old_data_dir = backend_main.DATA_DIR
            backend_main.DATA_DIR = root
            try:
                result = asyncio.run(backend_main.dataset(DatasetRequest(
                    project_id=project["id"], messages=[
                        {"sender": "被", "content": "在吗", "timestamp": "2026-08-01 09:00"},
                        {"sender": "舔", "content": "在", "timestamp": "2026-08-01 09:01"},
                    ],
                    dog_speaker="舔", receiver_speaker="被", dog_name="舔", receiver_name="被",
                    model_role="dog", method="memory", model_id="qwen25-15b",
                )))
                selected = project_dir(root, project["id"])
                self.assertTrue((selected / "dog-profile.json").exists())
                self.assertTrue((selected / "source.json").exists())
                self.assertFalse((root / "dog-profile.json").exists())
                self.assertEqual(Path(result["dataset"]).parent, selected)
            finally:
                backend_main.DATA_DIR = old_data_dir


if __name__ == "__main__":
    unittest.main()
