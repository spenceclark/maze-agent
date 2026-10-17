import { useEffect, useMemo, useState } from "react";
import { AgentInspector } from "./components/AgentInspector";
import { MazeView } from "./components/MazeView";
import { MetricsPanel } from "./components/MetricsPanel";
import { NotebookPanel } from "./components/NotebookPanel";
import { OperatorControls } from "./components/OperatorControls";
import { RadioPanel } from "./components/RadioPanel";
import { RunPicker } from "./components/RunPicker";
import { TimelinePanel } from "./components/TimelinePanel";
import { radioRecords, trailsUpTo } from "./state/journal";
import { useRun } from "./state/useRun";

const runFromHash = () => new URLSearchParams(location.hash.slice(1)).get("run");

export function App() {
  const [runId, setRunId] = useState<string | null>(runFromHash);
  const run = useRun(runId);
  useEffect(() => {
    const onHash = () => setRunId(runFromHash());
    addEventListener("hashchange", onHash);
    return () => removeEventListener("hashchange", onHash);
  }, []);
  const { view, live, journal, maze } = run;

  const select = (id: string) => {
    location.hash = `run=${id}`;
    setRunId(id);
  };

  const trails = useMemo(() => (view ? trailsUpTo(journal, view.tick) : null), [journal, view]);
  const radio = useMemo(() => radioRecords(journal), [journal]);

  return (
    <div className="app">
      <header>
        <h1>Maze Lab</h1>
        <RunPicker selected={runId} onSelect={select} />
        {view && (
          <div className={`mode mode-${run.mode.toLowerCase()}`} role="status">
            {run.mode}
            <span>
              {run.mode === "LIVE" ? "following" : "viewing"} tick {view.tick}
              {live && live.committed.tick !== view.tick ? ` · run at tick ${live.committed.tick}` : ""}
              {live ? ` · ${live.status}` : ""}
            </span>
          </div>
        )}
      </header>
      {run.error && <p className="banner error">{run.error}</p>}
      {runId && view && live && maze && trails ? (
        <main>
          <div className="top">
            <div className="left">
              <section className="panel">
                <h3>Maze (spectator ground truth)</h3>
                <MazeView maze={maze} state={view.state} trails={trails} />
              </section>
              <OperatorControls runId={runId} status={live.status} liveTick={live.committed.tick} />
              <TimelinePanel
                journal={journal}
                tick={view.tick}
                maxTick={live.committed.tick}
                followLive={run.followLive}
                setFollowLive={run.setFollowLive}
                seek={run.seek}
              />
            </div>
            <div className="inspectors">
              {view.state.agents.map((agent) => (
                <AgentInspector key={agent.agent_id} runId={runId} agent={agent} tick={view.tick} metrics={view.metrics} />
              ))}
            </div>
          </div>
          <NotebookPanel journal={journal} agents={view.state.agents} tick={view.tick} liveTick={live.committed.tick} />
          <RadioPanel records={radio} tick={view.tick} />
          <MetricsPanel metrics={view.metrics} />
        </main>
      ) : (
        <p className="muted">{runId ? "Loading run…" : "Choose a run to view."}</p>
      )}
    </div>
  );
}
