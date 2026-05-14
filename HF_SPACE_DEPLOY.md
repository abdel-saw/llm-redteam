# Deploying Red-Agent-S to Hugging Face Spaces

Step-by-step deployment guide. The steps marked **(manual)** require
your interaction (no token / no automation in this repo for them yet).

## 1. Prerequisites

- A free Hugging Face account: <https://huggingface.co/join>
- The HF CLI installed locally *(optional, only if you push via SSH)*:
  ```bash
  pip install -U "huggingface_hub[cli]"
  huggingface-cli login
  ```

## 2. Create the Space *(manual)*

1. Go to <https://huggingface.co/new-space>.
2. Fill in:
   - **Owner**: your HF handle (e.g. `abdel-saw` — confirm the handle
     matches the GitHub one).
   - **Space name**: `red-agent-s`
   - **License**: MIT (matches the GitHub repo).
   - **Space SDK**: **Docker** *(critical — not Gradio / Streamlit)*.
   - **Hardware**: CPU basic (free tier). 2 vCPU / 16 GB is sufficient
     for the MVP; the heavy lifting is done by Groq, not the Space.
   - **Visibility**: Public.
3. Click *Create Space*. HF creates an empty git repo at
   `https://huggingface.co/spaces/<owner>/red-agent-s`.

## 3. Configure secrets *(manual)*

In the new Space, open *Settings → Variables and secrets* and add:

| Type | Name | Value |
|---|---|---|
| Secret | `GROQ_API_KEY` | *(your Groq key)* |
| Secret | `OPENROUTER_API_KEY` | *(optional, can be left empty)* |
| Variable | `APP_DEPLOYED` | `true` *(switches on the "public demo" banner)* |
| Variable | `APP_ENV` | `prod` |

> **Why secret vs variable?** Secrets are encrypted-at-rest and not
> exposed to forks. Variables are plain config visible to anyone with
> read access to the Space settings. API keys MUST be secrets;
> harmless flags can be variables.

## 4. Push the code to the Space

The Space is its own git repo. Two options:

### Option A — second git remote *(simplest)*

From the GitHub repo, add HF as a second remote:

```bash
git remote add hf https://huggingface.co/spaces/<owner>/red-agent-s
git push hf main
```

You'll be prompted for HF credentials on the first push. HF supports
HTTPS basic-auth with a user access token (created in
*Settings → Access Tokens → New token*, scope *write*).

### Option B — GitHub Action *(automatable)*

If/when you want pushes to `main` to mirror to HF automatically, add
the following step to `.github/workflows/ci.yml` (gated behind a
`HF_TOKEN` secret in the GitHub repo settings):

```yaml
  deploy-hf:
    name: Deploy to Hugging Face Space
    runs-on: ubuntu-latest
    needs: [test, docker-build]
    if: github.event_name == 'push' && github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: huggingface/[email protected]
        with:
          token: ${{ secrets.HF_TOKEN }}
          repo-name: red-agent-s
          repo-type: space
          repo-owner: <owner>
```

*(Not enabled by default — keep manual until the first push works
end-to-end.)*

## 5. Watch the build

After `git push hf main`:

- HF reads the YAML frontmatter at the top of `README.md` (we set
  `sdk: docker`, `app_port: 7860`).
- HF runs `docker build .` against the root `Dockerfile`.
- The Space goes through `Building → Running` states (visible in the
  Space header). Build takes ~3–5 minutes on the first push, ~30 s on
  cached rebuilds.
- App is exposed on <https://`<owner>`-red-agent-s.hf.space>.

If the build fails: *Settings → Logs* shows the docker build output.

## 6. Notes specific to HF Spaces

- **Cold start** ≈ 30–60 s on free tier (CPU basic). The container is
  paused after extended inactivity and a new request triggers a
  full restart.
- **Free-tier sleep**: Spaces enter sleep after **48 h of inactivity**.
  The first visitor after that pays the full re-build / start
  latency. For demos during a defense: **ping the Space 1 h before**
  (a simple `curl https://<owner>-red-agent-s.hf.space/healthz`
  suffices) to keep it warm.
- **Persistent storage**: not available on the free tier. The SQLite
  DB at `/data/red-agent-s.db` is **ephemeral** — wiped on every
  container restart. Acceptable for a demo, not for an audit log.
  Paid tier provides persistent volumes if needed later.
- **Outbound network**: HF Spaces allow outbound HTTPS — Groq /
  OpenRouter calls work out of the box.
- **Inbound traffic**: HTTPS terminated by HF, the container only
  needs to listen on `0.0.0.0:7860` (handled by the Dockerfile CMD).
- **Logs**: real-time logs are in *Settings → Logs*. They include
  uvicorn output and any `print` from the app.

## 7. Post-deployment checklist

After the Space reports *Running*:

- [ ] Open `https://<owner>-red-agent-s.hf.space/` — see the "Démo
      publique" banner (driven by `APP_DEPLOYED=true`).
- [ ] Open `https://<owner>-red-agent-s.hf.space/healthz` — expect
      `{"status":"ok","version":"0.2.0","name":"Red-Agent-S"}`.
- [ ] Open `https://<owner>-red-agent-s.hf.space/docs` — confirm the
      OpenAPI schema is reachable and `/healthz` is intentionally
      hidden (`include_in_schema=False`).
- [ ] Configure a Groq target via the UI (use one of your own keys via
      the form — the value never leaves the Space).
- [ ] Launch a 1-category × 2-attempts scan; confirm SSE updates work
      live (no buffering).
- [ ] Click "Voir le rapport" at the end and verify the HTML renders.

## 8. Updating the live Space

For subsequent updates:

```bash
# from the GitHub repo, after merging changes to main
git push hf main
```

A short rebuild happens (~30 s with Docker layer cache). No
configuration to redo — secrets and variables persist across pushes.

## 9. Tearing down

*Settings → Delete this Space* — irreversible, removes the repo and
the running container. Secrets are wiped.
