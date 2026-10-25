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

## 4. STREAMLIT DAEMON RESTART RULE
- Streamlit daemon cache python imports in memory.
- If add or change imports/functions in backend modules, kill running Streamlit task and restart fresh.
