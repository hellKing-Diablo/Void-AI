# How VoidAI Differs from Upstream Omi

Every deliberate divergence from `github.com/BasedHardware/omi`, and why. Read this before
merging upstream changes — these are the places a merge is likely to conflict or silently undo
something.

---

## 1. Architecture — one service instead of seven

**Upstream production:**

| Service | Platform |
|---|---|
| pusher | GKE (Kubernetes), Helm |
| backend | Cloud Run |
| backend-sync | Cloud Run |
| backend-sync-backfill | Cloud Run |
| backend-integration | Cloud Run |
| backend-listen | GKE, Helm |
| llm-gateway | GKE, Helm |

**VoidAI:** `backend` on Cloud Run. That's it.

**Why:** a seven-service, two-platform architecture including Kubernetes is not a sensible thing
to operate for five users. Each omitted service was checked against the code before dropping it.

**The one that needed real work:** pusher. See below.

---

## 2. Cloud Tasks replaces pusher for finalization

**Upstream:** pusher (on Kubernetes) relays events and triggers conversation finalization.

**VoidAI:** `LISTEN_FINALIZATION_DISPATCH_MODE=cloud_tasks`, with a `listen-finalization` queue.

**Why it works:** `backend/utils/conversations/conversations.py:110` gates finalization on
*either* pusher *or* Cloud Tasks:

```python
if not self.host.request_conversation_processing and not is_listen_finalization_dispatch_enabled():
    logger.warning('Pusher unavailable; finalization remains queued conversation=%s', conversation_id)
    return False
```

Setting the dispatch mode makes the second condition false and the gate opens.

**What was verified as *not* needing pusher:** live transcripts. `routers/listen/transcripts.py`
sends to the app's WebSocket unconditionally, and there's an explicit `not pusher_enabled`
branch that runs realtime integrations in-process.

**Consequences to remember:**
- Cloud Tasks is now load-bearing. Misconfigure it and conversations silently never finish.
- Anything else pusher does upstream that we haven't exercised is untested here.
- Without *both* pusher and Cloud Tasks — e.g. running locally — auto-timeout finalization does
  not work at all. That's the code doing what it says, not a bug.

---

## 3. Region: asia-south1

**Upstream:** us-central1 and similar.

**VoidAI:** everything in `asia-south1` (Mumbai), because Firestore was created there and a
Firestore location is permanent.

Watch for hardcoded regions in any upstream deployment scripts you adopt.

---

## 4. Build: the base image must be overridden

`backend/Dockerfile` line 1:

```dockerfile
ARG PYTHON_BASE_IMAGE=gcr.io/based-hardware-dev/python:3.11-slim-forky
```

That registry is **private to Omi**. Every build from a fork must pass:

```bash
--build-arg PYTHON_BASE_IMAGE=python:3.11-slim
```

**This is permanent**, not a one-off. Any upstream Dockerfile change will keep this default, and
forgetting the flag reproduces the `403 Forbidden` every time.

---

## 5. The hourly cron runs as a Cloud Run Job

**Upstream:** `backend/modal/Dockerfile.notifications_job` builds a **separate image** that
flattens `backend/modal/` into `/app`, so `job.py` sits beside `utils/`:

```dockerfile
COPY backend/ .
COPY backend/modal/ .
CMD ["python", "job.py"]
```

**VoidAI:** the same backend image, run as a Cloud Run Job with `--command=python
--args=modal/job.py` and **`PYTHONPATH=/app`**.

**Why:** one image to build, push, and keep in sync instead of two. The `PYTHONPATH` env var
achieves the same import resolution the flattening does.

**Cost of this choice:** the job is pinned to an image tag and does **not** follow the service.
Every backend deploy needs a matching `gcloud run jobs update`.

---

## 6. Tracked source changes

Only one file in the repo differs for deployment reasons, plus one behavioural commit.

### `app/android/settings.gradle:26`

```diff
- id "org.jetbrains.kotlin.android" version "2.1.0" apply false
+ id "org.jetbrains.kotlin.android" version "2.2.21" apply false
```

`webview_flutter_android 4.10.11` requires Kotlin 2.2.21; its Java extends Kotlin classes
generated in the same module, so an older toolchain produces ~100 `cannot find symbol` errors.
Eight plugins in the cache want newer than 2.1.0.

