# Copilot Instructions for AnnotatorBackend

## 1. Project Overview

This is a **Chinese reading-learning application** that helps users who can speak and understand Mandarin learn to read Chinese characters. The core feature is Pinyin annotation: users paste or select Chinese text, and the app generates Pinyin (transliteration) displayed above each character. Users can toggle Pinyin on/off and progressively mark characters or words as "recognized", enabling incremental reading progress.

**Full Stack:**

| Layer | Technology |
|---|---|
| Backend API | Django 6.1 + Django REST Framework (DRF) 3.18.x |
| Frontend UI | Next.js 16 with React 19, Tailwind CSS 4, TypeScript 5 |
| Bundler | Next.js built-in bundler |
| HTTP Client | axios (with Django CSRF token support configured) |
| Language (backend) | Python 3.12 (pinned via `.python-version`; Render also reads `PYTHON_VERSION` in `render.yaml`) |
| Language (frontend) | TypeScript |
| Python Environment & Dependency Tool | uv (`uv venv`, `uv pip`, `uv run`) with `requirements.txt` |
| Data | CEDict dictionary, custom Trie structure for lookups |

The Django project lives under `Annotator/` and contains one Django app:
- `api/` — all backend REST API logic (models, views, serializers, utilities)

The frontend is a separate Next.js application under `frontend/` that communicates with the backend via REST API calls.

---

## 2. Code Style & Conventions

### Python (Backend)

- **Naming:**
  - Functions and local variables: `snake_case` (e.g., `parse_pinyin`, `reload_entry`)
  - Classes: `PascalCase` (e.g., `EntryView`, `AnnotationSerializer`)
  - Constants: `UPPER_SNAKE_CASE` (e.g., `DEFAULT_OWNER`, `MAX_PRIORITY`)
  - Model fields: use `camelCase` to match the existing convention in `models.py` (e.g., `createdAt`, `updatedAt`)
- **Formatting:** Follow PEP 8. Use 4-space indentation. Keep lines under 120 characters.
- **Imports:** Group in order — stdlib, Django/DRF, local app imports. Use absolute imports within the project.
- **Early returns:** Prefer early returns over deeply nested conditionals.
- **Error handling:** Always return a DRF `Response` with an appropriate `status` code. Never let an uncaught exception propagate to the client.
- **No unused code:** Do not leave commented-out code blocks unless they carry meaningful in-progress notes. Remove dead code.
- **Type hints:** Add type hints to new utility functions and helper methods when the types are non-obvious.

### TypeScript (Frontend)

- **Naming:**
  - React components: `PascalCase` file names and function names (e.g., `HelperCard.tsx`, `DisplayArea.tsx`)
  - Variables, functions, props: `camelCase` (e.g., `parsePinyin`, `triggerAnnotate`)
  - Constants: `UPPER_SNAKE_CASE`
- **Formatting:** 2-space indentation, single quotes for strings. Follow TypeScript strict mode requirements.
- **TypeScript:** All new code must use TypeScript (`.ts` and `.tsx` files). Use strict mode with proper type annotations.
- **Functional components:** Use **functional components** with React hooks (the modern React paradigm). Do not use class-based components.
- **State management:** Use React hooks for state management (`useState`, `useContext`, etc.). Do not introduce Redux, Zustand, or other external state libraries without explicit approval.
- **Styling:** Use Tailwind CSS for styling. Apply utility classes directly to JSX elements. Do not use styled-components or CSS-in-JS.

---

## 3. Architecture & Directory Patterns

### Backend (`Annotator/api/`)

```
Annotator/
├── Annotator/          # Django project settings, root URL conf
│   ├── settings.py
│   └── urls.py         # Routes: /api/ → api.urls
├── api/                # Main API Django app
│   ├── models.py       # All Django ORM models
│   ├── serializers.py  # All DRF serializers
│   ├── views.py        # All API views (class-based)
│   ├── urls.py         # API URL patterns (prefix: /api/)
│   ├── utils.py        # Shared utility functions (isChinese, parsePinyin, CEDict loading, etc.)
│   ├── Trie.py         # Trie data structure for fast dictionary lookups
│   ├── migrations/     # Django database migrations (auto-generated)
│   └── tests.py        # Django test cases
└── frontend/           # Next.js frontend application
    ├── src/
    │   ├── app/        # Next.js App Router pages and layouts
    │   ├── components/ # All React components (one per file)
    │   └── lib/        # Utility functions and helpers
    ├── public/         # Static assets
    ├── next.config.ts  # Next.js configuration
    ├── tsconfig.json   # TypeScript configuration
    ├── tailwind.config.ts # Tailwind CSS configuration
    └── package.json
```

