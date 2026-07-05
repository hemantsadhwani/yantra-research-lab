# Setup — accounts & tokens for v1 (do this once, before deploying)

Get these in place **now** so building/deploying isn't blocked later. The golden rule:
**secrets go in `.env` (git-ignored) or the host's secrets manager — never in code, never in a
prompt, never committed.** You create them in your browser; no tool ever needs to *see* them.

**Good news for v1:** the only *paid* secret is the Anthropic API key. Everything else is a free
account or runs locally. **No auth/Clerk keys are needed** — v1 has no login.

---

## What you need (v1)

| # | Thing | Needed for | Cost | Blocks the build? |
|---|---|---|---|---|
| 1 | **GitHub account** | code + Vercel/Fly deploy | free | already have it ✓ |
| 2 | **Anthropic API key** | chatbot LLM + offline research runs | pay-per-token (set a cap) | no (only to *run*) |
| 3 | **Vercel account** | frontend hosting | free | no (only to *deploy*) |
| 4 | **Fly.io account** | backend (FastAPI) hosting | free tier | no (only to *deploy*) |
| 5 | **Domain** (optional) | branded URL | ~$12/yr | no |
| — | Qdrant, embeddings | vector store + embeddings | **run locally, no account** | — |

> **Nothing above is needed to *write* the code** — Fable builds code that reads secrets from
> `.env`. You only need these to *run and deploy*. Set them up in parallel.

---

## Local tools (install once)

- **Node.js 20+** — `node -v` (get from nodejs.org or `brew install node`)
- **Python 3.11+** — `python3 --version` (you already have this)
- **git** — you have it
- **Fly CLI** (`flyctl`) — install when you reach step 4: `brew install flyctl`

---

## Step 1 — GitHub ✓
Already done — this repo exists. Vercel and Fly both log in *with* GitHub, so no separate token now.

## Step 2 — Anthropic API key (the one paid secret) ⭐
1. Go to **console.anthropic.com** → sign in.
2. **Billing** → add a payment method and a small credit (e.g. $5–10 is plenty for a demo).
3. **⚠️ Set a spend limit:** Billing → **Usage limits** → set a **monthly cap** (e.g. $10). This is
   your safety net — the chatbot can't run up a surprise bill.
4. **API keys** → **Create Key** → name it `yantra-dev` → copy it **once** (starts `sk-ant-...`).
5. Paste it into your local `.env` as `ANTHROPIC_API_KEY=sk-ant-...` — **do not commit** (`.env` is
   already git-ignored).

> This same key powers both the chatbot and the offline research-lab runs. Separate from your
> Claude Max subscription (that powers Claude Code, not deployed apps).

## Step 3 — Vercel (frontend) — free
1. Go to **vercel.com** → **Sign Up** → **Continue with GitHub**.
2. That's it for now. At deploy time you'll **Import** this GitHub repo and point Vercel at the
   `frontend/` directory — Vercel gives you a free `*.vercel.app` URL automatically (custom domain
   optional later). No token to copy.

## Step 4 — Fly.io (backend) — free tier
1. Go to **fly.io** → **Sign Up** (GitHub works).
2. Install the CLI: `brew install flyctl`
3. `fly auth login` (opens a browser). Done — the CLI stores your credential locally.
4. At deploy time you'll run `fly launch` from the `backend/` directory (the Fable output includes
   a `fly.toml`). Scale-to-zero is the default, so it idles at ~$0.
5. *(Only if you set up CI auto-deploy later:)* create a deploy token with
   `fly tokens create deploy` and add it to GitHub repo secrets as `FLY_API_TOKEN`.

> Prefer AWS-native or find Fly odd? Google **Cloud Run** is the alternative (needs a GCP project +
> billing enabled + `gcloud`), but Fly is the lower-overhead choice for v1.

## Step 5 — Domain (optional, recommended before applying)
- Buy a `.com` from **Cloudflare** or **Namecheap** (~$12/yr), then add it to Vercel (frontend) and
  Fly (backend API subdomain). A branded URL sells the "real product" story better than
  `*.vercel.app`. Skip for the first deploy if you want.

## Not needed for v1 (deferred)
- **Clerk** (auth) — v2 only. No keys yet. See [docs/adr/0006-auth-rbac.md](docs/adr/0006-auth-rbac.md).
- **Qdrant Cloud** — v1 uses Qdrant in **local mode** (no account). Cloud is a later swap.
- **Voyage / OpenAI embeddings** — v1 uses **local** embeddings (no key).

---

## Final `.env` for v1 (local)
After the steps above, your local `.env` needs essentially one line:

```dotenv
ANTHROPIC_API_KEY=sk-ant-...          # from step 2 (with a spend cap set!)
# Everything else has safe local defaults; the Fable output ships a full .env.example.
```

## Checklist
- [ ] Anthropic API key created **+ monthly spend cap set**
- [ ] Vercel account (GitHub login)
- [ ] Fly.io account + `flyctl` installed + `fly auth login`
- [ ] Node.js 20+ and Python 3.11+ installed
- [ ] (optional) domain purchased
- [ ] `ANTHROPIC_API_KEY` in local `.env` (never committed)
