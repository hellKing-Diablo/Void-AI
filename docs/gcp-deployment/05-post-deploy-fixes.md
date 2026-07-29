# Phase 5 — What Broke After Launch

## What this phase is

The app signed in, transcription streamed live, and it looked like the deployment was done. Then
real data started flowing and four things failed — none of which could have been caught locally,
because each depended on cloud infrastructure that doesn't exist on a laptop.

They're written up in the order they were found. Each follows the same shape: **symptom →
evidence from logs → root cause in code → fix**. That shape is the most transferable part of
this document.

---

## The diagnostic loop

Every one of these was found the same way. Worth internalising before the details:

```bash
# 1. What errors is the backend producing?
gcloud logging read \
  'resource.type=cloud_run_revision AND resource.labels.service_name=voidai-backend AND severity>=ERROR' \
  --project=void-ai-489016 --limit=20 --format='value(timestamp,textPayload)'

# 2. What happened in a specific time window?
gcloud logging read \
  'resource.type=cloud_run_revision AND resource.labels.service_name=voidai-backend
   AND timestamp>="2026-07-28T20:05:00Z" AND timestamp<="2026-07-28T20:15:00Z"' \
  --project=void-ai-489016 --limit=400 --order=asc --format='value(timestamp,textPayload)'
```

> **Reading Python tracebacks in Cloud Logging.** Each line of a traceback arrives as a separate
> log entry. The useful part — the exception type and message — is at the **bottom**, so `head`
> shows you uvicorn's plumbing and nothing else. Filter for `/app/` to find your own code:
> `| grep -E "/app/(routers|utils|database)/"`.

---

## 1. Conversations never got summarized

**Symptom:** you record, live transcripts appear on the phone, then nothing. No title, no
summary. The conversation just sits there.

### Evidence

```
ERROR:utils.conversations.lifecycle:listen finalization enqueue failed job=a56055db-…
  File "/app/utils/conversations/lifecycle.py", line 714, in request_finalization
    enqueue_listen_finalization_job(intent['job_id'], …)
  File "/app/utils/cloud_tasks.py", line 268, in enqueue_listen_finalization_job
  File "/app/utils/cloud_tasks.py", line 180, in _enqueue_named_task
    client.create_task(parent=parent, task=task)
google.api_core.exceptions.PermissionDenied: 403 The principal (user or service account)
lacks IAM permission "iam.serviceAccounts.actAs" for the resource
"voidai-runtime@void-ai-489016.iam.gserviceaccount.com"
```

### Root cause

When the backend creates a Cloud Task, it asks Google to attach an **OIDC identity token** to
that task so the handler can verify the callback is genuine and not a stranger hitting a public
URL. Attaching an identity to something is *acting as* that account, and requires
`iam.serviceAccounts.actAs`.

The service account had `roles/iam.serviceAccountTokenCreator` but **not**
`roles/iam.serviceAccountUser`, which is the role that grants `actAs`.

> **The counterintuitive part.** The account was trying to act as *itself*. Being an account and
> being permitted to act as that account are separate things in Google's IAM model. A service
> account does not automatically hold `serviceAccountUser` over itself.

### Fix

```bash
gcloud iam service-accounts add-iam-policy-binding \
  voidai-runtime@void-ai-489016.iam.gserviceaccount.com \
  --member="serviceAccount:voidai-runtime@void-ai-489016.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser" \
  --project=void-ai-489016
```

IAM takes up to a minute to propagate. Then force a cold start so the recovery sweep runs:

```bash
curl -s https://voidai-backend-684741928652.asia-south1.run.app/v1/health
```

### Why the data wasn't lost

`lifecycle.py:715` catches the failure and marks the job `route='queued'` — durable, not
dropped. But the sweep that drains queued jobs only runs at container startup or on a background
tick, and with scale-to-zero plus CPU throttling those ticks don't happen between requests. So
the job sat there. **The failure mode of `min-instances=0` isn't lost data, it's stalled data.**

### The forensic detour worth remembering

The user's real recording appeared to be gone. It wasn't. Querying Firestore directly showed
four conversations:

