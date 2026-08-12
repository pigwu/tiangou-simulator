import json
import tempfile
import unittest
from pathlib import Path

from backend.dataset import build_examples, build_narrative_memory, retrieve_memories
from backend.parsers import parse_upload
from backend.models import catalog, estimate


class ParserTests(unittest.TestCase):
    def test_parse_text_and_ignore_system_lines(self):
        data = "[22:01] A: 你好\n[22:02] B: 嗯\n[22:03] A: 撤回了一条消息".encode()
        messages = parse_upload("chat.txt", data)
        self.assertEqual([item["sender"] for item in messages], ["A", "B"])

    def test_parse_json_aliases(self):
        data = json.dumps([{"发送人": "甲", "内容": "在吗"}, {"发送人": "乙", "内容": "在"}], ensure_ascii=False).encode()
        self.assertEqual(len(parse_upload("chat.json", data)), 2)


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


if __name__ == "__main__":
    unittest.main()
