# Deploying to Railway

Two services in one Railway project: `backend` (FastAPI, Dockerfile-based,
with a persistent volume for its SQLite databases and uploads) and
`frontend` (Next.js, Dockerfile-based). Both Dockerfiles already exist in
this repo (`backend/Dockerfile`, `frontend/Dockerfile`) - Railway just needs
to be pointed at them.

This is a one-time setup. After it's done, every `git push` to `main`
redeploys both services automatically.

## 1. Push this repo to GitHub

Already done if `git remote -v` shows `origin` - just make sure everything
in this change is committed and pushed. Railway deploys from GitHub, not
from your machine.

## 2. Create the Railway project

1. Go to [railway.app](https://railway.app) and sign in with GitHub.
2. **New Project → Deploy from GitHub repo** → select this repo.
3. Railway will create one service and try to guess how to build it. Delete
   that first guess if it's wrong - you're about to add both services
   explicitly.

## 3. Add the backend service

1. **+ New → GitHub Repo** → this repo again.
2. Open the new service's **Settings**:
   - **Root Directory**: `backend`
   - Railway should auto-detect the `Dockerfile` there. If it offers a
     "Builder" choice, pick **Dockerfile**, not Nixpacks.
3. **Variables** tab, add:
   - `OPENAI_API_KEY` — your OpenRouter (or OpenAI) key.
   - `PYS_MODEL_NAME` = `openai/gpt-4o-mini` (matches what you're running
     locally - cheaper and enough for structured extraction; the code
     defaults to full `gpt-4o` if you don't set this).
   - Leave everything else at its default for now.
4. **Settings → Volumes → New Volume**:
   - **Mount path**: `/app/data`
   - Any size (1 GB is overkill for this).

   This is the one non-obvious step: without it, every deploy wipes the
   database and any generated designs, because the container filesystem
   itself isn't persistent. `docker-entrypoint.sh` re-seeds the checked-in
   knowledge base and supplier list into a fresh empty volume automatically
   on first boot - you don't need to upload anything.
5. **Settings → Networking → Generate Domain.** Copy the URL it gives you
   (looks like `backend-production-xxxx.up.railway.app`) - you need it in
   the next step.
6. Deploy. Watch the build logs; the first boot takes a little longer than
   normal because it builds the search index once (a handful of real
   embedding API calls) - that's expected, not a hang.

## 4. Add the frontend service

1. **+ New → GitHub Repo** → this repo again.
2. **Settings → Root Directory**: `frontend`, builder **Dockerfile**.
3. **Variables**:
   - `API_BASE_URL` = `https://<the backend domain from step 3.5>/api`
     (include the `/api` suffix, and `https://`, not `http://`).
4. **Settings → Networking → Generate Domain.** This is the URL you'll
   actually give people.
5. Deploy.

## 5. Verify

Open the frontend's Railway domain. You should see the marketing page.
Click **Start a production project**, submit a request, and confirm it
reaches brief review - that exercises the full path: frontend → backend →
model API → SQLite on the volume.

If it doesn't: check the backend service's logs first (`/api/health` on its
own domain is a quick way to see whether it's up and whether it thinks an
API key is configured), then the frontend's logs.

## Known limitations of this setup

- **Free tier**: Railway's trial credit is small and one-time; past that,
  billing is usage-based (routinely a few dollars a month for a project at
  this scale, more if the model calls or traffic scale up).
- **The knowledge base and supplier list only seed once per volume.** If
  you edit `backend/data/knowledge/*.md` or `backend/data/suppliers.json`
  and redeploy, the running volume already has its own copy and won't pick
  up the change automatically (the entrypoint only seeds an *empty*
  volume). To force a refresh, delete the volume in Railway's dashboard and
  let it reseed on the next boot - this also wipes any projects created so
  far, so only do it when that's acceptable.
- **CORS is not the blocker it looks like.** The frontend calls the backend
  entirely server-side (server components and server actions - see
  `frontend/lib/api.ts`), so the browser never talks to the backend
  directly and `PYS_CORS_ORIGINS` doesn't need to match the deployed
  domains for the app to work.
