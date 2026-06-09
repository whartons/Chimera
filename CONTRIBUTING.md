# Contributing to Chimera

Thanks for your interest! Chimera is a **public, reusable** set of ComfyUI workflows, docs, and
orchestration glue. Contributions that keep it **generic, modular, and reproducible** are welcome.

> Building with an AI coding assistant? The machine-facing contributor brief is
> [`CLAUDE.md`](CLAUDE.md); this file is the human version. They agree — `CLAUDE.md` just has more
> operational detail.

## Quick start (no GPU required)

The core logic is unit-tested **without** a GPU or a running ComfyUI — the test suite mocks the
ComfyUI client, so you can develop and validate most changes on any machine.

```bash
git clone https://github.com/whartons/ComfyUI-Chimera
cd ComfyUI-Chimera
pip install -e ".[dev]"     # editable install + pytest & ruff; gives you the `chimera` command
python -m pytest            # the whole offline core
ruff check .                # lint (correctness rules)
```

(`pip install -r requirements-dev.txt` is a lighter alternative that installs the tools without
the package.) Once installed editable, the CLI is available as `chimera image --brand … ` as well
as `python scripts/generate.py image --brand …`.

End-to-end generation additionally needs a running ComfyUI at `127.0.0.1:8000` with the relevant
models — see [`docs/SETUP.md`](docs/SETUP.md) and each module's `models.md`.

## Repo philosophy — please respect it on every change

- **Public + reusable.** Everything tracked must be **brand-neutral** and shareable. No secrets, no
  brand assets, no personal workflow JSON in tracked paths.
- **Personal/brand data is gitignored.** Real brands live under `brands/<name>/` (ignored);
  `brands/_template/` and the public `brands/example-brand/` are the tracked starters. Private
  workflows go in `workflows/personal/` (ignored); sanitized ones in `workflows/templates/`.
- **Modular.** Each modality is self-contained under `modules/<name>/`. Adding or changing one
  modality shouldn't require touching another.
- **No large binaries.** Model weights, outputs, and caches are gitignored — reference models by
  name + source URL in [`docs/CATALOG.md`](docs/CATALOG.md), never commit weights.

## Adding a module or workflow

1. Create `modules/<name>/` with a `README.md`, `models.md` (model name + source URL + license +
   where the file goes), and a sanitized workflow template.
2. Add the canonical template to `workflows/templates/` (the module copy must stay identical —
   `tests/test_template_parity.py` enforces it).
3. Update `docs/CATALOG.md` with the model(s) and their license.
4. Keep any private/branded variant in `workflows/personal/` (gitignored), never a tracked path.

## Testing

- The GPU-free suite (`python -m pytest -q`) **must stay green**. CI (when enabled) runs it on every
  PR.
- **Add tests for new logic.** Pure logic lives in `scripts/brandkit/` and `scripts/agent/` and is
  testable without a server; follow the existing patterns (mocked `ComfyClient`, title-addressed
  graph nodes, schema-validated sidecars).
- Node-graph fillers should address nodes by stable `_meta.title` (see `scripts/brandkit/nodes.py`),
  never raw numeric ids.

## Security

Third-party ComfyUI node packs must be **security-reviewed and pinned** before adoption and on every
update — see [`SECURITY.md`](SECURITY.md). Never add a path that deserializes untrusted pickles or
sends prompts/data to an external endpoint without it being clearly opt-in and documented.

## Commits & pull requests

- **Conventional Commits**: `feat:`, `fix:`, `docs:`, `refactor:`, `chore:`, `test:` with an optional
  scope, e.g. `feat(video): add 2x latent upscaler`.
- Keep PRs focused; explain the *why*. If you changed behavior, say how you tested it (and paste
  output if a render was involved).
- By contributing you agree your work is licensed under the repo's [MIT License](LICENSE).
