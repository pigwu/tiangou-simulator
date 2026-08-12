"""可选的 QLoRA 训练入口；基础 UI 默认使用更广泛兼容的聊天记忆模式。"""
from __future__ import annotations

import argparse
import platform
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="local_data/dataset.jsonl")
    parser.add_argument("--model", default="Qwen/Qwen2.5-3B-Instruct", help="Hugging Face 模型 ID；首次运行时由 Transformers 按用户选择下载")
    parser.add_argument("--output", default="local_data/adapters/role-lora")
    parser.add_argument("--epochs", type=float, default=2.0)
    args = parser.parse_args()

    import torch
    from datasets import load_dataset
    from peft import LoraConfig
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        raise SystemExit(f"训练集不存在：{dataset_path}。请先在 UI 中生成角色数据。")
    cuda = torch.cuda.is_available()
    mps = bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
    if not cuda and not mps:
        raise SystemExit("LoRA 微调需要 NVIDIA CUDA 或 Apple Silicon MPS；CPU 设备请使用聊天记忆模式。")
    if platform.system() == "Windows" and cuda:
        print("提示：Windows 上 bitsandbytes 兼容性取决于版本；遇到问题请改用 WSL2。")

    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    quantization = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.bfloat16) if cuda else None
    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        trust_remote_code=True,
        quantization_config=quantization,
        torch_dtype=torch.bfloat16 if cuda else torch.float16,
        device_map="auto",
    )
    data = load_dataset("json", data_files=str(dataset_path), split="train")
    peft = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, target_modules="all-linear", task_type="CAUSAL_LM")
    config = SFTConfig(
        output_dir=args.output,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        learning_rate=2e-4,
        logging_steps=5,
        save_strategy="epoch",
        max_length=2048,
        gradient_checkpointing=True,
        report_to="none",
    )
    trainer = SFTTrainer(model=model, args=config, train_dataset=data, peft_config=peft, processing_class=tokenizer)
    trainer.train()
    trainer.save_model(args.output)
    tokenizer.save_pretrained(args.output)
    print(f"LoRA 适配器已保存到 {args.output}")


if __name__ == "__main__":
    main()