**On merge:** if upstream bumps Kotlin, take theirs.

### Commit `9e7db6ad96` — "Make Redis TLS env-driven; collapse duplicate executors import"

Upstream assumed a non-TLS Redis. Upstash requires TLS. `REDIS_DB_SSL=true` now selects
`SSLConnection` at runtime.

---

## 7. Local config that is gitignored — invisible to git, easy to lose

These files are **not tracked**, so nothing in git records that they differ from what `setup.sh`
would write. This document is their only record.

| File | State | Why |
|---|---|---|
| `app/android/app/src/dev/google-services.json` | Replaced with `void-ai-489016` config | Was Omi's `based-hardware-dev` |
| `app/lib/firebase_options_dev.dart` | Android block repointed to `void-ai-489016` | `Firebase.initializeApp(options:)` overrides the JSON |
| `app/.dev.env` | `API_BASE_URL` = Cloud Run URL; both auth flags `false` | `setup.sh` sets Omi's URL and flips both to `true` |
| `app/android/key.properties` | **Deleted** (backed up outside the repo) | Pointed at Omi's shared debug keystore — private key is public in their repo |

⚠️ **Running `app/setup.sh` reverts all four.** See
[04-android-app.md](04-android-app.md#the-root-cause-of-nearly-everything-setupsh).

---

## 8. Firestore indexes not in the repo

`firestore.indexes.json` ships 13 index definitions, all deployed. Two more were required in
production and are **not** in that file:

| Collection | Fields | Needed by |
|---|---|---|
| `messages` | `chat_session_id` ASC, `created_at` DESC | Chat (`database/chat.py:227`) |
| `action_items` | `conversation_id` ASC, `created_at` DESC | Task page (`database/action_items.py:459`) |

Whether upstream has these declared elsewhere or relies on manual creation is unknown. Either
way, a rebuild from this repo alone produces a broken chat and a broken task page.

A static sweep of `backend/database/*.py` found roughly 25 query shapes that combine a filter
with an order-by on a different field — the pattern that requires a composite index. Most either
already have one or use filter combinations that only trigger with specific parameters. Expect
occasional new "requires an index" errors as features get exercised; the error always contains
the exact creation URL.

---

## 9. Speech-to-text

**Current:** Modulate, model `modulate-velma-2` (`STT_SERVICE_MODELS`, `STT_PRERECORDED_MODEL`).

**Planned:** Soniox routed by language, because Modulate does not support Gujarati. Target
languages are Gujarati, Hindi, English, and code-switched mixes. Design work was done in July
2026; not yet implemented.

---

## 10. Output language — investigated, then closed with no code

Worth recording because it prevents re-doing work.

The plan had been to force all LLM-generated output (summaries, memories) to English while
transcripts stay in the spoken language. **That feature already exists upstream.**

`backend/utils/llm/conversation_processing.py:1086`:
```python
response_language = output_language_code or language_code
```
feeding a prompt that says *"The content language is {language_code}. You MUST respond entirely
in {response_language}."*

And `output_language_code` comes from a per-user Firestore setting
(`utils/conversations/process_conversation.py:176`):
```python
user_language = users_db.get_user_language_preference(uid) or language_code
```

It's threaded through all seven structuring and memory calls. Set it to `en` and summaries,
memories and action items come out in English while transcripts keep the spoken language.

**How to set it:** `PATCH /v1/users/language` with `{"language": "en"}`, or the language setting
in the app UI, which calls the same endpoint.

**No code change is needed. Do not reimplement this.**

---

## What to watch when merging upstream

| Area | Risk |
|---|---|
| `backend/Dockerfile` | Base image default stays private — the `--build-arg` is still required |
| `app/setup.sh` | Will still overwrite your config. Never run it |
| `app/android/settings.gradle` | Kotlin version conflict — take upstream's if newer |
| Pusher-related code | Upstream may add code paths assuming pusher exists |
| `modal/` scripts | New scheduled entry points would also need deploying as jobs |
| `firestore.indexes.json` | New queries may need new indexes |
| Deployment workflows | `.github/workflows/gcp_backend.yml` assumes Omi's project and regions |
