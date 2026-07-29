# Phase 1 — Google Cloud Foundation

> **Note on this file.** Phase 1 was done partly in the browser console and partly in a chat
> whose transcript no longer exists. So unlike the other phase files, this is **not** a replay
> of commands actually typed. It is a *reconstruction*: every resource below was read back from
> the live project on 29 July 2026, and the commands shown are the ones that would recreate
> exactly what's there. Treat it as a working recipe for rebuilding, not as history.

---

## What this phase is

Before code can run in the cloud, the cloud needs the surrounding scaffolding: somewhere to
store data, somewhere to store your packaged code, an identity for the server to act as, and a
safe place for API keys. None of it runs anything. It's all setup.

## Project identity

| | |
|---|---|
| Project ID | `void-ai-489016` |
| Project number | `684741928652` |
| Region | `asia-south1` (Mumbai) |
| Billing account | `017C68-3616AC-931D93` ("Firebase Payment") — open, **no trial credits** |

### Why asia-south1, and why you can't change it

Firestore was created in `asia-south1` first. **A Firestore database's location is permanent** —
there is no move, no migrate, no console button. The only way to change it is to create a new
project and copy all data across.

Everything else then has to follow it. If your server sits in one region and your database in
another, every single read and write pays a cross-region round trip — slower for users and
billed as network egress. So the region wasn't really a decision; it was a consequence.

**If you ever rebuild from scratch, choose the region deliberately at the Firestore step**,
because that's the one that locks.

---

## Step 1 — Enable the APIs

> **What this is.** Google Cloud ships with almost everything switched off. "Enabling an API"
> means turning on a product for your project. It costs nothing by itself — you only pay for
> what you then use. Forgetting one produces a confusing `PERMISSION_DENIED` or
> `SERVICE_DISABLED` error much later, so it's worth doing all at once.

```bash
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  cloudtasks.googleapis.com \
  cloudscheduler.googleapis.com \
  storage.googleapis.com \
  iamcredentials.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  identitytoolkit.googleapis.com \
  fcm.googleapis.com \
  firebase.googleapis.com \
  --project=void-ai-489016
```

What each one is for, in one line:

| API | Why it's needed |
|---|---|
| `run` | Cloud Run — runs the backend container |
| `artifactregistry` | Stores the packaged container image |
| `firestore` | The main database |
| `secretmanager` | Stores API keys safely |
| `cloudtasks` | Queues background work (conversation finalization) |
| `cloudscheduler` | Triggers the hourly job that makes daily recaps |
| `storage` | The five file buckets |
| `iamcredentials` | Lets the server mint identity tokens for Cloud Tasks |
| `logging`, `monitoring` | Where logs and metrics go |
| `identitytoolkit`, `fcm`, `firebase` | Firebase Auth and push notifications |

---

## Step 2 — Firestore

> **What this is.** Firestore is a NoSQL document database. Instead of tables and rows it stores
> JSON-like documents in nested collections. In VoidAI everything user-facing lives here:
> `users/{uid}/conversations`, `users/{uid}/messages`, `users/{uid}/action_items`, and so on.

```bash
gcloud firestore databases create \
  --location=asia-south1 \
  --type=firestore-native \
  --project=void-ai-489016
```

Current state: one database, `(default)`, `FIRESTORE_NATIVE`, `PESSIMISTIC` concurrency.

### Indexes

Firestore needs a **composite index** whenever a query filters on one field and sorts by a
different one. Without it the query doesn't run slowly — it fails outright with a 400.

The repo ships 13 index definitions in `firestore.indexes.json`, all of which are deployed:

```bash
firebase deploy --only firestore:indexes --project void-ai-489016
```

Two more indexes had to be created by hand after launch because they aren't in that file. They
are the cause of two production outages — full story in
[05-post-deploy-fixes.md](05-post-deploy-fixes.md):

| Collection | Fields |
|---|---|
| `messages` | `chat_session_id` ASC, `created_at` DESC |
| `action_items` | `conversation_id` ASC, `created_at` DESC |

**These two exist only in the live project, not in the repo.** If you rebuild, you must create
them manually or add them to `firestore.indexes.json` first.

---

## Step 3 — Artifact Registry

> **What this is.** A private registry for container images — think of it as your own Docker
> Hub. When you build the backend into an image, you push it here, and Cloud Run pulls it from
> here. It must be in the same region as Cloud Run to avoid cross-region pulls on every cold
> start.

```bash
gcloud artifacts repositories create voidai \
  --repository-format=docker \
  --location=asia-south1 \
  --project=void-ai-489016
```

Images then live at:
```
asia-south1-docker.pkg.dev/void-ai-489016/voidai/backend:<tag>
```

---

## Step 4 — Storage buckets

