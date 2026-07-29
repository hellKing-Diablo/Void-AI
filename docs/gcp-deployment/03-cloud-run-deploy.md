# Phase 3 — Deploying to Cloud Run

## What this phase is

> **What Cloud Run is.** A service that runs your container image and puts it on the internet
> with an HTTPS URL, without you managing any servers. You hand it an image; it handles TLS
> certificates, load balancing, restarts, and scaling. You're billed for the time your container
> is actually running, not for a reserved machine.
>
> The key idea to internalise: **Cloud Run scales your container down to zero when nobody is
> using it.** That's why it's cheap, and it's also the source of most of its surprising
> behaviour.

---

## The biggest decision: what *not* to deploy

Before any commands, this is the architectural choice that shaped the whole deployment.

### What upstream Omi actually runs

Reading their GitHub Actions workflows, production Omi is roughly **seven services across two
platforms**:

| Service | Platform | Deployed by |
|---|---|---|
| **pusher** | **GKE (Kubernetes)**, via Helm | `gcp_backend_pusher.yml` |
| backend | Cloud Run | `gcp_backend.yml` |
| backend-sync | Cloud Run | same |
| backend-sync-backfill | Cloud Run | same |
| backend-integration | Cloud Run | same |
| backend-listen | GKE, via Helm | same |
| llm-gateway | GKE, via Helm | `gcp_llm_gateway.yml` |

**VoidAI deploys one:** `backend`, on Cloud Run.

Nobody should run a seven-service, two-platform, Kubernetes-inclusive architecture for five
users. But dropping services means understanding what each one does, and one of them —
**pusher** — looked load-bearing.

### The pusher decision

Pusher is a separate service that relays events: live transcripts to clients, and triggers to
finish processing a conversation. There is **no official recipe for running pusher on Cloud
Run** — upstream runs it on Kubernetes. Improvising one felt wrong, so we checked whether it was
needed at all.

Two findings settled it.

**Finding 1 — live transcripts don't need pusher.** In `backend/routers/listen/transcripts.py`
around line 315:

```python
await self.host.request.websocket.send_json(client_segments)   # ← app gets transcripts HERE
...
if self.host.transcript_send is not None and ...:              # pusher path
    self.host.transcript_send(...)
elif not self.host.pusher_enabled and ...:                     # explicit no-pusher branch
    await trigger_realtime_integrations(...)                   # backend does it in-process
```

That first line is **unconditional**. Live transcripts go straight to the phone over the app's
own WebSocket connection. Pusher is only involved in relaying to *integrations*, and the code
has an explicit `not pusher_enabled` fallback that does the work in-process.

**Finding 2 — finalization DOES need something, and it isn't necessarily pusher.**
In `backend/utils/conversations/conversations.py` around line 110:

```python
if not self.host.request_conversation_processing and not is_listen_finalization_dispatch_enabled():
    logger.warning('Pusher unavailable; finalization remains queued conversation=%s', conversation_id)
    return False
```

Read it as: *"if there's no pusher **and** no Cloud Tasks, refuse to finalize."*

This explained a symptom seen while testing locally — conversations that never auto-completed
and sat in `in_progress` forever. Locally there was neither pusher nor Cloud Tasks, so both
halves of the condition were true and the function returned without doing anything.

**The resolution:** set `LISTEN_FINALIZATION_DISPATCH_MODE=cloud_tasks`. That makes the second
half false, the gate opens, and Cloud Tasks takes over pusher's finalization role. No Kubernetes
required.