| Doc | Created | Segments | Status |
|---|---|---|---|
| `fc0a2554` | today 20:02 | **48 — intact** | stuck at `processing` |
| `506a1ad3` | today 20:08 | 0 | `completed`, discarded |
| `9a5ec5bb` | **Mar 21** | 4 | old local-backend data |
| `85bcb1ed` | **Mar 21** | 0 | old local-backend data |

Reading Firestore directly, without going through the app, is often the fastest way to tell
"data is gone" from "data is fine, the read path is broken":

```bash
TOKEN=$(gcloud auth print-access-token)
curl -s -H "Authorization: Bearer $TOKEN" \
  "https://firestore.googleapis.com/v1/projects/void-ai-489016/databases/(default)/documents/users/<UID>/conversations?pageSize=50"
```

**The two March documents also explained a scary-looking log line:**

```
ERROR:utils.encryption:Decryption failed for user <uid>:
ERROR:database.conversations:non-hexadecimal number found in fromhex() arg at position 0
```

Those were written by the **local** backend using the `ENCRYPTION_SECRET` in `backend/.env`,
which is a genuinely different value from the one in Secret Manager. Cloud Run cannot decrypt
them and never will.

Two details worth carrying forward:

- **An empty exception message after "Decryption failed" is the signature of `InvalidTag`** —
  AES-GCM's way of saying *wrong key*. `InvalidTag` has no message text.
- **`decrypt()` returns the original ciphertext on failure** (`utils/encryption.py`), so the
  caller then tries `bytes.fromhex()` on base64 and reports a confusing hex error. The hex error
  is a *symptom two steps downstream* of the real problem.

---

## 2. Chat was completely dead

**Symptom:** the chat tab did nothing at all.

### Evidence

```
GET  /v2/messages → 500     (routers/chat.py:551, get_messages)
POST /v2/messages → 500     (routers/chat.py:376, send_message)

grpc_status: 9
"The query requires an index. You can create it here: https://console.firebase.google.com/…"
```

### Root cause

> **What a Firestore composite index is.** Firestore automatically indexes single fields. But if
> a query **filters on one field and sorts by a different one**, it needs a purpose-built
> composite index. Without it the query doesn't run slowly — it fails outright with
> `FAILED_PRECONDITION` (gRPC status 9). This is by design: Firestore refuses queries it can't
> serve at predictable speed.

`database/chat.py:227` filters `chat_session_id == …` and orders by `created_at` descending. No
index existed for that pair.

### Fix

```bash
gcloud firestore indexes composite create \
  --collection-group=messages \
  --query-scope=COLLECTION \
  --field-config=field-path=chat_session_id,order=ascending \
  --field-config=field-path=created_at,order=descending \
  --project=void-ai-489016 --async
```

**Use `--async`.** Without it, gcloud blocks and polls, which looks exactly like a hang — the
first attempt appeared stuck for 5+ minutes. The index was building fine; gcloud was just
waiting. Ctrl-C is always safe; the build continues server-side.

Check state:
```bash
gcloud firestore indexes composite list --project=void-ai-489016 --format='value(name,state)'
```

---

## 3. Action items never reached the tasks page

**Symptom:** conversations correctly extracted to-do items and showed them on the conversation
detail page, but the dedicated Tasks page was permanently empty.

### The clue: two different storage locations

| Screen | Reads from |
|---|---|
| Conversation detail | `structured.action_items`, **embedded in the conversation document** |
| Tasks page | `users/{uid}/action_items`, a **separate collection** |

The first was populated. The second was empty. So the *copier* between them was failing.

### Evidence

```
ERROR:utils.executors:Background task failed: _save_action_items:
  400 The query requires an index.
  File "/app/utils/conversations/process_conversation.py", line 869, in _save_action_items
    old_items = action_items_db.get_action_items_by_conversation(uid, conversation.id)
  File "/app/database/action_items.py", line 459, in get_action_items
```

### Root cause

A **second** missing index. `_save_action_items` first calls
`get_action_items_by_conversation()` to clear stale entries before writing new ones — and that
query filters `conversation_id ==` and orders by `created_at` descending. It threw before
writing anything.