**Rules:**
- New API endpoints **must** be added to `api/urls.py` and `api/views.py`. URL patterns use the existing `/api/<resource>` convention.
- New models go in `api/models.py`. Run `python manage.py makemigrations` after any model change.
- New serializers go in `api/serializers.py`.
- Shared/reusable backend logic (e.g., Chinese character parsing, dictionary helpers) goes in `api/utils.py`.
- New React components go in `frontend/src/components/` as a single `.tsx` file per component. Use functional components with TypeScript.
- Do not create sub-directories inside `frontend/src/components/` unless there is an explicit need for co-located assets.
- Pages and layouts go in `frontend/src/app/` following Next.js App Router conventions.
- Utility functions and custom hooks go in `frontend/src/lib/`.

### Module Interaction

- The frontend communicates with the backend **exclusively via axios HTTP calls** to `/api/` endpoints.
- CSRF tokens are handled globally via `axios.defaults.xsrfCookieName` and `axios.defaults.xsrfHeaderName` (already configured in `App.js`). Do not bypass CSRF protection.
- The backend does **not** import anything from the `frontend/` app. Data flows strictly from the database → DRF serializer → JSON response → React component.

---

## 4. Tech-Specific Rules

### Django / Django REST Framework

**DO:**
- Use `uv` for Python environment and dependency workflows (`uv venv`, `uv pip install -r requirements.txt`, `uv run python ...`).
- Use **class-based views** inheriting from `APIView` or a DRF generic view (`generics.ListAPIView`, `generics.ListCreateAPIView`, `generics.RetrieveUpdateDestroyAPIView`). Match the pattern in `views.py`.
- Use a dedicated **serializer** for every model interaction. Never directly build raw dicts from `request.data` without validation.
- Validate input with `serializer.is_valid()` before accessing `serializer.data`.
- Return `Response(data, status=status.HTTP_<CODE>_<NAME>)` for all API responses.
- Use `Entry.objects.filter(...)` with Q objects for complex lookups. Always call `.order_by()` when the ordering matters.
- Use `get_or_create` for idempotent object creation (see `CreateMemoryView`).
- Add new URL patterns to `api/urls.py` using `path(...)` with descriptive resource names.
- Always handle the case where a session does not yet exist: `if not self.request.session.exists(...): self.request.session.create()`.

**DO NOT:**
- Do not add new Python package managers or lockfile workflows (Poetry/Pipenv/etc.) without explicit approval.
- Do not use Django function-based views. All views must be class-based.
- Do not use `django.shortcuts.render` for API responses (it is only used in `frontend/views.py` to serve the SPA shell).
- Do not use raw SQL queries. Use the Django ORM exclusively.
- Do not expose the Django admin credentials or internal model data without proper serializer filtering.
- Do not use `serializer.save()` unless the serializer's `create`/`update` method is explicitly defined for that serializer.
- Do not hardcode the `owner` field; use the `OwnerOrDefault(owner)` utility and the `DEFAULT_OWNER` constant from `utils.py`.

### React / Next.js (Frontend)

**DO:**
- Use **functional components** with React hooks (`useState`, `useEffect`, etc.) for all new components.
- Export components as default or named exports, e.g. `export default function MyComponent() { ... }` or `export function MyComponent() { ... }`.
- Use `axios` for all HTTP requests to backend `/api/` endpoints.
- Use **Tailwind CSS** for all styling. Apply utility classes directly to JSX elements (e.g., `<div className="flex items-center gap-4">`).
- Use Next.js App Router conventions for pages and layouts. Place pages in `src/app/` following the file-based routing structure.
- Use custom hooks in `src/lib/` for shared logic between components.

**DO NOT:**
- Do not use class-based components. This project uses modern functional components with hooks exclusively.
- Do not use MUI, styled-components, or other CSS-in-JS libraries. Use Tailwind CSS only.
- Do not use `fetch` for HTTP calls. Use `axios` exclusively.
- Do not add new npm packages without explicit approval. Check `frontend/package.json` before installing new dependencies.
- Do not use the old `react-router-dom` library. Next.js App Router handles routing natively.

