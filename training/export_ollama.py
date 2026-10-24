# pyright: reportMissingImports=false
"""Merge a trained LoRA into Qwen3.5-4B, quantize to GGUF, and register it with Ollama.

Runs in the training environment. Uses llama.cpp's converter and `llama-quantize` (Unsloth Studio
installs a prebuilt copy in ~/.unsloth/llama.cpp):

    python training/export_ollama.py outputs/maze-qwen4b/checkpoint-150 --name maze-qwen4b

The Modelfile keeps Ollama's built-in `qwen3.5` renderer and parser, so prompts render exactly as for
`qwen3.5:4b`, and copies its sampling parameters so the two compare like for like.
"""

import argparse
import subprocess
import sys
from pathlib import Path

from unsloth import FastLanguageModel

LLAMA_CPP = Path.home() / ".unsloth" / "llama.cpp"
MODELFILE = """FROM {gguf}
TEMPLATE {{{{ .Prompt }}}}
RENDERER qwen3.5
PARSER qwen3.5
PARAMETER presence_penalty 1.5
PARAMETER temperature 1
PARAMETER top_k 20
PARAMETER top_p 0.95
"""


def run(*cmd: str | Path) -> None:
    print("+", " ".join(map(str, cmd)), flush=True)
    subprocess.run([str(c) for c in cmd], check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("adapter", type=Path, help="saved LoRA: a training checkpoint or --out/lora")
    parser.add_argument("--name", default="maze-qwen4b", help="Ollama model name")
    parser.add_argument("--quant", default="Q4_K_M")
    args = parser.parse_args()

    work = args.adapter.parent / f"export-{args.adapter.name}"
    merged, f16 = work / "merged", work / "model-bf16.gguf"
    quantized = work / f"model-{args.quant.lower()}.gguf"
    if not merged.exists():
        model, tokenizer = FastLanguageModel.from_pretrained(str(args.adapter), load_in_4bit=True)
        model.save_pretrained_merged(str(merged), tokenizer, save_method="merged_16bit")
    if not f16.exists():
        run(sys.executable, LLAMA_CPP / "convert_hf_to_gguf.py", merged, "--outtype", "bf16", "--outfile", f16)
    if not quantized.exists():
        run(LLAMA_CPP / "build" / "bin" / "Release" / "llama-quantize.exe", f16, quantized, args.quant)
    modelfile = work / "Modelfile"
    modelfile.write_text(MODELFILE.format(gguf=quantized.resolve()), encoding="utf-8")
    run("ollama", "create", args.name, "-f", modelfile)


if __name__ == "__main__":
    main()
