NO. 07 · DRAFT

# Teaching the maze

Fine-tuning a 4B local model on an 8 GB card, using twelve thousand moves from a depth-first search, and the
one token it wouldn't learn.

By Spencer Clark

LOCAL-LLM / FINE-TUNING / UNSLOTH / OLLAMA

---

## Background

[Part 1](https://spencerclark.dev/blog/maze-escape/) ended with Qwen3.5-9B stuck in the maze.

The game is the same here. Three agents start in different cells of a grid maze, and every agent has to reach
the exit at least once. Each turn every agent gets one fresh call with no history. It sees its cell, its own
8 KB notebook (its only memory) and any radio messages, and replies with one JSON action.

The hosted models got there with enough scaffolding. The local one never did. I fixed Qwen one layer at a time:

| Problem | Scaffold | Result |
| --- | --- | --- |
| Walked into walls on 37.5% of moves | A required `check` line before the move, restating its four edges | 7.5% |
| Took exits it had already used | The engine lists the exits already used at this cell | Took an unexplored exit 89% of the time |
| Still occasionally chose a wall | The move enum only offers open directions | 0% |

And still only one agent ever got out. Qwen spent more than half its turns on cells where every exit had
already been used, with no way to plan a route back to unexplored ground. lfm2.5, command-r7b and Nemotron 3.5
Bolt did worse. The only scaffold left was to have the engine point at the nearest unexplored exit, and at that
point the engine is solving the maze.

The frustrating part was that Qwen followed every instruction. Told to note each junction and which exits it
had tried, it wrote 125 notes in a game. It just never read them back to decide where to go.

So I stopped telling it what to do and showed it instead: supervised fine-tuning on demonstrations. This post
is the how. I've included the code for each step, because most of it carries over to fine-tuning a small model
for anything else:
- generating training data from a program rather than from people or a bigger model;
- making the training prompt identical to the prompt the model is served;
- training on a consumer card with Unsloth;
- getting the result into Ollama;
- and the part that took longest: finding out what the model *hadn't* learned.

## The plan

- **Model:** Qwen3.5-4B, small enough to train on the same 8 GB card that runs the games.
- **Teacher:** an algorithm, not a bigger model. No API calls, no labelling, as much data as I want, and every
  answer correct by construction.
- **Prompt:** exactly what a live game sends, byte for byte.
- **Stack:** Unsloth for training (QLoRA), llama.cpp to convert to GGUF, Ollama to serve, and the same game
  engine to evaluate.

Hardware: Windows 11 and an RTX 3070 (8 GB), with about 1.3 GB of it already taken by the desktop.

## Step 1: an expert that only knows what the model knows

The one rule for the expert: **it can't look at the maze.** If it could, the demonstrations would include
decisions the model can't work out from its prompt, and the best the model could do is guess. So the expert is
a function of one observation, the same observation the model gets, notebook included.

It plays depth-first search, and Part 1's scaffolds do most of the work. The agent knows its exact coordinates,
and the engine lists the exits it has already used from its current cell. In a perfect maze (no loops), an open
exit that isn't on that list always leads somewhere new. So the search is:
- take an untried exit if there is one;
- otherwise go back the way you came.

Going back is easy in a corridor (leave by the exit you didn't arrive through) and in a dead end. At a junction
it isn't. Once you've tried two or three of its exits, the used-exits list no longer tells you which one you
originally came in by. That is the only thing the agent has to remember, so it goes in the notebook, one line
per junction, on first arrival:

```
junction [3,-2] back W
```

Trimmed, the decision looks like this (the real one is in `src/maze_lab/finetune/expert.py`):

```python
def decide(obs: Observation) -> Direction:
    edges = {"N": obs.local.north, "E": obs.local.east, "S": obs.local.south, "W": obs.local.west}
    open_dirs = [d for d in "NESW" if edges[d] == "open"]
    untried = [d for d in open_dirs if d not in obs.used_exits]
    arrived = obs.last_action.movement.arrived_from
    x, y = obs.coordinates.position
    backs = junction_backs(obs.notebook.text)  # {(3, -2): "W", ...} parsed from the notebook

    if untried:
        return untried[0]                                    # anything new, in N, E, S, W order
    if len(open_dirs) == 1:
        return open_dirs[0]                                  # dead end: back out
    if len(open_dirs) == 2:
        return next(d for d in open_dirs if d != arrived)    # corridor: the way I didn't come in
    return backs[(x, y)]                                     # exhausted junction: what I wrote down
```

The expert's reply also fills in the `check` line from Part 1, so the model sees the reasoning as well as the
answer:

```json
{"schema_version":"1.2","tick":2,
 "check":"at [-1,0]; N brick, E open, S open, W open; arrived from E; used E; untried S,W; new junction, noting back E; go S, untried",
 "notebook_append":"junction [-1,0] back E","move":"S","radio":null}
```

**The notebook format.** Part 1 turned Qwen's notebook into a rolling log, where the engine drops the oldest
lines when it fills up. That could silently drop a junction line. But junction lines never change, so nothing
ever needs rewriting, and a 15×15 maze needs well under 1 KB of the 8 KB (the largest notebook in the data was
875 bytes). The generator fails outright if a line is ever dropped.

**What the expert doesn't do:** radio, landmark relays, or anything with teammates. It searches alone. It does
note landmarks, because the prompt asks for that. Turns after an agent reaches the exit aren't recorded.

## Step 2: record exactly what the model will see

This is the most important rule in the whole pipeline: **the training prompt has to be the serving prompt.** Not
the same information, the same bytes. So the dataset builds prompts with the same two functions the live adapter
uses:

```python
def prompt_messages(rules: AgentRules, obs: Observation, prompt_version: str) -> list[Message]:
    system = system_instruction(rules, obs.agent_id, prompt_version, with_check=True)
    blocks = user_blocks(obs, "append_log")
    return [{"role": "system", "content": system}, *({"role": "user", "content": b} for b in blocks)]
```

Why three user messages rather than one? The adapter sends one user message made of three text parts (stable
parts first, for prompt caching). I'd have guessed those get joined. They don't. Ollama's OpenAI-compatible
endpoint turns each part into a separate message with the same role:

```go
case "text":
    messages = append(messages, api.Message{Role: msg.Role, Content: text})
```

So the model sees three consecutive user turns. Train it on one joined message and you've trained it on a format
it never sees in play.

The prompt settings come from a real run config (`--config`) rather than being typed in again. Landmarks add a
paragraph to the system prompt. Meeting notebooks change the second block. Distance sensors add fields to the
third. Any of those could drift.

I didn't want to rely on reading the code, so a test plays a whole game in which every decision also goes through
the real adapter, against a fake Ollama server that replies with the expert's answer. The wire request has to
match the dataset row:

```python
def handler(request: httpx.Request) -> httpx.Response:
    sent.append(json.loads(request.content))
    message = {"role": "assistant", "content": reply["text"]}
    return httpx.Response(200, json={..., "choices": [{"index": 0, "message": message, "finish_reason": "stop"}]})

def through_adapter(obs: Observation, messages: list[dict[str, str]]) -> str:
    reply["text"] = expert(obs, messages)
    attempt = asyncio.run(live.decide(obs, agent_rules))
    assert ollama_split(sent[-1]["messages"]) == messages   # what Qwen sees == what we train on
    assert attempt.response_text == reply["text"]
    return reply["text"]

rows = play(game_config(TARGET, seed=4, size=8), through_adapter)
```

The first run of that test failed. I'd built the adapter in the test without the run's prompt version, so it used
its default, v4, while the games use v10. The two system prompts differed by about a thousand characters. Here the
bug was in the test, but that is exactly the mismatch it exists to catch: a model trained on one prompt and served
another.

A training row ends up looking like this (trimmed):

```
system     You are agent A in a three-agent team (A, B, C) exploring a grid maze. ...      (4,945 characters)
user       Your notebook, 95 of 8192 bytes used (plain text between the markers):
           <<<NOTEBOOK A
           junction [-1,0] back E
           junction [0,-2] back N
           landmark easel at [-2,-4]
           landmark map at [-3,-7]
           NOTEBOOK A>>>
user       Notebooks of agents sharing your cell, readable this turn only:
           (none)
user       Current observation; notebooks are given above (JSON data):
           {"schema_version":"1.0","agent_id":"A","decision_tick":30, ... "used_exits":["W"], ...
            "coordinates":{"position":[-2,-7], ...}}
assistant  {"schema_version":"1.2","tick":30,"check":"...","notebook_append":"junction [-2,-7] back W","move":"N","radio":null}
```

## Step 3: generate, then replay what you generated

The generator plays full games with three experts through the real engine. Every decision becomes one chat
example. Trimmed from `play()` in `src/maze_lab/finetune/dataset.py`:

```python
for agent_id in AGENT_IDS:
    obs = observe(maze, rules, state, agent_id)
    if obs.has_reached_exit:
        action = stay(obs)                       # finished agents wait; those turns teach no search
    else:
        messages = prompt_messages(agent_rules, obs, config.prompt_version)
        reply = decide(obs, messages)            # the expert, or (when verifying) the recorded reply
        action = parse_reply(reply)              # the same strict parser live replies go through
        rows.append({"messages": [*messages, {"role": "assistant", "content": reply}], "meta": meta})
    submissions[agent_id] = Submission(action=action, failure=None)
state, events = resolve(maze, rules, state, submissions)
```

`decide` is a parameter, which makes verification cheap. After writing the file, the generator plays every game
again with a `decide` that reads the recorded replies back and checks each prompt against a freshly built one. It
fails if any prompt differs, any move hits a wall, any notebook line is dropped, or any agent misses the exit.

```bash
uv run maze-lab dataset --games 40 --sizes 8,10,12,15 --out data/train.jsonl
```

```
## train
- games: 40 (seeds 1-40)
- expert success: 40/40 games, every agent reached the exit (100%)
- decisions (examples): 12612; by maze size: 8x8 1656, 10x10 2466, 12x12 3055, 15x15 5435
- tokens per example, prompt + reply (Qwen estimate): min 1739, median 1873, p90 1968, p99 2020, max 2080
- largest notebook shown: 875 bytes (cap 8192; no line ever dropped)
- verified: 40 games replayed from data/train.jsonl

## eval (held-out seeds)
- games: 8 (seeds 41-48)
- decisions (examples): 2829
- verified: 8 games replayed from data/eval.jsonl
```

A game takes about 0.2 seconds, so the whole dataset takes under a minute. A seed plus a size fully determines a
maze, so seeds 41–48 are mazes the model never trains on. The token counts are estimated from bytes, using the
ratio Ollama reported on earlier Qwen runs. The real tokeniser later came in about 15% lower: 1,586 tokens for
one example.

The mix of decisions matters later:

| Decision | Share of examples |
| --- | --- |
| Take an untried exit | 66% |
| Walk back out of a corridor | 25% |
| Leave a dead end | 6% |
| Read a junction line back from the notebook | 3% |

That 3% is exactly the skill Qwen lacked in Part 1. So the training script oversamples those rows.

## Step 4: a separate environment for training

The project runs on Python 3.14. The training stack wants 3.12 and CUDA builds of PyTorch, so it gets its own
virtual environment outside the repo:

```bash
uv venv --python 3.12 ../unsloth-env
uv pip install --python ../unsloth-env/Scripts/python.exe torch torchvision --index-url https://download.pytorch.org/whl/cu128
uv pip install --python ../unsloth-env/Scripts/python.exe unsloth
```

That gave PyTorch 2.11 (CUDA 12.8), transformers 5.17, TRL 1.15 and Unsloth with `triton-windows`, and it
worked on Windows first time. The one missing piece was `causal_conv1d`, which falls back to a slower reference
implementation.

Two things about the model I didn't know going in:
- **Qwen3.5 is a hybrid.** 24 of its 32 layers use linear attention (Gated DeltaNet), and only 8 use full
  attention. It also carries a vision tower. The usual LoRA targets (`q_proj`, `k_proj`, `v_proj`, `o_proj`)
  only exist in those 8 layers. To train the other 24, you need their projection names (`in_proj_qkv`,
  `in_proj_z`, `out_proj`). Read your model's `config.json` before you copy a LoRA recipe.
- **Unsloth's Qwen3.5 guide advises against 4-bit QLoRA,** because Qwen3.5 loses more than usual to
  quantization, and bf16 LoRA on the 4B needs about 10 GB. I had 8. The options were QLoRA anyway, the 2B in
  bf16, or a rented GPU. I chose QLoRA and decided to judge it by the games.

A smaller trap: my formatter is set to the project's Python 3.14, and it rewrote `except (ValueError,
KeyError):` into 3.14's new unbracketed form, which is a syntax error on 3.12. The training script died on
import. If your training code lives in the same repo as your app, give it its own target version:

```toml
[tool.ruff.per-file-target-version]
"training/*.py" = "py312"
```

## Step 5: render the text the way the server will

The usual way to turn messages into training text is the tokenizer's chat template. But Ollama doesn't use a
template for this model. `ollama show qwen3.5:4b --modelfile` gives:

```
TEMPLATE {{ .Prompt }}
RENDERER qwen3.5
PARSER qwen3.5
```

That's a renderer built into Ollama's Go code. Reading it showed what Qwen actually sees with thinking off: each
message wrapped in `<|im_start|>role ... <|im_end|>`, consecutive user messages kept separate, and the reply
starting after an empty think block. So rather than hoping `apply_chat_template` matches, the training script
builds the string itself:

```python
ASSISTANT_THINK_OFF = "<|im_start|>assistant\n<think>\n\n</think>\n\n"
END = "<|im_end|>"

def render(messages: list[dict[str, str]]) -> dict[str, str]:
    *prompt, reply = messages
    text = "".join(f"<|im_start|>{m['role']}\n{m['content']}{END}\n" for m in prompt)
    return {"prompt": text + ASSISTANT_THINK_OFF, "completion": reply["content"] + END}
```

Splitting each example into `prompt` and `completion` lets TRL compute the loss on the completion only. That
matters here. The prompt is about 1,600 tokens and the reply about 70, so without the mask about 96% of the
training signal would go into predicting observation JSON.

Don't assume the mask works. My first check looked for a `completion_mask` column in the dataset, found none, and
printed nothing. Ask the collator instead, since it builds the batches the model actually trains on:

```python
batch = trainer.data_collator([trainer.train_dataset[0]])
labelled = int((batch["labels"] != -100).sum())
print(f"loss tokens in example 0: {labelled} of {batch['input_ids'].shape[-1]}")
```

```
loss tokens in example 0: 67 of 1586
```

## Step 6: the training run

```python
model, tokenizer = FastLanguageModel.from_pretrained("Qwen/Qwen3.5-4B", max_seq_length=2304, load_in_4bit=True)
model = FastLanguageModel.get_peft_model(
    model, r=16, lora_alpha=16, lora_dropout=0, use_gradient_checkpointing="unsloth",
    target_modules=[
        "q_proj", "k_proj", "v_proj", "o_proj",   # the 8 full-attention layers
        "in_proj_qkv", "in_proj_z", "out_proj",   # the 24 Gated DeltaNet layers
        "gate_proj", "up_proj", "down_proj",      # every MLP
    ],
)
trainer = SFTTrainer(
    model=model,
    processing_class=tokenizer,
    train_dataset=train,
    eval_dataset=held_out,
    args=SFTConfig(
        max_length=2304,
        completion_only_loss=True,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        num_train_epochs=1,
        learning_rate=2e-4,
        warmup_steps=20,
        optim="adamw_8bit",
        bf16=True,
        eval_strategy="steps",
        eval_steps=150,
        save_steps=150,
    ),
)
```

That trains 30 million parameters out of 4.57 billion (0.67%). The first pass used 3,000 random examples plus
two extra copies of each of the 394 junction lookups: 3,788 examples, 474 steps. (The script's defaults have
changed since; this was pass 1's mix.)

A smoke test came first, eight steps on 64 examples:

```bash
../unsloth-env/Scripts/python.exe training/train_qwen.py --out outputs/smoke --max-steps 8 --examples 64
```

The first step took 97 seconds, mostly Triton compiling kernels, and then about 13.5 seconds each. After eight
steps the model already replied with valid JSON in the right shape. Then the real run:

```bash
../unsloth-env/Scripts/python.exe -u training/train_qwen.py --out outputs/maze-qwen4b
```

Use `-u`. Python buffers output written to a file, and on this run the loss lines didn't appear in my log for
the first hour.

At 14 seconds a step this should have taken under two hours. At step 150 it ran its first evaluation and saved a
checkpoint, and from then on each step took 80 seconds, then 170, then 260. VRAM sat at 7.7 of 8 GB. On Windows,
when the card fills up, the driver quietly spills GPU memory into system RAM instead of failing, so everything
just gets much slower. The estimate went to 19 hours.

The logged training loss had been around 0.00003 since step 110, so I stopped there and used checkpoint 150.

## Step 7: check it, then export it

Before exporting, the script generates replies to held-out prompts greedily and compares them with the expert:

```python
for ex in examples:
    inputs = tokenizer(text=ex["prompt"], return_tensors="pt").to("cuda")
    out = model.generate(**inputs, max_new_tokens=160, do_sample=False)
    text = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    expected = json.loads(ex["completion"].removesuffix(END))
    ...
```

```
check: valid JSON 100/100, move matches expert 100/100, junction lookups 4/4
```

Export means four steps: merge the adapter into 16-bit weights, convert to GGUF, quantize, and register with Ollama:

```python
model, tokenizer = FastLanguageModel.from_pretrained(str(adapter), load_in_4bit=True)
model.save_pretrained_merged(str(merged), tokenizer, save_method="merged_16bit")
run(sys.executable, LLAMA_CPP / "convert_hf_to_gguf.py", merged, "--outtype", "bf16", "--outfile", f16)
run(LLAMA_CPP / "build" / "bin" / "Release" / "llama-quantize.exe", f16, quantized, "Q4_K_M")
run("ollama", "create", name, "-f", modelfile)
```

Compiling llama.cpp on Windows is its own project. Luckily Unsloth Studio had already left a prebuilt copy, with
`llama-quantize.exe` and a converter that knows Qwen3.5, in `~/.unsloth/llama.cpp`. The Modelfile copies the base
model's renderer, parser and sampling settings, so prompts render exactly as they did for `qwen3.5:4b` and the two
compare like for like:

```
FROM C:\...\export-checkpoint-150\model-q4_k_m.gguf
TEMPLATE {{ .Prompt }}
RENDERER qwen3.5
PARSER qwen3.5
PARAMETER presence_penalty 1.5
PARAMETER temperature 1
PARAMETER top_k 20
PARAMETER top_p 0.95
```

```bash
../unsloth-env/Scripts/python.exe training/export_ollama.py outputs/maze-qwen4b/checkpoint-150 --name maze-qwen4b
```

The bf16 GGUF was 8.7 GB, and the Q4_K_M one 2.8 GB. Playing a game is then just a config with a different model
name:

```bash
uv run maze-lab run --config configs/maze_qwen4b_v10_helping_hands_nothink.json
```

## Pass 1: it learned to search, not to remember

Same 12×12 maze as Part 1's last Qwen game, same setup, 80 turns:

| Model | Exits | Distinct cells | Coverage | Searching turns on explored cells | Back-and-forth moves |
| --- | --- | --- | --- | --- | --- |
| qwen3.5:9b (Part 1's best) | A | 74 | 0.36 | 52% | 87 |
| qwen3.5:4b, untrained | A | 49 | 0.31 | 60% | 98 |
| **maze-qwen4b** | **A, and B at turn 40** | **173** | **0.65** | **15%** | **13** |

Its moves matched the expert 124 times out of 125. B was the first local agent other than A, who starts five
moves from the exit, ever to get out of this maze.

Then I gave it 300 turns. The team covered 99% of the maze, and still only A got out. So I scored the model's
own notes against what the expert would have written:

| Game | Junction notes due | Written |
| --- | --- | --- |
| 80 turns | 13 | 1, in the wrong format |
| 300 turns | 30 | 0 |

It had learned every rule for moving and none for remembering. Without junction lines it had no way back through
a junction, and in a long game that is most of the search.

The held-out check had said 100 out of 100. It compared moves, and on a turn where a note is due the right move is
the same whether or not the note gets written. **The check was measuring the wrong thing.**

## Finding it

I worked down the stack, cheapest checks first.

**Sampling?** Ollama's defaults for this model are temperature 1 and a presence penalty of 1.5, which penalises
tokens already in the context. A junction note mostly repeats coordinates from the check line, so that seemed
plausible. I sent 25 held-out turns where a note was due straight to Ollama:

```
maze-qwen4b defaults:   junction note written 1/25, exact 1/25, move 24/25
maze-qwen4b temp0 pp0:  junction note written 0/25, exact 0/25, move 25/25
```

Not sampling.

**Constrained decoding?** At temperature 0 with no JSON schema, the replies were still `"notebook_append":null`,
and the check line skipped the "new junction" clause entirely.

**Quantization?** I registered the bf16 GGUF as a second model: 0 of 10.

**The trained checkpoint itself,** loaded in Unsloth exactly as trained: 6 of 12 held-out notes right, and all six
were landmark notes. On *training* examples, 2 of 12, again landmarks only. It had never learned junction notes at
all.

So I measured the loss token by token on training examples where a junction note was due:

```python
logits = model(input_ids=full).logits[0, :-1].float()
nll = torch.nn.functional.cross_entropy(logits, full[0, 1:], reduction="none")[prompt_len - 1:]
```

```
mean 0.0521 over 81 | worst [(3.65, ' new', 45), (0.15, ' noting', 48), (0.08, ' back', 49), (0.07, ']', 68)]
mean 0.0519 over 81 | worst [(3.65, ' new', 45), (0.14, ' noting', 48), (0.11, ' back', 49), (0.07, ',W', 43)]
mean 0.0514 over 81 | worst [(3.78, ' new', 45), (0.25, ',W', 43), (0.07, ' noting', 48), (0.01, '","', 71)]
mean 0.0447 over 81 | worst [(3.29, ' new', 45), (0.21, ',W', 43), (0.06, ' noting', 48), (0.02, '","', 71)]
```

Every token in the reply was cheap except one: " new" in "new junction, noting back E". That word is the decision
to write the note. Once the model has written it, the rest follows; if it doesn't, the note never happens. The
whole failure came down to one token.

Why that one? To write it the model has to combine two facts the check line never states: the cell has three or
more open edges, and the only exit used so far is the one it just came in by. It had to work that out silently,
from about 60 examples: pass 1's mix oversampled lookups but not notes, so notes were about 5% of the 1,200
examples it saw before I stopped it.

And the training loss? It read about 0.00003 from step 110 onwards. The held-out evaluation loss at step 150 was
0.0029, about a hundred times higher, which one missed token per note-due example accounts for almost exactly. I
don't know why the logged figure was so low. Unsloth did print one warning that may be related:

```
Unsloth: Not an error, but `num_items_in_batch` could not be counted for Qwen3_5ForConditionalGeneration's labels,
so each micro-batch loss is a mean.
```

Whatever the cause, the logged training loss said the model had learned the task. It hadn't.

## The fix

Three changes.

**1. Spell out the trigger in the check line.** The check is a scratchpad the model writes before it decides. So
instead of leaving the note decision implicit, make each step of it something the model reads off the prompt:

```
pass 1: at [-1,0]; N brick, E open, S open, W open; arrived from E; used E; untried S,W;
        new junction, noting back E; go S, untried

pass 2: at [-1,0]; N brick, E open, S open, W open; 3 open: junction; arrived from E; used E; untried S,W;
        notebook: no junction [-1,0], noting back E; go S, untried
```

Now each step is a count or a lookup. Count the open edges: three, so a junction. Search the notebook for
`junction [-1,0]`: not there, so write it. At a junction that already has a line, the check quotes it (`notebook:
junction [-2,0] back W`). That means the model practises the lookup on every revisit, not only on the 3% of turns
where it has to backtrack.

```python
facts = [
    f"at [{x},{y}]",
    ", ".join(f"{d} {_EDGE_WORDS[edges[d]]}" for d in COMPASS),
    f"{len(open_dirs)} open: {kind}",
    f"arrived from {arrived or 'nowhere (start)'}",
    f"used {','.join(used) or 'none'}",
    f"untried {','.join(untried) or 'none'}",
]
if junction and (x, y) in backs:
    facts.append(f"notebook: {junction_line(x, y, backs[(x, y)])}")
elif junction and arrived is not None and (x, y) != (0, 0):
    notes.append(junction_line(x, y, arrived))
    facts.append(f"notebook: no junction [{x},{y}], noting back {arrived}")
```

**2. Oversample both rare decisions,** writing a junction line as well as reading one back:

```python
LOOKUP = "junction explored"
NOTE = '"notebook_append":"junction'

rare = [r for r in rows if LOOKUP in r[-1]["content"] or NOTE in r[-1]["content"]]
picked = rows[:n] + rare * rare_copies
```

With 2,000 random examples plus one extra copy of each of the 828 note-writing and 394 lookup examples, that's
about 3,200 examples and 403 steps. The model sees roughly ten times as many note examples as pass 1 did before I
stopped it.

**3. No evaluation during training.** Check afterwards instead.

```bash
uv run maze-lab dataset --games 40 --sizes 8,10,12,15 --out data/train.jsonl
../unsloth-env/Scripts/python.exe -u training/train_qwen.py --out outputs/maze-qwen4b-v2 --rare-copies 1
```

It ran at 13.5 seconds a step to step 368, and then slowed to 220 seconds a step with VRAM full again, this time
with no evaluation to blame. I stopped it and used checkpoint 300, three quarters of the way through. If you train
on a card that is also running your desktop, save checkpoints often.

This time I checked the notes first:

```bash
../unsloth-env/Scripts/python.exe training/train_qwen.py --adapter outputs/maze-qwen4b-v2/checkpoint-300 --check 20 --notes-only
```

```
check: valid JSON 20/20, move matches expert 20/20, junction lookups 0/0, notes written exactly 20/20
```

## Pass 2: the expert, played by a 4B model

The same maze again, 300 turns:

| | Exits | Junction notes due / right | Moves matching the expert |
| --- | --- | --- | --- |
| Pass 1 | A only | 30 / 0 | 538 / 549 |
| **Pass 2** | **All three: A turn 5, C turn 212, B turn 250** | **25 / 25** | **466 / 467** |

The expert, playing alone on that maze, gets its agents out on turns 5, 212 and 250. The fine-tuned model played
the expert's game exactly, and that was the first team success by a local model anywhere in the project. It's not
fast: depth-first search is thorough rather than clever, and B walked 250 moves to an exit 28 away. Sonnet's team
finished this maze at turn 110.

Then the held-out mazes, overnight:

| Seed | Size | Team objective met | Expert alone |
| --- | --- | --- | --- |
| 41 | 8×8 | turn 92 | turn 92 |
| 45 | 8×8 | turn 73 | turn 73 |
| 42 | 10×10 | turn 189 | turn 184 |
| 46 | 10×10 | **no** (200-turn limit) | turn 123 |
| 43 | 12×12 | turn 169 | turn 169 |
| 47 | 12×12 | turn 229 | turn 229 |
| 44 | 15×15 | turn 275 | turn 274 |
| 48 | 15×15 | turn 244 | turn 237 |

Seven out of eight, four of them tick for tick. In the other three, one sampled choice went differently and the
game drifted a few turns. Across the eight mazes it wrote all 160 junction notes that were due, all correct, and
never walked into a wall.

The failure is the classic weakness of learning by imitation. On seed 46, one agent reached a junction that also
held a landmark, where the notebook line read `junction [7,7] back S; landmark helmet at [7,7]`. It missed the
junction part and wrote a malformed second line:

> "notebook: helmet at [7,7], no junction entry for [7,7], noting back N,S"

That led it, later, into a state the expert never produces: arriving at a fully explored junction from the side it
first came in by. There's no training data for that. So it fell back on its most common pattern, copied `used E`
where the observation said `E,S,W`, and searched the same branch five times until the turns ran out. The fix is to
let the expert label the states the model actually reaches, not just the ones the expert would reach (DAgger is the
usual name), and to keep junction and landmark notes on separate lines.

## What I'd take to the next fine-tune

- **Generate data from something that only sees what the model sees.** If the teacher uses information the student
  doesn't have, the student learns to guess.
- **Build training prompts with the serving code, and test against the wire.** My guess about how Ollama joins
  message parts was wrong. The test caught a prompt-version mismatch on its first run.
- **Render text the way the server does.** Check how your server actually formats the prompt (for Ollama, `ollama
  show --modelfile`, and the source if it says `RENDERER`). Don't assume the HF chat template matches.
- **Check the loss mask in the collator,** not in the dataset.
- **Check behaviour per field and per decision type, especially the rare ones.** Moves were 100% right while notes
  were 0%. An overall score would have hidden that.
- **Don't trust the logged training loss.** Held-out evaluation loss and real generation were the honest signals.
- **When a decision won't learn, write its reasoning out.** If the model writes a scratch field before it answers,
  put each step of the decision in it. Learning "3 open: junction; notebook: no junction [-1,0]" was easy; inferring
  the same thing silently wasn't.
- **Oversample rare decisions.** Then check them separately.
- **On an 8 GB card under Windows:** skip evaluation during training, save checkpoints often, run Python with `-u`,
  and unload Ollama (`ollama stop`) before using the GPU.
- **Imitation doesn't teach recovery.** One mistake can lead the model somewhere the teacher never went, and it has
  nothing to go on there.

## Conclusion

Part 1 found that you can tell a small model the right strategy, and it will write it down, quote it back, and
still not manage it. Showing it worked. A 4B model learned depth-first search with its memory kept in a notebook,
and played it exactly on mazes it had never seen, for about five hours of training on a gaming GPU (more than half
of that lost to the slowdowns) and no API calls.

It learned exactly what the expert did, and nothing else. It never radios, never uses landmarks to help anyone,
and never goes back for a teammate, because the expert doesn't. The teamwork from Part 1 isn't in this model. The
next step is an expert that cooperates, and recovery data so a single slip doesn't end the game.

Full code, configs and the running observations log are at https://github.com/spenceclark/maze-agent. The dataset
generator is `src/maze_lab/finetune/`, the training and export scripts are in `training/`, and the prompt-parity
test is `tests/test_finetune.py`.