### Pinyin / Chinese Text Processing

- **Always** use `isChinese(char)` from `api/utils.py` to detect Chinese characters — do not write ad-hoc Unicode range checks.
- **Always** use `parsePinyin(pinyin)` from `api/utils.py` (backend) or the `parsePinyin` method in `HelperCard.js` (frontend) to convert ASCII pinyin (e.g., `san1`) to toned Unicode pinyin (e.g., `sān`). Do not duplicate this logic.
- When performing dictionary lookups at annotation time, use the `Trie` class from `api/Trie.py` — do not do linear scans over `Entry.objects.all()`.
- Pinyin in storage (database and serialized form) follows the CEDict ASCII format (e.g., `zhong1 guo2`). Convert to display form only at render time.
- **Polyphone (多音字) disambiguation:** `api/polyphone.py` wraps the lightweight g2pM model (single-layer BiLSTM, ~1.7MB, numpy-only) for contextual readings. It runs in **advisory mode** by default (`G2PM_ADVISORY_MODE=1`): the model never overrides a reading -- the dictionary always wins -- and disagreements are flagged as `conflict` provenance for dictionary curation. Set `G2PM_ADVISORY_MODE=0` to let g2pM override when its prediction is a known dictionary reading of that character (it never invents readings outside the dictionary). Disable the whole step with `G2PM_ENABLED=0`. Each character carries a provenance `source` (`dict` | `g2pm` | `conflict`) on `ChineseEntry` and through `ChineseEntrySerializer`, plus `suggested_pinyin` (g2pM's proposed reading, parsed form like `pinyin`) when the source is `conflict`, plus `confidence` (the model's softmax confidence 0..1 for its prediction, null when no prediction was made). `predict_with_confidence(text, model=None)` returns `(pinyins, {pos: confidence})` in a single forward pass -- it mirrors `G2pM.__call__`/`predict` internals using the model's own public sub-methods because the package discards logits (argmax only); `predict_char_pinyins` is kept as a backwards-compatible wrapper.
- **g2pW A/B testing:** a second, BERT-based disambiguation model (GitYCC/g2pW, 99.08% vs g2pM's 97.31% on the CPP benchmark) is available behind `G2P_MODEL` (`"g2pm"` default | `"g2pw"`, Django setting / env var; `G2PW_MODEL_DIR` overrides the model dir, default `data/models/g2pw`). `api/polyphone.py` dispatches via `active_model()`; `predict_with_confidence(text, model=...)` and `model_available(model=...)` take an optional model name. The g2pW path (`_predict_g2pw`) uses `G2PWConverter(style="pinyin", enable_non_tradional_chinese=True)` -- the model was trained on traditional text, so simplified input is converted 1:1 first; characters it has no reading for are echoed back so the list stays 1:1 and downstream `looks_like_pinyin` filtering ignores them; outputs are normalized via `normalize_pinyin()` (g2pW spells ü as 'v', e.g. 'nv3' -> the dictionary's 'nu:3', so equivalent readings compare equal); confidences are always `{}` (its public API discards them). `resolve_pinyin()` silently keeps the dictionary reading (no conflict flag) when a neutral-tone particle in a multi-character phrase (e.g. de5, zi5) only differs from the model by tone -- the neutral tone is grammatical, not a real polyphone ambiguity; single-character phrases and different-syllable disagreements still flag. It needs `pip install g2pw onnxruntime transformers tqdm requests` plus CPU-only torch (`pip install torch --index-url https://download.pytorch.org/whl/cpu`; the g2pw package imports torch at module level even though inference is ONNX-only), and the ~590MB ONNX model auto-downloads on first use -- the download + load runs on a background daemon thread (`get_g2pw_converter` never blocks; `g2pw_status()` reports 'ready'/'provisioning'/'unavailable'). `POST /annotate/provenance` accepts an optional `model` field (`400` on unknown names, per-model `503` when unavailable; a `503` with `{"status": "provisioning"}` means g2pW is still downloading in the background -- retryable, not failed); the dev legend (`?dev=1`) has a g2pM/g2pW toggle that re-runs the provenance pass with the chosen model, and the conflict panel + legend labels follow the active model. The toolbar shows a conflict count badge, a spinner while a pass is running, and a "provisioning g2pW model" indicator (with auto-retry) while the backend downloads. Provenance passes are cancellable via AbortController -- switching chapters/models aborts the in-flight pass so slow g2pW requests don't pile up. `/annotate/curate` accepts an optional `model` recorded in the priority row's `reason` (`"g2pM curation"` / `"g2pW curation"`). Missing g2pW packages degrade gracefully -- the toggle just reports the model unavailable.
- **EntryManager LRU cache:** `EntryManager.get()` memoizes the merged blacklist/priority/sorted entries per `(phrase, trad)` (`functools.lru_cache`, maxsize 16384) -- phrases repeat heavily within a text, so the merge runs once per unique phrase. The cache is cleared in `clear()`/`load()` (hence on every `reload()`); callers must treat the returned list as read-only. This also fixed a latent aliasing bug where `entries.extend(customEntries)` mutated the shared cached list and duplicated custom entries on repeated lookups.
- **Dev-only provenance highlights:** the annotator frontend underlines characters by pinyin `source` (emerald = `g2pm` override, amber = `conflict`; `dict` has no underline) plus a legend, but ONLY when `?dev=1` is in the URL. For speed, the main `/annotate` endpoint skips g2pM entirely in advisory mode; the frontend then calls `POST /annotate/provenance` in the background and swaps the result in, so highlights appear when the model finishes without blocking the first render (stale responses are discarded via a request id). `/annotate/provenance` returns 503 when the model can't load (missing package etc.) instead of silently returning all-dict, and the dev legend shows "g2pM provenance unavailable" in that case. The `?dev=1` check is a live `isDevMode()` read (never a stale closure) so the background pass fires reliably. `Fragment.source` is optional in `frontend/src/lib/types.ts` for backward compatibility. On a `conflict` character the dev UI shows the g2pM suggestion (no "g2pM:" label) ABOVE the dictionary pinyin, with the model's confidence as a percentage next to it (e.g. `háng · 87%`; the panel's curation section shows `· 87% confident` too); in dev mode a single tap always opens the bottom lookup panel instead of toggling pinyin visibility, and the panel shows an amber curation section with two actions: "✓ Use this reading" (`POST /annotate/curate`) and "✗ Mark as wrong" (`POST /annotate/dismiss`). Accepting only re-runs the provenance pass (it returns full annotations, so no full re-annotate). The character's position within its phrase is threaded through as `phraseIndex` (`renderFragment` → `handleFragmentPress`/`beginLongPress` → `inspectLookup` → `LookupTarget`) so the curate call targets the right character.
- **Dev-only curation endpoints:** `POST /annotate/curate` `{phrase, char_index, suggested_pinyin}` takes the phrase's top entry, swaps the reading at `char_index` for the suggestion, and persists it -- boosting via `priority.json` when a dictionary entry with the corrected pinyin already exists (the row carries that matching entry's own traditional form and definition, not the top entry's; an existing row for the same reading gets its stale fields refreshed instead of being skipped), otherwise adding via `custom.json` (english falls back to the top entry's) -- then rebuilds that datamap (`setupPriorityEntries`/`setupCustomEntries`) and calls `EntryManager.reloadPriorities()`/`reloadCustoms()` (granular reloads that re-read one datamap + clear the LRU cache) so the change is live immediately. `POST /annotate/dismiss` `{char, dict_pinyin, suggested_pinyin, prev_char?, next_char?}` records the tuple in `data/g2pm_dismissed.json`; `polyphone.resolve_pinyin` consults it via `is_dismissed()` and never flags that (character, dict reading -> suggestion) direction again **in that context** -- `prev_char`/`next_char` are the character's immediate neighbors within its phrase ("" at phrase edges), so the same suggestion can still flag in other words. The frontend computes the neighbors from the phrase text + `phraseIndex`. Rows written before context existed load with "" neighbors and only match empty context. Both endpoints also accept optional `context` (the paragraph text the model saw) + `context_index` (the judged character's offset within it); when valid, the judgment is appended to `data/g2pm_training.jsonl` as a fine-tuning example `{text, index, char, pinyin, label, model, ts}` (`label` is 'accept' with the suggested pinyin, or 'dismiss' with the kept dictionary reading; misaligned rows are skipped, never breaking curation). The frontend threads the paragraph location through as `paragraphIndex`/`absoluteIndex` (`renderAnnotationItem` -> `renderFragment` -> `handleFragmentPress` -> `inspectLookup` -> `LookupTarget`) and validates `context[contextIndex] === fragment.cchar` before sending. `python manage.py export_training --out data/training_cpp/mine` exports the log to CPP format (`.sent` lines wrap the judged character in U+2581 ▁, `.lb` lines hold its pinyin), deduped on (text, index) with the latest judgment winning. `POST /entry/custom` `{simplified, traditional?, pinyin, english?, notes?}` (pinyin is normalized to numbered ASCII via `normalize_pinyin()`, so "nǐ hǎo"/"nv3" become "ni3 hao3"/"nu:3") (used by the annotator's "Add custom phrase" modal) appends to `data/custom.json` (deduped on simplified+pinyin), rebuilds the custom datamap and reloads it so the phrase annotates immediately, and also logs an `EditEntry` record (`type='custom'`) for review -- previously the modal only wrote the `EditEntry` row, which never affected annotation. Both endpoints accept toned (`háng`) or ASCII (`hang2`) pinyin, normalized by `polyphone.unparse_pinyin()` -- note the neutral-tone fallback only applies to vowel-containing input so garbage like `zzz` is returned unchanged and rejected by `looks_like_pinyin` instead of being blessed as `zzz5`.

---

## 5. Testing & Documentation

### Instruction Maintenance Requirement

`copilot-instructions.md` is a living source of truth for coding agents in this repository.

Whenever any PR or commit changes project-level conventions or implementation direction, this file **must** be reviewed and updated in the same change set.

Required update triggers include:
- Architecture changes (new app/module boundaries, moved responsibilities, routing structure changes)
- Stack/technology changes (framework/library upgrades, replacements, additions, removals)
- Code style or convention changes (naming, formatting, component patterns, serializer/view patterns)
- Build/deploy/runtime changes (webpack/build pipeline, env handling, deployment platform behavior)
- Testing strategy changes (new frameworks, required coverage expectations, test command changes)

Contributor checklist for such changes:
1. Update the relevant section(s) in this file to match the new reality.
2. Remove or rewrite outdated guidance; do not leave contradictory rules.
3. In the PR description, include a short note confirming instruction updates were reviewed.

If a change intentionally diverges from existing guidance temporarily, add a concise `TODO` in this file describing:
- what is changing,
- why the temporary divergence exists, and
- when/how it will be reconciled.

### Backend Tests

- Tests live in `api/tests.py` and `frontend/tests.py`.
- Use Django's `TestCase` base class: `from django.test import TestCase`.
- Use DRF's `APITestCase` for endpoint tests that require the test client: `from rest_framework.test import APITestCase`.
- **Each view** should have a corresponding test class that covers:
  - Happy path (valid input → expected HTTP 200/201 response)
  - Invalid input (missing required fields → HTTP 400)
  - Not-found cases (HTTP 404)
- Run tests with: `uv run python manage.py test`

### Frontend Tests

- No automated test framework is currently configured for the frontend. If you add tests, use **Jest** (which is compatible with the existing Babel config) placed alongside the component file (`ComponentName.test.js`).
- Do not configure or run Playwright or Cypress tests unless the project explicitly adopts them.

### Code Documentation

- **Python:** Use Google-style docstrings for all public functions and class methods. Include `Args:`, `Returns:`, and `Raises:` sections when applicable.
  ```python
  def parse_pinyin(pinyin: str) -> str:
      """Convert ASCII pinyin to toned Unicode.

      Args:
          pinyin: ASCII pinyin string, e.g. 'san1'.

      Returns:
          Toned Unicode pinyin string, e.g. 'sān'.
      """
  ```
- **TypeScript:** Use proper type annotations and JSDoc comments when needed for complex types.
  ```typescript
  /**
   * Parses pinyin from ASCII to UTF-8.
   */
  function parsePinyin(pinyin: string): string {
    // implementation
  }
  ```
- **Inline comments:** Add inline comments only when the logic is non-obvious (e.g., Unicode range handling, priority ordering). Do not add comments that merely restate what the code does.
- **TODO comments:** Use `# TODO:` or `// TODO:` for known missing features or edge cases, followed by a concise description. Do not leave empty TODOs.
