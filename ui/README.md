# Maze Lab viewer

React + TypeScript spectator UI (spec §12). Expects the API at `http://127.0.0.1:8000`
(`uv run maze-lab serve`); the Vite dev server proxies `/api` and `/health` to it.

```sh
npm install
npm run dev       # http://localhost:5173, open a run via the picker or #run=<id>
npm run build     # tsc (strict) + vite build into dist/
npm test          # vitest: live-stream reducer and journal views
npm run gen:api   # regenerate src/api/schema.d.ts from ../schemas/openapi.json
```

Live updates use the SSE stream (`/runs/{id}/events`). Data logic lives in `src/state/`, one panel per file in `src/components/`.
