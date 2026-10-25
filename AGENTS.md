# AGENT INSTRUCTIONS FOR BRACKETMAN

Agent must obey rules. No exceptions.

## 1. ALWAYS RUN TESTS
- After every code change, run pytest:
  ```bash
  .venv/bin/pytest -v
  ```
- All tests must pass 100%. If test break, fix immediately.

## 2. ALWAYS UPDATE DOCS AND DECISION LOGS
- When code change architecture, rules, UI, or CLI:
  - Update `docs/ARCHITECTURE_AND_DECISIONS.md`.
  - Update `README.md` if user-facing instructions change.
- Keep repository docs in sync with reality.

## 3. SPEAK IN CAVEMAN STYLE (SAVE TOKENS)
- Talk like caveman.
- Cut fluff. Drop filler words.
- Short sentences. Punchy. High signal.
- Save tokens. Help user fast.

## 4. ALWAYS RESTART STREAMLIT DAEMON AFTER CODE CHANGES
- Streamlit daemon caches Python imports in memory (`sys.modules`).
- Hot reload does NOT reload modified backend modules (`exporters`, `store`, `grouping`, etc.).
- After ANY code change in `src/`:
  1. Kill running Streamlit daemon task.
  2. Restart fresh Streamlit daemon on port 8503 (`bracketman ui` or `streamlit run`).
  3. Verify HTTP 200 with `curl -sI http://127.0.0.1:8503`.
  4. If print/export logic changed, regenerate exports for active tournaments on disk.
  5. Never leave user looking at stale cache.
