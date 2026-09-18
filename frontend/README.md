# GridWise — frontend (demo UI)

A standalone React + TypeScript + Vite app that drives `/health` and `POST /optimize-energy`. This is a
demo/testing UI, not part of the judged surface — the backend defines the actual contract, in
[../README.md](../README.md) and [../IMPLEMENTATION_TRACKER.md](../IMPLEMENTATION_TRACKER.md).

It lets you build a 24-hour scenario (or load one of the ten public sample cases), submit it, and see the
result: the plan summary, totals, each note's directive interpretation, and the 24-hour dispatch plan as a
chart or table.

## Running it

```bash
npm install
npm run dev      # http://localhost:5173
```

The backend must be running separately (`uvicorn app.main:app --host 0.0.0.0 --port 8000` from the repo root).
Requests to `/api/*` are proxied by Vite to `http://localhost:8000` in dev — see "Why the proxy" below. Point
it elsewhere with `VITE_BACKEND_URL` in a `.env.local` (copy `.env.example`).

```bash
npm run build     # type-check + production build to dist/
npm run preview   # serve the production build locally
```

## Current backend state

As of this writing the backend is through P0–P6: the optimizer path is fully wired and provably optimal, but
the LLM interpreter (P8) doesn't exist yet, so `POST /optimize-energy` currently returns a controlled
`500 interpretation_unavailable` for every request. This UI is built against the real, final contract
(`app/schemas/`) so it needs no changes once P8/P9 land — until then, submitting a scenario here will show
that error rendered in the result panel, which is expected.

## Why the proxy

The backend has no CORS middleware (by design, for now — this frontend does not add one, since the task was
to build the frontend without touching the backend). A page served from `localhost:5173` calling
`localhost:8000` directly would be blocked by the browser. `vite.config.ts` works around this in dev only: it
proxies `/api/*` to the backend server-side, so the browser only ever talks to the Vite origin and CORS never
comes into play.

This means `npm run build && npm run preview` (or any other static hosting of the built `dist/`) has **no**
such proxy. To use a built version against a real backend, either enable CORS on the backend for that origin,
or serve both from behind the same reverse proxy — a deployment concern that belongs to P16, not to this
frontend.

## What's here

```
src/
  api/          Fetch client + TypeScript types mirroring app/schemas/*.py exactly
  components/   Form editors (notes, battery, 24-hour table), sample picker, results display
  utils/        Client-side structural pre-checks, formatting, empty-scenario helper
public/
  samples.json  Trimmed copy (id/label/input only) of public_cases/sample_cases.json,
                for the "load a sample" picker — the same public examples the organizers
                publish, not hidden judge data.
```

No chart library, no CSS framework: the 24-hour chart is hand-rolled SVG and the styling is plain CSS with
light/dark support, to keep the dependency list (and therefore the things that can go wrong) small.

## Known limitations

- No automated tests for this UI — it wasn't asked for, and the judged surface is the backend. Add some if the
  demo layer starts carrying real weight (e.g. for a submission video).
- The hour-by-hour table can get long on a small screen; there's no compact/collapsed view yet.
- The client-side validation in `utils/validation.ts` only mirrors the backend's *structural* contract, not
  its semantic or guardrail rules — the backend is still the source of truth and re-validates everything.
