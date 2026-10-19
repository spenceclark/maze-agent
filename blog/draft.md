NO. 06 · DRAFT

# Lost in the maze

What it took to get three small-model agents to find their way out together, and how often the
problem was the harness, not the model.

By Spencer Clark

LOCAL-LLM / MEASUREMENT / AGENTS / MULTI-AGENT

---

## Background

In my last two posts I tested whether small local models could use tools, then built a multi-agent
harness where goblins filed feature requests. Both had short horizons. A tool chain is done after a
handful of calls. A fight in Models & Monsters lasts a few rounds.

I wanted something that runs for hundreds of turns, where an agent's only memory is what it chose to write
down, and where the only way to win is for three agents to share what they know. So I built a maze.

## The setup

Three agents start in different cells of a grid maze. The objective is for every agent to reach the exit
at least once. They don't have to be there at the same time.

Each turn, every agent is called once with no conversation history. It sees:

- the four edges of the cell it's standing on: `open`, `interior_wall` or `outer_brick`;
- whether it's on the exit;
- its own notebook (8 KB, its only memory);
- any radio messages sent by the others last turn;
- the full notebooks of any teammates standing on the same cell.

It replies with one JSON action: a move (N, E, S, W or STAY), an optional notebook edit (at most 1 KB of
new text per turn), and an optional radio message (280 bytes, then a five-turn cooldown).

All three move at once and the engine resolves the turn. As in Models & Monsters, the agents decide what to
do but never what is true. Every turn is written to a SQLite journal with state hashes, so any game can be
replayed and checked. A React viewer lets me scrub through a game and see exactly what each agent saw.

The default rules are deliberately sparse:
- no coordinates;
- no map;
- a straight-line distance to the exit and to each teammate, in tenths of a cell, which ignores walls.

Most games here use a 12×12 or 10×10 maze. All the code is at https://github.com/spenceclark/maze-agent.

One caveat before the results. **Almost every comparison in this post is a single game on a single seed.**
Earlier in the project I ran batches with three seeds, and they taught me how badly single games mislead. So
read the numbers below as what happened, not as effect sizes. Where I have batches, I say so.

## Act 1: they follow the instructions, and still fail

The first pilots used Claude Haiku 5.5. It was capable in all the small ways:
- it kept a tidy one-line-per-turn journal from the first move;
- it logged a move only after the next turn confirmed it had succeeded;
- it radioed useful facts;
- it occasionally caught its own mistakes ("labels look swapped vs obs, trust obs").

It didn't finish mazes. It fell into a few habits:
- **Following the distance reading downhill.** It parked on cells where every move made the number go up.
  One agent sat 2.2 cells from the exit in a straight line and 39 moves away by path.
- **Camping on the exit as a "beacon".** Once one agent got out, it stood on the exit cell and radioed
  directions. But the other agents can't see it, and the distance to a beacon on the exit is the same as
  the distance to the exit.
- **Looping.** Revisiting the same few cells for dozens of turns.

So I did the obvious thing and started adding sentences to the rules. Each version of the prompt targeted
one habit:

| Version | Added | Adopted? | Outcome |
| --- | --- | --- | --- |
| v3 | "Straight-line distance ignores walls; a cell where every move raises it can be a dead end" | Rarely quoted | No change in greedy behaviour |
| v4 | Note each junction and which exits you've tried; prefer an untried one | 17 of 18 agents (1 of 18 before) | More of the maze covered, same progress toward the exit |
| v5 | Keep your own coordinates; estimate where the exit is | 100% of agents | Progress got *worse*: only 28% of their self-tracked positions were correct |
| Higher reasoning effort | — | — | 2 team successes in 12 runs, both on the easiest seed; neither repeated at a bigger output cap |

The batches did the most damage to my assumptions. Across 78 Haiku runs with three seeds, there were two
team successes: $7.59 spent, about $3.80 per success. Then I ran Claude Sonnet 5.5 with no prompt changes at
all, and three of six teams succeeded.

That was the first lesson, and the rest of the project kept confirming it. **Haiku adopted every
instruction almost to the letter, and the outcome barely moved.** You can tell a model the right strategy.
It will write the strategy down, quote it back, and still not manage it.

### Was it the radio?

Agents on the exit radioed confident, greedy advice ("avoid E", "hold at 5.0"). I suspected the radio was
spreading bad habits, so I turned it off across 18 runs.

Outcomes didn't change. With radio on, the agents that were still searching just stood still about 17 more
turns, waiting for messages, and the games cost about 15% more. The greed was the model's own.

## Act 2: the local model