> **What this is.** Cloud Storage holds files — audio recordings, uploaded chat attachments,
> intermediate processing artifacts. Firestore holds structured data; buckets hold blobs.
> Bucket names are globally unique across all of Google Cloud, which is why they're prefixed
> `voidai-`.

```bash
for b in voidai-speech-profiles voidai-postprocessing voidai-memories-recordings \
         voidai-chat-files voidai-private-cloud-sync; do
  gcloud storage buckets create gs://$b \
    --location=asia-south1 --project=void-ai-489016
done
```

| Bucket | Holds | Backend env var |
|---|---|---|
| `voidai-speech-profiles` | Voice fingerprints for speaker identification | `BUCKET_SPEECH_PROFILES` |
| `voidai-postprocessing` | Intermediate audio during processing | `BUCKET_POSTPROCESSING` |
| `voidai-memories-recordings` | Saved conversation audio | `BUCKET_MEMORIES_RECORDINGS` |
| `voidai-chat-files` | Files attached to chat messages | `BUCKET_CHAT_FILES` |
| `voidai-private-cloud-sync` | Private-cloud sync payloads | `BUCKET_PRIVATE_CLOUD_SYNC` |

---

## Step 5 — The runtime service account

> **What this is.** A service account is a *robot user*. When the backend runs on Cloud Run, it
> isn't "you" — it's this identity. Every permission the backend has is a permission granted to
> this account, and nothing more. This is why a missing role shows up as a 403 in production
> even though everything worked on your laptop, where you were running as yourself with owner
> rights.

```bash
gcloud iam service-accounts create voidai-runtime \
  --display-name="VoidAI Cloud Run runtime" \
  --project=void-ai-489016
```

Full identity: `voidai-runtime@void-ai-489016.iam.gserviceaccount.com`

### Project-level roles

```bash
SA=voidai-runtime@void-ai-489016.iam.gserviceaccount.com
for role in \
  roles/datastore.user \
  roles/storage.objectAdmin \
  roles/secretmanager.secretAccessor \
  roles/cloudtasks.enqueuer \
  roles/firebaseauth.admin \
  roles/logging.logWriter \
  roles/monitoring.metricWriter ; do
  gcloud projects add-iam-policy-binding void-ai-489016 \
    --member="serviceAccount:$SA" --role="$role"
done
```

| Role | What it lets the backend do | If missing you'd see |
|---|---|---|
| `datastore.user` | Read/write Firestore | 403 on every request |
| `storage.objectAdmin` | Read/write the buckets | Audio uploads fail |
| `secretmanager.secretAccessor` | Read the 7 API keys at startup | Container won't boot |
| `cloudtasks.enqueuer` | Add jobs to the queue | Conversations never finalize |
| `firebaseauth.admin` | Verify user login tokens | Every request 401s |
| `logging.logWriter` | Write logs | Silent server, no diagnostics |
| `monitoring.metricWriter` | Write metrics | No metrics |

### Roles the account holds *on itself*

This part is unusual and caused a production outage, so it's worth understanding.

```bash
SA=voidai-runtime@void-ai-489016.iam.gserviceaccount.com

# Lets the backend create tasks that authenticate AS itself
gcloud iam service-accounts add-iam-policy-binding $SA \
  --member="serviceAccount:$SA" \
  --role="roles/iam.serviceAccountUser" --project=void-ai-489016

gcloud iam service-accounts add-iam-policy-binding $SA \
  --member="serviceAccount:$SA" \
  --role="roles/iam.serviceAccountTokenCreator" --project=void-ai-489016

# Lets the Cloud Tasks service itself mint tokens for this account
gcloud iam service-accounts add-iam-policy-binding $SA \
  --member="serviceAccount:service-684741928652@gcp-sa-cloudtasks.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountTokenCreator" --project=void-ai-489016
```

**Why `serviceAccountUser` on itself is not redundant.** When the backend creates a Cloud Task,
it asks Google to attach an identity token to that task so the handler can verify the call is
genuine. Attaching an identity to something is called *acting as* that account, and it requires
`iam.serviceAccounts.actAs` — granted by `roles/iam.serviceAccountUser`.