**The consequence:** Cloud Tasks stopped being optional. It is now load-bearing infrastructure,
and if its configuration is wrong, conversations silently never finish. That is exactly what
happened after launch — see
[05-post-deploy-fixes.md](05-post-deploy-fixes.md#1-conversations-never-got-summarized).

---

## The cost decision

This was a real fork in the road and worth recording, because the "obvious" configuration is
five times more expensive.

The backend runs three background recovery loops. To keep them ticking continuously you need
`--min-instances=1` (never scale to zero) **and** `--no-cpu-throttling` (keep the CPU running
between requests). That combination means paying for a full vCPU 24 hours a day:

| Option | Flags | Rough cost | Trade-off |
|---|---|---|---|
| Always on | `--min-instances=1 --no-cpu-throttling` | **~$75/mo** | No cold starts, loops always tick |
| Warm, throttled | `--min-instances=1` | **~$15/mo** | No cold starts; loops tick only during traffic |
| **Scale to zero** ← chosen | neither flag | **~$5–15/mo** | Cold start 20–40s after idle |

### Why scale-to-zero is defensible here

The background loops matter less than they first appear. In `backend/main.py` around lines
219–227, `startup_event` runs `_drain_listen_finalization_jobs` and
`_drain_stale_processing_conversations` **on every container start**. So every cold start
performs a full recovery sweep. You trade continuous ticking for a sweep on each wake — the
safety net still exists, it just fires on a different trigger.

### The billing scare

Midway through this phase, Google support reported the free trial had expired (started 7 April
2026, ended 7 July 2026, credit gone, account closed). That looked fatal.

It wasn't — it was about a **different billing account**:

| Account | Status | Linked to the project? |
|---|---|---|
| `015D8A…` "My Billing Account" | closed, expired trial | No |
| `017C68…` "Firebase Payment" | **open** | **Yes** |

The project runs on the Firebase Payment account, which is open and working. There are no free
credits, so charges hit a real card — which is precisely why scale-to-zero was the right call.

Cloud Run also has a **permanent** free tier, separate from trial credits, that resets monthly
forever: 2 million requests, 180,000 vCPU-seconds, 360,000 GiB-seconds.

---

## The deploy — pass 1

```bash
source ~/voidai-env.sh
export TAG=$(git rev-parse --short HEAD)

gcloud run deploy voidai-backend \
  --image=$IMAGE:$TAG \
  --region=asia-south1 \
  --project=void-ai-489016 \
  --service-account=voidai-runtime@void-ai-489016.iam.gserviceaccount.com \
  --port=8080 \
  --memory=2Gi \
  --cpu=1 \
  --concurrency=20 \
  --timeout=3600 \
  --allow-unauthenticated \
  --env-vars-file=$HOME/voidai-run-env.yaml \
  --set-secrets=ENCRYPTION_SECRET=ENCRYPTION_SECRET:latest,OPENAI_API_KEY=OPENAI_API_KEY:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest,MODULATE_API_KEY=MODULATE_API_KEY:latest,PINECONE_API_KEY=PINECONE_API_KEY:latest,FIREBASE_API_KEY=FIREBASE_API_KEY:latest,REDIS_DB_PASSWORD=REDIS_DB_PASSWORD:latest
```

### Flag by flag

| Flag | What it does | Why this value |
|---|---|---|
| `--service-account` | The robot identity the container runs as | Everything the backend can do comes from this account's roles ([01-foundation.md](01-foundation.md#step-5--the-runtime-service-account)) |
| `--port=8080` | Port the container listens on | Matches `EXPOSE 8080` in the Dockerfile |
| `--memory=2Gi --cpu=1` | Resources per instance | 2 GiB is needed for the ML libraries; 1 vCPU is enough at this scale |
| `--concurrency=20` | Simultaneous requests per instance | With 5 users they share one instance. Too high risks memory pressure; too low spawns instances needlessly |
| `--timeout=3600` | Max request duration, 60 min | **This caps WebSocket sessions.** 3600s is Cloud Run's maximum. A recording session longer than an hour will be disconnected |
| `--allow-unauthenticated` | Cloud Run's own door is open | Auth is done *inside* the app by Firebase. Without this, Cloud Run would reject requests before your code ever sees them |
| `--env-vars-file` | Non-secret configuration | Readable, editable, version-controllable |
| `--set-secrets` | Secret values from Secret Manager | Fetched at container start; never in the image, never in a file, never in `describe` output |

> **Why env vars and secrets are split.** Config you'd happily paste in a chat goes in the YAML
> file. Anything that would be a problem if leaked goes in Secret Manager. The split also means
> you can rotate a key without redeploying — Secret Manager is read fresh on each container
> start.

---

## The two-pass problem

**The backend needs to know its own URL, but the URL doesn't exist until after the first
deploy.** Cloud Tasks has to be told where to call back, and that address is the service's own
public URL.

So pass 1 deploys without it, Google assigns the URL, and pass 2 sets it:

```bash
gcloud run services update voidai-backend \
  --region=asia-south1 \
  --project=void-ai-489016 \
  --update-env-vars=BASE_API_URL=https://voidai-backend-684741928652.asia-south1.run.app,LISTEN_FINALIZATION_TASKS_HANDLER_URL=https://voidai-backend-684741928652.asia-south1.run.app/v1/conversation-finalization-jobs/run
```

Two details that cost time:

- **`--update-env-vars` merges**; `--set-env-vars` would *replace* everything. Using the wrong
  one silently wipes your other 26 variables.
- **`LISTEN_FINALIZATION_TASKS_HANDLER_URL` must be the full endpoint path**, not the base URL.
  It's passed straight into `tasks_v2.HttpRequest(url=...)`, so Cloud Tasks POSTs to exactly
  that string. A base URL there produces 404s on every finalization.

Also worth knowing: **`API_BASE_URL` is not a backend variable.** Zero hits in backend source —
it belongs to the Flutter app. Setting it on the service does nothing.

### Your service answers on two hostnames

```
https://voidai-backend-684741928652.asia-south1.run.app   ← project-number form (used everywhere)
https://voidai-backend-zmnoueh3ba-el.a.run.app            ← hash form (what `describe` reports)
```

Both are live and route to the same service. Not a misconfiguration.

---

## Verifying it actually worked

"It deployed" is not "it works". Three checks, each proving something different.

**1 — the service responds**
```bash
curl -s https://voidai-backend-684741928652.asia-south1.run.app/v1/health
# {"status":"ok"}
```

**2 — the finalization gate is open**

In the startup logs, look for:
```
listen finalization via cloud_tasks: True
```
This is the gate from `conversations.py:110`. `True` means auto-timeout finalization will work.

**3 — Redis, Cloud Tasks, and Firestore all work — proven by one request**

A single authenticated probe to the Cloud Tasks handler returned **200**. That one status code
proves the entire chain, because of how the code is written: `try_acquire_job_run_lock`
(`backend/database/sync_jobs.py:857`) calls `r.set(...)` on the Redis client with **no
try/except and no fail-open wrapper**. If Redis were unreachable or the TLS setting wrong, that
call raises `ConnectionError` → 500. If the lock were held, → 409. A 200 only happens when the
`SET NX` genuinely succeeded.

So: **Cloud Tasks → OIDC verification → Redis over TLS → Firestore → 200.** Whole path, one
request.

> **A note on this style of verification.** It's worth finding the one request that can only
> succeed if everything behind it is healthy, rather than testing each component separately.
> Reading the code to find where it *doesn't* catch exceptions is what makes that possible.

---

## Final deployed configuration

Read back from the live service on 29 July 2026:

```
image        asia-south1-docker.pkg.dev/void-ai-489016/voidai/backend:9e7db6ad96
service acct voidai-runtime@void-ai-489016.iam.gserviceaccount.com
cpu 1 · memory 2Gi · port 8080
concurrency  20        timeout 3600s
maxScale     3         minScale (unset → 0, scales to zero)
CPU throttling: default (on)      startup-cpu-boost: true
```

### Environment variables (non-secret)

| Variable | Value |
|---|---|
| `GOOGLE_CLOUD_PROJECT` | `void-ai-489016` |
| `FIREBASE_PROJECT_ID` | `void-ai-489016` |
| `FIREBASE_AUTH_DOMAIN` | `void-ai-489016.firebaseapp.com` |
| `FIRESTORE_DATABASE_ID` | `(default)` |
| `BASE_API_URL` | the Cloud Run URL |
| `BUCKET_CHAT_FILES` | `voidai-chat-files` |
| `BUCKET_MEMORIES_RECORDINGS` | `voidai-memories-recordings` |
| `BUCKET_POSTPROCESSING` | `voidai-postprocessing` |
| `BUCKET_PRIVATE_CLOUD_SYNC` | `voidai-private-cloud-sync` |
| `BUCKET_SPEECH_PROFILES` | `voidai-speech-profiles` |
| `LISTEN_FINALIZATION_DISPATCH_MODE` | `cloud_tasks` ← **the pusher replacement** |
| `LISTEN_FINALIZATION_TASKS_QUEUE` | `listen-finalization` |
| `LISTEN_FINALIZATION_TASKS_HANDLER_URL` | full callback endpoint path |
| `SYNC_TASKS_PROJECT` / `_LOCATION` / `_INVOKER_SA` | project, `asia-south1`, runtime SA |
| `REDIS_DB_HOST` | `gorgeous-lab-118268.upstash.io` |
| `REDIS_DB_PORT` / `REDIS_DB_SSL` | `6379` / `true` |
| `PINECONE_INDEX_NAME` | `void-ai-memories` |
| `OPENAI_BASE_URL` | `https://api.openai.com/v1` |
| `STT_SERVICE_MODELS` / `STT_PRERECORDED_MODEL` | `modulate-velma-2` |
| `MODEL_QOS` | `max` |
| `MEMORY_MODE` | `off` |
| `ENVIRONMENT` / `OMI_ENV_STAGE` | `development` / `dev` |
| `LANGSMITH_TRACING` | `false` |

Secrets injected from Secret Manager: `ENCRYPTION_SECRET`, `OPENAI_API_KEY`,
`ANTHROPIC_API_KEY`, `MODULATE_API_KEY`, `PINECONE_API_KEY`, `FIREBASE_API_KEY`,
`REDIS_DB_PASSWORD`.

> **Note:** `ENVIRONMENT=development` and `OMI_ENV_STAGE=dev` are set on what is effectively your
> production backend. Harmless today, but worth revisiting before real users — some code paths
> may behave differently based on these.