The same question from my earlier posts: could a local model on an 8 GB GPU do this? I used Qwen3.5-9B,
the Unsloth IQ4_XS build that had been my best local model for Models & Monsters, with reasoning off and an
8k context.

It walked into walls on a third of its moves. Every other model did that on well under 1%.

Working out why took longer than anything else in the project, and most of the early answers were wrong.

**The notebook was the first casualty.** The notebook edit format follows the original spec: replace the
text between two character positions, and quote the notebook's current revision number. Qwen got the
positions wrong constantly, and the rejected edits left its notes out of order. So I replaced the edit with
two simpler fields, `notebook_append` and `notebook_rewrite`, and let the engine handle positions.

Qwen then wiped its own notebook. Five times it sent the literal string `"null"` as a rewrite. Once it
rewrote 5 KB of notes into an echo of the JSON wrapper the notebook was shown in:

```
{"owner":"A","revision":34,"text":..."}
```

Showing the notebook as plain text and treating `"null"` as no change fixed the wipes. The rewrite field
then got dropped altogether. Qwen kept filling in both fields when told to use one or the other, so 21 of 22
rewrite attempts cancelled themselves. What was left was a rolling log: one append field, with the engine
dropping the oldest lines when the notebook fills.

**Temperature looked like a fix, and wasn't.** I replayed 60 randomly chosen recorded decisions. At
Ollama's default temperature, 24% went into walls; at 0.2, 9%. So I ran a full game at 0.2, and wall moves rose to *56%*.
One agent reached a cell at turn 9 and moved west into a wall for the remaining 71 turns. Every turn its
note correctly said `W=wall`. The prompt barely changed between turns, so at low temperature the same reply
came back each time. The replay had tested independent decisions; a real game feeds each reply into the
next prompt.

**Plan inertia.** Qwen wasn't misreading the walls. It copied its edges correctly about 90% of the time,
and then moved through the one it had just called closed:

```json
{
  "move": "N",
  "notebook_append": "At [3,3] (N=wall, E=wall, S=open, W=open): Backtracking West…"
}
```

I suspected field order: if the model writes `move` before its note, it commits to a direction before it
has written anything about its cell. My first test of this was invalid. The Unsloth build writes JSON keys
in alphabetical order whatever the schema says, so `move` always came first. When I sent the same request to
the official `qwen3.5:9b` build, it answered differently, and it keeps keys in schema order. That made the
test possible:

| qwen3.5:9b, reasoning off | Moves into walls |
| --- | --- |
| Move first (default) | 37.5% |
| Note before move, on turns it wrote a note | 14% |
| A required one-line `check` before the move, every turn: "restate your four edges, where you came from, which way you'll go and why" | **7.5%** |

A single scratch field, written before the decision and thrown away afterwards, did most of what turning
reasoning on did, without the cost. (With reasoning on, half the replies never finished within 4,096
tokens.)

**Then the bookkeeping, then the wall.** With the walls fixed, the next problem was junctions. Back at a
junction with an untried exit, Qwen took one it had already used 58% of the time. Having the engine list
"exits you've already used here" fixed that: given an unexplored way out, it took it 89% of the time.

And still nobody got out. Qwen now spent 57% of its turns wandering cells where every exit had already
been used. It had no way to plan a route back to the nearest unexplored ground. The only scaffold left was
to have the engine point at the nearest unexplored exit. At that point the engine is solving the maze and
Qwen is just pressing the buttons.

That's where I stopped. Each fix repaired exactly the layer it targeted. Perception went from 37% to 7.5%
wall moves, the local choice from 58% wrong to 11%. None of it added the ability to plan across a map
Qwen had already seen.

For reference, two other local models were worse. lfm2.5 lost 192 of 240 turns by replying with the wrong
turn number. command-r7b, with its chat template fixed, walked into walls on 45% of its moves even with the
check line.

## Act 3: when the harness is the problem

The other recurring theme was finding out, often late, that a failure I had blamed on a model was mine.

- **The trail wording.** I gave agents their coordinates plus a list of their last 30 positions. The rule
  said the trail lists "where you were on each of the last 30 turns". Haiku read the last entry as its
  current cell, and wrote "trail lagged" or "position conflicts with trail" about 22 times a game. One
  agent trusted the trail over its exact position. Rewording it ("it ends with last turn's cell, so it
  never includes where you are now") took the doubts to zero. That game was then Haiku's best exploration
  so far.
- **Output modes.** Xiaomi's MiMo answers with JSON as plain text instead of a tool call. In tool mode,
  that cost 99 turns of one game. Switched to prompted mode, it sometimes copied `"additionalProperties":
  false` from the schema into its reply, which the strict parser rejects.
- **Key order.** As above, the Unsloth Qwen build's alphabetical keys quietly invalidated an experiment.
- **The literal string "null".** Qwen sent `"null"` as a real radio message 21 times in 28 in one game,
  and both teammates dutifully received "null".
- **A Qwen fix leaking into everyone else's games.** The rolling-log notebook was built for Qwen and
  carried on into the hosted baseline. For Haiku it nearly doubled the cost of a game: notebooks changed
  every turn, so the prompt cache was rewritten every turn. Sonnet appends and never edits, so for it the format
  doesn't matter until the notebook fills. DeepSeek, it turns out, compacts its own notes regularly (73
  times in 9 games), and the rolling log takes that away.

