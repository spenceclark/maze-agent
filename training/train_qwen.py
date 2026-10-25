# pyright: reportMissingImports=false, reportMissingModuleSource=false
"""QLoRA fine-tune of Qwen3.5-4B on the maze expert dataset with Unsloth.

Runs in its own CUDA environment (Python 3.12 + unsloth), not the project's:

    python training/train_qwen.py --out outputs/maze-qwen4b            # full run
    python training/train_qwen.py --out outputs/smoke --max-steps 5    # smoke test
    python training/train_qwen.py --adapter outputs/maze-qwen4b/checkpoint-150 --check 100   # check only

Examples are rendered exactly as Ollama's built-in `qwen3.5` renderer does with thinking off (system,
one block per user message, then an empty think block), so no HF chat template is involved. Loss covers
only the assistant reply.
"""

import argparse  # noqa: I001 (unsloth must be imported before datasets and trl)
import json
import random
from pathlib import Path

from unsloth import FastLanguageModel  # must come first: it patches transformers and trl

from datasets import Dataset
from trl import SFTConfig, SFTTrainer

ASSISTANT_THINK_OFF = "<|im_start|>assistant\n<think>\n\n</think>\n\n"
END = "<|im_end|>"
LOOKUP = "junction explored"  # the 3% of decisions that read a junction line back from the notebook
NOTE = '"notebook_append":"junction'  # the ~7% that write one; both are rare, so both are oversampled


def render(messages: list[dict[str, str]]) -> dict[str, str]:
    *prompt, reply = messages
    text = "".join(f"<|im_start|>{m['role']}\n{m['content']}{END}\n" for m in prompt)
    return {"prompt": text + ASSISTANT_THINK_OFF, "completion": reply["content"] + END}


def load(path: Path, n: int, rare_copies: int, seed: int = 0) -> list[dict[str, str]]:
    with path.open(encoding="utf-8") as f:
        rows = [json.loads(line)["messages"] for line in f]
    random.Random(seed).shuffle(rows)
    rare = [r for r in rows if LOOKUP in r[-1]["content"] or NOTE in r[-1]["content"]]
    picked = rows[:n] + rare * rare_copies
    random.Random(seed + 1).shuffle(picked)
    return [render(r) for r in picked]


def check(model, tokenizer, examples: list[dict[str, str]]) -> None:
    """Greedy replies to held-out prompts: valid JSON rate and exact-move agreement with the expert."""
    FastLanguageModel.for_inference(model)
    valid = same = lookups = lookups_same = notes_due = notes_same = 0
    for ex in examples:
        inputs = tokenizer(text=ex["prompt"], return_tensors="pt").to("cuda")
        out = model.generate(**inputs, max_new_tokens=160, do_sample=False)
        text = tokenizer.decode(out[0][inputs["input_ids"].shape[1] :], skip_special_tokens=True)
        if ex is examples[0]:
            print(f"check sample: {text!r}")
        expected = json.loads(ex["completion"].removesuffix(END))
        is_lookup = LOOKUP in expected["check"]
        lookups += is_lookup
        notes_due += expected["notebook_append"] is not None
        try:
            reply = json.loads(text.strip())
            move = reply["move"]
            valid += 1
        except (ValueError, KeyError, TypeError):
            continue
        if expected["notebook_append"] is not None:
            if reply.get("notebook_append") == expected["notebook_append"]:
                notes_same += 1
            else:
                print(
                    f"note miss: want {expected['notebook_append']!r}, got {reply.get('notebook_append')!r}"
                )
        same += move == expected["move"]
        lookups_same += is_lookup and move == expected["move"]
    n = len(examples)
    print(
        f"check: valid JSON {valid}/{n}, move matches expert {same}/{n},"
        f" junction lookups {lookups_same}/{lookups}, notes written exactly {notes_same}/{notes_due}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="Qwen/Qwen3.5-4B")
    parser.add_argument("--train", type=Path, default=Path("data/train.jsonl"))
    parser.add_argument("--eval", type=Path, default=Path("data/eval.jsonl"))
    parser.add_argument("--out", type=Path, help="training output directory")
    parser.add_argument(
        "--adapter", type=Path, help="skip training: check this saved LoRA (e.g. a checkpoint)"
    )
    parser.add_argument("--examples", type=int, default=2000, help="random training examples")
    parser.add_argument(
        "--rare-copies", type=int, default=2, help="extra copies of each junction note and lookup"
    )
    parser.add_argument("--max-seq", type=int, default=2304)  # longest example is ~2.1K tokens
    parser.add_argument("--max-steps", type=int, default=-1, help="stop early (smoke test)")
    parser.add_argument("--check", type=int, default=40, help="held-out prompts to generate after training")
    # In-loop eval is off by default: on an 8 GB card the first eval left VRAM full and steps went 18x slower.
    parser.add_argument("--eval-steps", type=int, default=0, help="eval every N steps (0: never)")
    parser.add_argument(
        "--notes-only", action="store_true", help="check only held-out turns where a note is due"
    )
    args = parser.parse_args()

    if args.adapter:
        model, tokenizer = FastLanguageModel.from_pretrained(
            str(args.adapter), max_seq_length=args.max_seq, load_in_4bit=True
        )
        held_out = load(args.eval, 10_000, 0)[100:]
        if args.notes_only:
            held_out = [ex for ex in held_out if '"notebook_append":null' not in ex["completion"]]
        check(model, tokenizer, held_out[: args.check])
        return
    if args.out is None:
        parser.error("--out is required when training")
    model, tokenizer = FastLanguageModel.from_pretrained(
        args.model, max_seq_length=args.max_seq, load_in_4bit=True
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        lora_alpha=16,
        lora_dropout=0,
        use_gradient_checkpointing="unsloth",
        # full-attention layers, gated-delta-net (linear attention) layers, and every MLP
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "in_proj_qkv",
            "in_proj_z",
            "out_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
    )
    train = Dataset.from_list(load(args.train, args.examples, args.rare_copies))
    held_out = load(args.eval, 300, 0)
    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        train_dataset=train,
        eval_dataset=Dataset.from_list(held_out[:100]),
        args=SFTConfig(
            output_dir=str(args.out),
            max_length=args.max_seq,
            completion_only_loss=True,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=8,
            num_train_epochs=1,
            max_steps=args.max_steps,
            learning_rate=2e-4,
            lr_scheduler_type="linear",
            warmup_steps=20,
            optim="adamw_8bit",
            bf16=True,
            logging_steps=1 if args.max_steps > 0 else 10,
            eval_strategy="steps" if args.eval_steps else "no",
            eval_steps=args.eval_steps or None,
            save_steps=150,
            save_total_limit=2,
            dataset_num_proc=1,
            report_to="none",
            seed=0,
        ),
    )
    # The loss must cover the reply only (~60-90 tokens), not the ~1.8K-token prompt.
    batch = trainer.data_collator([trainer.train_dataset[0]])
    labelled = int((batch["labels"] != -100).sum())
    print(f"loss tokens in example 0: {labelled} of {batch['input_ids'].shape[-1]}", flush=True)
    trainer.train()
    model.save_pretrained(args.out / "lora")
    tokenizer.save_pretrained(args.out / "lora")
    if args.check:
        check(model, tokenizer, held_out[100 : 100 + args.check])


if __name__ == "__main__":
    main()