**Why it was silent:** `_save_action_items` is submitted to a background thread pool at
`process_conversation.py:1268`:

```python
submit_with_context(postprocess_executor, _save_action_items, uid, conversation)
```

The exception never reached the HTTP response. The conversation looked perfectly processed. Only
the server logs knew.

> **The lesson.** When a feature silently does nothing while everything around it works, look
> for work happening on a background executor. A failure there is invisible to the client by
> construction.

### Fix

```bash
gcloud firestore indexes composite create \
  --collection-group=action_items \
  --query-scope=COLLECTION \
  --field-config=field-path=conversation_id,order=ascending \
  --field-config=field-path=created_at,order=descending \
  --project=void-ai-489016 --async
```

### Two gotchas that cost an extra round trip

**`CREATING` is not `READY`.** A reprocess attempted while the index was still building failed
with the identical error. A half-built index behaves exactly like a missing one. Always confirm
`READY` first:

```bash
gcloud firestore indexes composite list --project=void-ai-489016 \
  --format='value(name,state)' | grep action_items
```

**Existing items don't backfill.** `_save_action_items` only runs during processing, and failed
runs aren't retried. Conversations processed before the fix need an explicit reprocess — via the
app's conversation menu, or `POST /v1/conversations/{id}/reprocess`.

---

## 4. Daily recaps were never generated

**Symptom:** the home page showed only the mind map, with no Daily Recaps section at all.

### Root cause: the generator was never deployed

`app/lib/pages/home/home_content.dart:95` hides the section entirely when there are no
summaries:

```dart
if (_loadingSummaries || _recentSummaries.isNotEmpty) ...[
```

There were none, and there never would be. The generation path is:

```
modal/job.py  →  utils/other/jobs.py: start_job()
              →  utils/other/notifications.py: start_cron_job()
              →  send_daily_summary_notification()
```

`modal/job.py` is a **standalone script**, not part of the FastAPI app. Upstream Omi runs it on
an hourly schedule as a separate process. The Cloud Run service runs only `uvicorn main:app` —
nothing in it ever calls that entry point.

> **This is a class of bug worth naming.** When you deploy "the backend" of a project that
> upstream runs as several processes, the ones you didn't deploy fail *silently* — there's no
> error, because no code is running to produce one. Check for scheduled/worker entry points
> whenever you consolidate a multi-service app into one container.

### Fix: a Cloud Run Job plus Cloud Scheduler

> **Cloud Run Job vs Cloud Run Service.** A *service* runs continuously and answers HTTP
> requests. A *job* runs a command once, to completion, and exits. Same image, different
> execution model. Perfect for a cron task.

```bash
# 0. Enable the scheduler API
gcloud services enable cloudscheduler.googleapis.com --project=void-ai-489016

# 1. Create the job — same image, different entrypoint
gcloud run jobs create voidai-cron \
  --image=asia-south1-docker.pkg.dev/void-ai-489016/voidai/backend:9e7db6ad96 \
  --region=asia-south1 --project=void-ai-489016 \
  --service-account=voidai-runtime@void-ai-489016.iam.gserviceaccount.com \
  --command=python --args=modal/job.py \
  --cpu=1 --memory=2Gi --task-timeout=900 --max-retries=1 \
  --env-vars-file=$HOME/voidai-job-env.yaml \
  --set-secrets=ENCRYPTION_SECRET=ENCRYPTION_SECRET:latest,OPENAI_API_KEY=OPENAI_API_KEY:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest,MODULATE_API_KEY=MODULATE_API_KEY:latest,PINECONE_API_KEY=PINECONE_API_KEY:latest,FIREBASE_API_KEY=FIREBASE_API_KEY:latest,REDIS_DB_PASSWORD=REDIS_DB_PASSWORD:latest

# 2. Required — see below
gcloud run jobs update voidai-cron --region=asia-south1 --project=void-ai-489016 \
  --update-env-vars=PYTHONPATH=/app

# 3. Test before scheduling
gcloud run jobs execute voidai-cron --region=asia-south1 --project=void-ai-489016 --wait

# 4. Let Scheduler invoke it
gcloud run jobs add-iam-policy-binding voidai-cron \
  --region=asia-south1 --project=void-ai-489016 \
  --member=serviceAccount:voidai-runtime@void-ai-489016.iam.gserviceaccount.com \
  --role=roles/run.invoker

# 5. Schedule hourly
gcloud scheduler jobs create http voidai-cron-hourly \
  --location=asia-south1 --project=void-ai-489016 \
  --schedule="0 * * * *" --time-zone="Etc/UTC" \
  --uri="https://run.googleapis.com/v2/projects/void-ai-489016/locations/asia-south1/jobs/voidai-cron:run" \
  --http-method=POST \
  --oauth-service-account-email=voidai-runtime@void-ai-489016.iam.gserviceaccount.com
```