None of these show up as "the harness is broken". They show up as a model that seems confused, unreliable
or bad at following instructions. My Models & Monsters post concluded that the engine has to be the
single source of truth. The corollary here is that **the engine, the schema and the prompt wording are all
part of what you're measuring**, whether you mean them to be or not.

## Act 4: coordinates and frames

The biggest single lift for Haiku came from giving it what it couldn't track for itself: exact coordinates.
I didn't give it a map, and its coordinates count from its own start.

With them, Haiku did things Sonnet had been doing unprompted:
- **It estimated the exit's exact position** in its own frame from distance readings taken at known cells.
  Two agents in one game were both exactly right.
- **One agent worked out the offset to a teammate's frame,** using the exit as the shared reference:
  "B = A + (-4,-3)", which was exactly right.

But each agent counts from its own start, so every coordinate on the radio was in someone else's frame.
Haiku understood this: 109 of its 110 radio messages with coordinates said whose frame they were in ("A-frame
[-2,1]", "offset unknown"). Qwen never once did.

Knowing where the exit is turned out not to be the same as knowing how to get there. One agent knew the
exit's exact cell from turn 31 and spent the rest of the game looking for a corridor to it.

### Turning off the distance sensors

Did the distance readings make the agents bounce back and forth? Partly. In eight earlier Haiku games, 62 of
104 reversals came straight after a move that raised the reading. With coordinates and the trail, though,
bouncing was already low, and removing the sensors changed it very little. The real effect was that landmarks
became the only reference two agents could both recognise, and they started using them as one.

## Act 5: teaching cooperation, one step at a time

The objective only needs each agent to visit the exit once. So the agent that finds it first is free, and
in theory the best thing it can do is go and help. Getting there took four more prompt versions, each
patching the specific way the previous one failed:

| Version | Added | What happened |
| --- | --- | --- |
| v8 | "Once you've reached the exit, standing on it helps nobody… head back and find a teammate" | A left the exit, then went back to its own start and waited there for 37 turns, radioing the same route 13 times |
| v9 | "Give positions relative to a landmark" | The searchers asked for exactly that ("send your exit position relative to the piano"). The exit-finder gave it relative to its own start and waited there for 69 turns |
| v10 | "Your own start is not a landmark: only you know where it is" | A stopped camping (2 STAYs in 80 turns), visited four landmarks and radioed the exit exactly from each: "10 west and 3 south of the key". Nobody else had visited those four landmarks |
| v11 | "When you meet, copy what you lack from their notebook. Don't wait for information; go and find the landmark" | The waiting stopped (197 STAYs → 72). Merging didn't happen at all |

Then I gave Sonnet 120 turns instead of 80, and it showed what all of this was for. The agent that found
the exit radioed it relative to the picture landmark. A second agent found the picture, walked to the exit,
and radioed a step-by-step route from the picture:

> "C reached exit. Exit is 5W,1N of PICTURE… From PICTURE go N3,W,S,W,S,E,S,W,W,N,N,W,S,W"

The third agent found the picture 22 turns later, followed the route, and the team met the objective at
turn 110. No frame conversion was needed at any point: everything went through a landmark they could all
stand on.

### The trigger matters more than the instruction

Across about 2,200 turns where two agents shared a cell, almost nobody copied anything from the other's
notebook. That held for Sonnet, Haiku and DeepSeek, and it held under v11, which explicitly told them to.

At Haiku's first v11 meeting, two agents stood on the same cell. Each wrote a note about its own next move
and said nothing about the other. The only sign they had met was an extra block of text in the prompt, and
both were mid-plan.

So I made the meeting explicit. The observation gained `"colocated_with": ["B"]`, and a rule said what to
do with it. The same game on the same maze, Haiku again:

> "Tick26: at [-1,-3] with B. B's notebook says B at [5,-3] (B frame), so offset is probably B = A + (6,0)"
>
> "Offset: B frame = C frame + (4,-3), since B candle [2,3] = my [-2,6]. Exit in B frame is [8,4]"

Every meeting got used. The team met the objective at turn 91, its fastest finish on any maze, for $0.13.
The instruction had been in the prompt the whole time; the trigger was missing.

The other route to a Haiku team success was to remove the problem: give everyone one shared frame. Then
the exit is just "[2,5]" to everyone. That team succeeded too, on the last turn.

## Act 6: bigger mazes, longer games

Finally I gave Haiku its best setup and 600 turns, on five new mazes from 9×9 to 17×17 with 10 to 14
landmarks:

| Maze | Fastest possible finish | Result | Cost |
| --- | --- | --- | --- |
| 9×9 | turn 30 | **objective met, turn 116** | $0.18 |
| 11×11 | turn 41 | **objective met, turn 125** | $0.18 |
| 13×13 | turn 83 | **objective met, turn 238** | $0.40 |
| 15×15 | turn 95 | time limit, no exits | $1.05 |
| 17×17 | turn 71 | **objective met, turn 236** | $0.37 |

Four out of five, each in about three to four times the fastest possible time. Compare $3.80 per success
at the start of the project on a 12×12 maze, against $0.18–0.40 per success now on mazes up to 17×17.

The first agent out was usually quick (turns 27, 42, 66). Most of each game went on the relay: describing
the exit relative to landmarks (12 to 47 such messages per game), and the others finding those landmarks
and walking the route.

The 15×15 failure is the most instructive game in the project. All three agents started 72 to 95 moves from
the exit, and the exit's whole region hung off a single cell on the south edge. Every agent passed that cell
twice. Each time the note recorded the open side, and each time the agent carried on along the edge:

> "N open, E open (came from), S brick, W open. Continuing W along row -6."

Six passes, six misses. A plan to keep sweeping the edge overrode the rule about untried exits, and by the
end of the game no notebook mentioned the cell at all. A v12 rerun told them to keep exploring and split the
search. They did both: radio about covered ground went from 12 messages to 65. They still walked past the
same cell.

They did sync their frames in those games, often. Offsets read off directly at a meeting were usually
right. Offsets they derived went wrong: turning "A = B + (8,−4)" round into "B = A + …" flipped the sign
of y, and chaining two offsets went off by one. The wrong values were then repeated for hundreds of turns.

## What it cost

| Setup | Team successes | Cost per success |
| --- | --- | --- |
| Haiku, early prompts, 12×12, 80 turns (78-run batch) | 2 | ~$3.80 |
| Sonnet, early prompts (6-run batch) | 3 | ~$3.00 |
| Sonnet, current setup, 12×12, 120 turns | 1 of 2 | $6.73 (both games) |
| Sonnet, current setup, 10×10, 120 turns | 1 of 1 | $1.97 |
| Haiku, current setup + meeting alert, 10×10 | 1 of 1 | $0.13 |
| Haiku, current setup, 9×9–17×17, 600 turns | 4 of 5 | $0.18–0.40 (plus $1.05 for the failure) |
| Qwen3.5-9B, local, every variant | 0 | — |

## Conclusion

I started out asking whether small models could cooperate through a maze with nothing but a notebook and a
radio. The answer turned out to be yes, for Haiku, but only once the harness gave it the right handholds.

**Instructions get adopted; mechanisms change outcomes.** Every prompt nudge was adopted, often by every
agent, and most of them didn't move the result. What moved it:
- **Exact coordinates,** because self-tracked coordinates drifted.
- **A shared frame, or a way to calibrate frames at meetings,** because converting between frames was where
  errors crept in.
- **A meeting made explicit,** because an implied one was ignored.
- **A longer horizon,** once the agents had stopped looping.

**Make the trigger obvious.** "Copy what you lack when you meet" did nothing until the observation said
someone was there. A scratch line before the move did more for Qwen than any wording about walls.

**Check the harness before you blame the model.**
- The trail wording;
- the output mode;
- the key order;
- the literal string "null";
- a notebook format designed for someone else.

Each looked like a model weakness at first.

**Don't trust a single decision or a single game.** A replay of individual decisions said lower temperature
would help; a real game said the opposite. A single run made v3 look like a big improvement; the batch said
it wasn't.

**Small local models hit a wall.** Each scaffold fixed the layer it targeted. None gave Qwen the ability to
plan a route back across ground it had already seen, which is the part of maze-solving that actually needs
a model of the maze.

The hosted models are a different story. Sonnet does most of this unprompted. GLM 5.3 Flash explored 95%
of a maze for $0.20. Haiku, with enough scaffolding, now finishes mazes bigger than any I first gave it, for
less than a quarter of a dollar.

Full code, configs and the running observations log are at https://github.com/spenceclark/maze-agent.
