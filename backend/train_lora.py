"""可选的 QLoRA 训练入口；基础 UI 默认使用更广泛兼容的聊天记忆模式。"""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import time
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", default="local_data/dataset.jsonl")
    parser.add_argument("--validation", default="", help="可选的独立验证集 JSONL")
    parser.add_argument("--model", default="Qwen/Qwen2.5-3B-Instruct", help="Hugging Face 模型 ID；首次运行时由 Transformers 按用户选择下载")
    parser.add_argument("--output", default="local_data/adapters/role-lora")
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--resume-from", default="", help="可选的 checkpoint 目录")
    parser.add_argument("--progress-file", default="", help="由本地 UI 任务管理器写入的进度文件")
    args = parser.parse_args()

    import torch
    from datasets import load_dataset
    from peft import LoraConfig
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig, EarlyStoppingCallback, TrainerCallback
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
    if cuda:
        print(f"训练设备：{torch.cuda.get_device_name(0)} · 显存 {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f} GB")
    else:
        print("训练设备：Apple Silicon MPS（统一内存）")

    progress_path = Path(args.progress_file) if args.progress_file else None

    def write_progress(payload: dict) -> None:
        if not progress_path:
            return
        progress_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = progress_path.with_suffix(progress_path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(progress_path)

    class ProgressCallback(TrainerCallback):
        def on_train_begin(self, args, state, control, **kwargs):
            write_progress({"phase": "training", "status": "running", "step": state.global_step, "total_steps": state.max_steps, "percent": round(state.global_step / max(state.max_steps, 1) * 100, 1), "started_at": datetime.now(timezone.utc).isoformat()})

        def on_log(self, args, state, control, logs=None, **kwargs):
            logs = logs or {}
            write_progress({
                "phase": "training", "status": "running", "step": state.global_step, "total_steps": state.max_steps,
                "percent": round(state.global_step / max(state.max_steps, 1) * 100, 1), "epoch": round(float(state.epoch or 0), 3),
                "loss": logs.get("loss"), "eval_loss": logs.get("eval_loss"), "learning_rate": logs.get("learning_rate"),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })

        def on_train_end(self, args, state, control, **kwargs):
            write_progress({"phase": "saving", "status": "running", "step": state.global_step, "total_steps": state.max_steps, "percent": 99, "epoch": state.epoch, "updated_at": datetime.now(timezone.utc).isoformat()})

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
    validation_path = Path(args.validation) if args.validation else None
    validation_data = None
    if validation_path:
        if not validation_path.exists():
            raise SystemExit(f"验证集不存在：{validation_path}")
        validation_data = load_dataset("json", data_files=str(validation_path), split="train")
    peft = LoraConfig(r=16, lora_alpha=32, lora_dropout=0.05, target_modules="all-linear", task_type="CAUSAL_LM")
    config = SFTConfig(
        output_dir=args.output,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        learning_rate=2e-4,
        logging_steps=5,
        save_strategy="epoch",
        eval_strategy="epoch" if validation_data is not None else "no",
        load_best_model_at_end=validation_data is not None,
        metric_for_best_model="eval_loss" if validation_data is not None else None,
        greater_is_better=False if validation_data is not None else None,
        save_total_limit=2,
        max_length=2048,
        gradient_checkpointing=True,
        report_to="none",
    )
    callbacks = [ProgressCallback()]
    if validation_data is not None:
        callbacks.append(EarlyStoppingCallback(early_stopping_patience=2))
    trainer = SFTTrainer(
        model=model, args=config, train_dataset=data, eval_dataset=validation_data,
        peft_config=peft, processing_class=tokenizer, callbacks=callbacks,
    )
    started = time.perf_counter()
    resume_path = Path(args.resume_from).resolve() if args.resume_from else None
    if resume_path and not resume_path.is_dir():
        raise SystemExit(f"恢复 checkpoint 不存在：{resume_path}")
    trainer.train(resume_from_checkpoint=str(resume_path) if resume_path else None)
    trainer.save_model(args.output)
    tokenizer.save_pretrained(args.output)
    output_path = Path(args.output)
    runtime_seconds = round(time.perf_counter() - started, 1)
    eval_losses = [item["eval_loss"] for item in trainer.state.log_history if "eval_loss" in item]
    train_losses = [item["loss"] for item in trainer.state.log_history if "loss" in item]
    receipt = {
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "base_model": args.model,
        "dataset": str(dataset_path.resolve()),
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "example_count": len(data),
        "validation_count": len(validation_data) if validation_data is not None else 0,
        "epochs": args.epochs,
        "output": str(output_path.resolve()),
        "train_loss": train_losses[-1] if train_losses else None,
        "best_eval_loss": min(eval_losses) if eval_losses else None,
        "runtime_seconds": runtime_seconds,
        "device": torch.cuda.get_device_name(0) if cuda else "Apple Silicon MPS",
        "completed_steps": trainer.state.global_step,
    }
    (output_path / "training-result.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    write_progress({
        "phase": "completed", "status": "completed", "step": trainer.state.global_step, "total_steps": trainer.state.max_steps,
        "percent": 100, "epoch": trainer.state.epoch, "loss": receipt["train_loss"], "eval_loss": receipt["best_eval_loss"],
        "runtime_seconds": runtime_seconds, "completed_at": receipt["completed_at"],
    })
    print(f"LoRA 适配器已保存到 {args.output}")
    print(f"本地训练凭证已保存到 {output_path / 'training-result.json'}")
    print(f"实际训练用时 {runtime_seconds / 60:.1f} 分钟；完成 {trainer.state.global_step} 步。")


if __name__ == "__main__":
    main()
