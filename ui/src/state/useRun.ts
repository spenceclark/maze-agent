// Loads a run and keeps it current: bootstrap from /state, follow the SSE event
// stream through the pure live reducer, and fetch historical ticks for local playback.

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import { EVENT_TYPES, TERMINAL_STATUSES } from "../api/types";
import type { EventEnvelope, MazeDefinition, RunDetail } from "../api/types";
import { applyEvent, bootstrap, displayed, markResync, mergeEvents, type Committed, type LiveState } from "./live";

const RECONNECT_MS = 1000;

export function useRun(runId: string | null) {
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [maze, setMaze] = useState<MazeDefinition | null>(null);
  const [journal, setJournal] = useState<EventEnvelope[]>([]);
  const [live, setLive] = useState<LiveState | null>(null);
  const [followLive, setFollowLive] = useState(true);
  const [historical, setHistorical] = useState<Committed | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDetail(null);
    setMaze(null);
    setJournal([]);
    setLive(null);
    setHistorical(null);
    setFollowLive(true);
    setError(null);
    if (!runId) return;

    let closed = false;
    let resyncing = false;
    let source: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | undefined;
    let current: LiveState | null = null;
    const fail = (e: unknown) => !closed && setError(String(e instanceof Error ? e.message : e));

    const publish = (next: LiveState) => {
      const previous = current;
      current = next;
      setLive(next);
      if (next.released !== previous?.released) setJournal((j) => mergeEvents(j, next.released));
      if (next.needsResync) resync().catch(fail);
    };

    const disconnect = () => {
      source?.close();
      source = null;
    };

    // SSE names each frame by event type, so every type needs its own listener.
    const connect = () => {
      if (closed || !current) return;
      source = new EventSource(api.eventsUrl(runId, current.lastSequence));
      const onEnvelope = (message: MessageEvent<string>) => {
        if (current) publish(applyEvent(current, JSON.parse(message.data) as EventEnvelope));
      };
      for (const type of EVENT_TYPES) source.addEventListener(type, onEnvelope);
      source.addEventListener("resync", () => current && publish(markResync(current)));
      // The server also ends the stream after run.completed. Otherwise reconnect ourselves from
      // the last received sequence (EventSource's own retry would reuse the original cursor);
      // the reducer drops any replayed duplicates.
      source.onerror = () => {
        disconnect();
        if (!closed && current && !TERMINAL_STATUSES.includes(current.status)) {
          retry = setTimeout(connect, RECONNECT_MS);
        }
      };
    };

    // Initial load and every resync: fresh /state, then subscribe after its as_of_sequence.
    const resync = async () => {
      if (resyncing) return;
      resyncing = true;
      disconnect();
      try {
        const [run, state, timeline] = await Promise.all([api.getRun(runId), api.getState(runId), api.timeline(runId)]);
        if (closed) return;
        setDetail(run);
        setJournal((j) => mergeEvents(j, timeline));
        current = bootstrap(state, run.summary.status);
        setLive(current);
        if (!TERMINAL_STATUSES.includes(current.status)) connect();
      } finally {
        resyncing = false;
      }
    };

    api.getMaze(runId).then((m) => !closed && setMaze(m), fail);
    resync().catch(fail);
    return () => {
      closed = true;
      clearTimeout(retry);
      disconnect();
    };
  }, [runId]);

  // Local playback: fetch the committed snapshot for a tick; never affects the live stream.
  const latestSeek = useRef(0);
  const seek = useCallback(
    (tick: number) => {
      if (!runId) return;
      setFollowLive(false);
      const request = ++latestSeek.current;
      api.getState(runId, tick).then(
        (r) => {
          if (request !== latestSeek.current) return; // a newer seek superseded this one
          setHistorical({ tick: r.snapshot.tick, state: r.snapshot.state, metrics: r.snapshot.metrics });
        },
        (e) => setError(String(e.message ?? e)),
      );
    },
    [runId],
  );

  const { view, mode } = displayed(live, followLive, historical);
  return { detail, maze, journal, live, view, mode, followLive, setFollowLive, seek, error };
}

export type RunView = ReturnType<typeof useRun>;