### Why `PYTHONPATH=/app` is mandatory

First run failed:

```
File "/app/modal/job.py", line 8, in <module>
    from utils.other.jobs import start_job
ModuleNotFoundError: No module named 'utils'
```

> **Python puts the *script's* directory on `sys.path`, never the working directory.** Running
> `python modal/job.py` puts `/app/modal` on the path. `utils/` lives at `/app`, so it's
> invisible.

Upstream avoids this differently — `backend/modal/Dockerfile.notifications_job` ends with:

```dockerfile
COPY backend/ .
COPY backend/modal/ .        # flattens modal/ INTO /app
CMD ["python", "job.py"]
```

They build a **separate image** where `job.py` sits next to `utils/`. Setting `PYTHONPATH=/app`
reaches the same end state without maintaining a second Dockerfile, second build, and second tag
to keep in sync.

### Why hourly and not daily

`send_daily_summary_notification()` groups all world timezones by their *current local hour*,
then finds users whose configured preference matches. A once-a-day trigger would only ever serve
one slice of the globe. The job must tick every hour and decide for itself.

### Why a correct run can still produce nothing

The first green run logged:

```
INFO:utils.other.notifications:start_cron_job at UTC hour 21
INFO:utils.other.notifications:No users found in time zone
```

That's correct behaviour, not a failure. A user qualifies only when **all four** hold
(`database/notifications.py:281`):

| Requirement | Default if unset |
|---|---|
| `time_zone` set on the user document | — (required) |
| `daily_summary_enabled` is not `False` | enabled |
| `daily_summary_hour_local` equals current local hour | **22** (`notifications.py:102`) |
| At least one token in `users/{uid}/fcm_tokens` | — (required) |

The run happened at 21:31 UTC = **03:01 IST**. Hour 3 ≠ 22, so it correctly skipped. The recap
generates on the **17:00 UTC** tick, when Asia/Kolkata reads 22:30.

To generate one immediately without waiting: the app's Settings → Daily Summary settings has a
test generator, which calls `POST /v1/users/daily-summary-settings/test` and bypasses the hour
check entirely.

---

## Reading the job's logs

Cloud Run **Jobs** log under a different resource type than services — the service filter will
show you nothing:

```bash
gcloud logging read \
  'resource.type=cloud_run_job AND resource.labels.job_name=voidai-cron' \
  --project=void-ai-489016 --limit=30 --format='value(timestamp,textPayload)'
```

Healthy output looks like:
```
INFO:__main__:Starting job...
INFO:utils.other.notifications:start_cron_job at UTC hour 21
Container called exit(0).
```

`exit(0)` is success. `exit(1)` means the script raised.

---

## Summary of everything fixed in this phase

| Problem | Root cause | Fix |
|---|---|---|
| Conversations never summarized | Missing `roles/iam.serviceAccountUser` | IAM binding |
| Chat 500s | Missing `messages` composite index | Create index |
| Tasks page empty | Missing `action_items` composite index | Create index + reprocess |
| No daily recaps | Cron entry point never deployed | Cloud Run Job + Scheduler + `PYTHONPATH` |

**Neither index is in `firestore.indexes.json`.** They exist only in the live project. If you
rebuild, recreate them by hand or add them to the repo file first.