Being the account is not the same as being allowed to *act as* the account. We had
`serviceAccountTokenCreator` but not `serviceAccountUser`, and every conversation silently
failed to finalize. See [05-post-deploy-fixes.md](05-post-deploy-fixes.md#1-conversations-never-got-summarized).

---

## Step 6 — Secrets

> **What this is.** Secret Manager is a vault. The alternative — putting API keys in environment
> variables or baking them into the image — means anyone who can read your deployment config or
> pull your image gets your keys. With Secret Manager, Cloud Run fetches the value at container
> start and it never appears in a file, in the image, or in `gcloud run services describe`
> output.

```bash
for s in ENCRYPTION_SECRET OPENAI_API_KEY ANTHROPIC_API_KEY MODULATE_API_KEY \
         PINECONE_API_KEY FIREBASE_API_KEY REDIS_DB_PASSWORD; do
  gcloud secrets create $s --replication-policy=automatic --project=void-ai-489016
done

# then add a value to each (note: printf, NOT echo — see warning below)
printf '%s' 'THE_ACTUAL_VALUE' | \
  gcloud secrets versions add OPENAI_API_KEY --data-file=- --project=void-ai-489016
```

⚠️ **Use `printf`, never `echo`.** `echo` appends a newline, and that newline becomes part of the
secret. For an API key you'd get mysterious auth failures. For `ENCRYPTION_SECRET` it's worse:
the key would differ by one byte, and **every piece of data encrypted with the other version
becomes permanently unreadable.**

### About ENCRYPTION_SECRET specifically

This is the master key from which each user's personal encryption key is derived
(`backend/utils/encryption.py`). It has to be at least 32 bytes or the backend refuses to start.

**There is no recovery if it changes.** Data encrypted with the old value cannot be decrypted
with the new one — you get an `InvalidTag` error and the content is gone.

This already bit us. The value in `backend/.env` (used when running locally) is **different**
from the one in Secret Manager (69 characters vs 64, genuinely different strings, not a quoting
artifact). Conversations recorded through the local backend in March 2026 cannot be read by the
Cloud Run backend and never will be. They show up in the logs as:

```
ERROR:utils.encryption:Decryption failed for user <uid>:
ERROR:database.conversations:non-hexadecimal number found in fromhex() arg at position 0
```

Two dead test conversations, harmless — but a warning about what a mismatched key costs.

---

## Step 7 — Cloud Tasks queue

> **What this is.** A durable job queue. When a conversation ends, the work of summarizing it
> shouldn't happen inside the user's request — it's slow and involves several AI calls. Instead
> the backend drops a job on this queue, and Cloud Tasks calls the backend back a moment later
> to do the work. If that call fails, Cloud Tasks retries it automatically.

```bash
gcloud tasks queues create listen-finalization \
  --location=asia-south1 --project=void-ai-489016
```

Current config: `maxAttempts: 100`, `minBackoff: 0.1s`, `maxBackoff: 3600s`, `maxDoublings: 16`.
Generous retry behaviour — a transient failure won't lose a conversation.

**In upstream Omi this queue's job is done by a separate "pusher" service running on Kubernetes.**
Using Cloud Tasks instead is the single biggest architectural difference in this deployment. See
[03-cloud-run-deploy.md](03-cloud-run-deploy.md#the-pusher-decision).

---

## Step 8 — External (non-Google) services

Four services live outside Google Cloud. Each needs an account and an API key, and each key goes
into Secret Manager.

| Service | What it does | Config |
|---|---|---|
| **Upstash Redis** | Short-term state, locks, caching | Host `gorgeous-lab-118268.upstash.io`, port `6379`, **TLS on** |
| **Pinecone** | Vector search — finds semantically similar memories | Index `void-ai-memories` |
| **OpenAI** | Embeddings + most LLM work | `OPENAI_BASE_URL=https://api.openai.com/v1` |
| **Anthropic** | Claude, used for some processing | — |
| **Modulate** | Speech-to-text | Model `modulate-velma-2` |

**Redis TLS matters.** Upstash requires TLS. The backend reads `REDIS_DB_SSL=true` and switches
to `SSLConnection`; without it the connection is refused. This was made env-driven in commit
`9e7db6ad96` ("Make Redis TLS env-driven") — before that it was hardcoded.

---

## Step 9 — Firebase

Firebase sits on the same GCP project and provides user authentication and push notifications.

Two Android apps are registered:

| Package | Purpose | Registered SHA-1 |
|---|---|---|
| `com.friend.ios` | Production flavor | — |
| `com.friend.ios.dev` | Dev flavor (what's on the phone) | `2DBB912D…5101` |

That SHA-1 is the fingerprint of the **debug keystore** at `~/.android/debug.keystore`. Google
sign-in checks that the app requesting login was signed with a registered certificate. Get this
wrong and you get `ApiException: 10` — see [04-android-app.md](04-android-app.md).

---

## Verifying the foundation

Run these to confirm everything exists:

```bash
P=void-ai-489016
gcloud services list --enabled --project=$P | grep -E "run|firestore|secretmanager|cloudtasks|scheduler"
gcloud firestore databases list --project=$P
gcloud artifacts repositories list --project=$P
gcloud storage buckets list --project=$P --format='value(name)'
gcloud iam service-accounts list --project=$P
gcloud secrets list --project=$P
gcloud tasks queues list --location=asia-south1 --project=$P
```

Expected: 1 database, 1 repo (`voidai`), 5 buckets, 3 service accounts (yours plus two Google
defaults), 7 secrets, 1 queue.
