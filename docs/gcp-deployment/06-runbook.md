# Runbook — Day-to-Day Operations

Practical reference. What to run, what to check, what to do when something breaks.

---

## Quick reference

| Thing | Value |
|---|---|
| GCP project | `void-ai-489016` (number `684741928652`) |
| Region | `asia-south1` (Mumbai) |
| Backend URL | `https://voidai-backend-684741928652.asia-south1.run.app` |
| Cloud Run service | `voidai-backend` |
| Cloud Run job | `voidai-cron` |
| Scheduler | `voidai-cron-hourly` (`0 * * * *`, UTC) |
| Service account | `voidai-runtime@void-ai-489016.iam.gserviceaccount.com` |
| Image | `asia-south1-docker.pkg.dev/void-ai-489016/voidai/backend:<git-sha>` |
| Tasks queue | `listen-finalization` |
| App package (dev) | `com.friend.ios.dev` |
| Budget alert | ₹2000/month at 50% / 90% / 100% |

### Shell setup

`~/voidai-env.sh`:
```bash
export PROJECT=void-ai-489016
export REGION=asia-south1
export IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/voidai/backend"

alias vlogs='gcloud run services logs read voidai-backend --region=asia-south1 --project=void-ai-489016 --limit=40'
alias verr='gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=voidai-backend AND severity>=ERROR" --project=void-ai-489016 --limit=20 --format="value(timestamp,textPayload)"'
```

```bash
source ~/voidai-env.sh
```

---

## Deploy a backend change

```bash
cd ~/Desktop/Void-AI

# 1. Commit first — the tag comes from the commit, not your working tree
git add -A && git commit -m "your change"

source ~/voidai-env.sh
export TAG=$(git rev-parse --short HEAD)

# 2. Build (the --build-arg is NOT optional)
sudo docker build --platform linux/amd64 \
  --build-arg PYTHON_BASE_IMAGE=python:3.11-slim \
  -f backend/Dockerfile -t "${IMAGE}:${TAG}" .

# 3. Log in to the registry (token expires hourly)
gcloud auth print-access-token | sudo docker login \
  -u oauth2accesstoken --password-stdin https://asia-south1-docker.pkg.dev

# 4. Push
sudo docker push "${IMAGE}:${TAG}"

# 5. Deploy
gcloud run deploy voidai-backend \
  --image="${IMAGE}:${TAG}" \
  --region=asia-south1 --project=void-ai-489016

# 6. ALSO update the cron job — it does not follow the service
gcloud run jobs update voidai-cron \
  --image="${IMAGE}:${TAG}" \
  --region=asia-south1 --project=void-ai-489016

# 7. Verify
curl -s https://voidai-backend-684741928652.asia-south1.run.app/v1/health
```

> **Step 6 is easy to forget and confusing when you do.** The job is pinned to a specific image
> tag. Skip it and your service runs new code while the hourly job runs old code, with no error
> anywhere.

`gcloud run deploy` on an existing service keeps all env vars, secrets, and settings — you only
need to pass the flags you're changing.

### Rollback

```bash
gcloud run deploy voidai-backend --image="${IMAGE}:<older-tag>" \
  --region=asia-south1 --project=void-ai-489016
```

No rebuild needed — the old image is still in Artifact Registry. This is why commit-hash tags
matter.

### Change an environment variable

```bash
# merge (safe)
gcloud run services update voidai-backend --region=asia-south1 --project=void-ai-489016 \
  --update-env-vars=KEY=value

# remove one
gcloud run services update voidai-backend --region=asia-south1 --project=void-ai-489016 \
  --remove-env-vars=KEY
```

⚠️ Never use `--set-env-vars` — it **replaces** the whole set and will silently delete the other
27 variables.

---

## Run the app

```bash
cd ~/Desktop/Void-AI/app
flutter run --flavor dev
```

**Never run `setup.sh`.** See [04-android-app.md](04-android-app.md).

After editing `.dev.env`:
```bash
dart run build_runner clean
dart run build_runner build --delete-conflicting-outputs
```
Both steps. A plain rebuild silently does nothing.

Build a standalone APK:
```bash
flutter build apk --flavor dev --debug
# output: build/app/outputs/flutter-apk/app-dev-debug.apk
```

Check the phone:
```bash
adb devices          # "device", not "unauthorized"
adb logcat -c && adb logcat | grep -iE "flutter|OAuth|ApiException"
```

---

## Read the logs

```bash
vlogs        # last 40 lines
verr         # errors only — start here when something is broken
```

Follow live (Ctrl-C to stop):
```bash
while true; do clear; gcloud run services logs read voidai-backend \
  --region=asia-south1 --project=void-ai-489016 --limit=30; sleep 5; done
```

Specific time window:
```bash
gcloud logging read \
  'resource.type=cloud_run_revision AND resource.labels.service_name=voidai-backend
   AND timestamp>="2026-07-28T20:00:00Z" AND timestamp<="2026-07-28T20:15:00Z"' \
  --project=void-ai-489016 --limit=300 --order=asc --format='value(timestamp,textPayload)'
```

The hourly job (**different resource type**):
```bash
gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=voidai-cron' \
  --project=void-ai-489016 --limit=30 --format='value(timestamp,textPayload)'
```

**Notes.** True streaming (`gcloud beta run services logs tail`) needs the `log-streaming`
component, which the snap build of gcloud can't install — hence the polling loop. And if the
browser console shows nothing, check which Google account your browser is signed into; gcloud
is authenticated as `vanodiyayagnik127@gmail.com`, and a mismatch makes every console URL fail.

---

## Common problems

| Symptom | Likely cause | Action |
|---|---|---|
| First request after idle takes 20–40s | Cold start, `min-instances=0` | Expected. Set `--min-instances=1` (~$15/mo) to remove |
| Docker build: `403 ... gcr.io/based-hardware-dev` | Forgot `--build-arg PYTHON_BASE_IMAGE` | Add it |
| `docker push` → `denied` / `unauthorized` | Registry token expired (1h) | Re-run `docker login` |
| Any endpoint 500s with "requires an index" | Missing Firestore composite index | The error contains the exact creation URL. Use `--async` |
| Conversations never finish | Cloud Tasks enqueue failing | `verr`, look for `actAs` or queue errors |
| Sign-in: `ApiException: 10` | Signing cert not registered in Firebase | [04-android-app.md](04-android-app.md#bug-5--signed-with-the-wrong-certificate) |
| App config change has no effect | `build_runner` cache | `build_runner clean` then rebuild |
| `Decryption failed` + `non-hexadecimal` | Data written with a different `ENCRYPTION_SECRET` | Old local data. Unrecoverable; delete the docs |
| Cron job `exit(1)`, `No module named 'utils'` | `PYTHONPATH` missing | `--update-env-vars=PYTHONPATH=/app` |
| Daily recap not generated | Local hour ≠ user's preferred hour, or no FCM token | Expected outside the window. Use the in-app test generator |

### Health checks

```bash
# service
curl -s https://voidai-backend-684741928652.asia-south1.run.app/v1/health

# indexes — everything should say READY
gcloud firestore indexes composite list --project=void-ai-489016 --format='value(state)' | sort | uniq -c

# scheduler
gcloud scheduler jobs list --location=asia-south1 --project=void-ai-489016

# what image is actually deployed
gcloud run services describe voidai-backend --region=asia-south1 --project=void-ai-489016 \
  --format='value(spec.template.spec.containers[0].image)'
```

---

## Costs

| Item | Roughly |
|---|---|
| Cloud Run service (scale-to-zero) | $5–15/mo |
| Cloud Run job (hourly, seconds each) | Free tier |
| Cloud Scheduler | Free (3 jobs/month free) |
| Firestore, Storage, Cloud Tasks | Free tier at 5 users |
| **OpenAI + Anthropic** | **Usage-based — invisible to GCP billing** |

Cloud Run's permanent free tier (resets monthly, not trial credit): 2M requests, 180,000
vCPU-seconds, 360,000 GiB-seconds.

```bash
gcloud billing budgets list --billing-account=017C68-3616AC-931D93
```

> ⚠️ **The GCP budget alert does not see OpenAI or Anthropic.** It also only *emails* — it never
> stops spending. Set hard caps in each provider's own dashboard. With no free credits on this
> account, that's the only real protection against a surprise bill.

### Per-user usage and cost data already exists

Useful for the cost-tracking tool on the roadmap — **you do not need to build the tracking, only
the export.**

`database/llm_usage.py` — schema `users/{uid}/llm_usage/{date} → {feature → {model → {input_tokens, output_tokens}}}`:

| Function | Returns |
|---|---|
| `get_usage_summary(uid, days)` | Per-user tokens by feature and model |
| `get_top_features(uid, days)` | That user's most expensive features |
| `get_global_top_features(days)` | **Across all users** — collection-group query |
| `get_total_llm_cost(uid, bucket)` | Dollar cost for a user |

`database/user_usage.py` — `users/{uid}/hourly_usage` with `transcription_seconds`,
`words_transcribed`, `insights_gained`, `memories_created`, `speech_seconds`, plus
`get_monthly_chat_usage()` which returns a `cost_usd` field.

Not covered: transcription provider costs and GCP infrastructure costs. For GCP, enable
**billing export to BigQuery** and chart in Looker Studio — no code required.

Also already wired but dormant: **LangSmith** (`utils/observability/langsmith.py`, called at
`main.py:100`). Currently `LANGSMITH_TRACING=false`. Enabling it gives per-request traces with
token counts, without adopting a new tool.

---

## What's left

### Before handing APKs to other people

1. **Generate a release keystore**, register its SHA-1 in Firebase. Do **not** restore
   `android/key.properties` — it points at a keystore whose private key is public in Omi's repo.
2. **Repoint the prod flavor.** Both `app/src/prod/google-services.json` and
   `lib/firebase_options_prod.dart` still target `based-hardware-dev`.
3. **Decide on the app identity.** It currently installs as "Omi Dev" with package
   `com.friend.ios.dev`. Changing the package means a new Firebase app registration and a new
   SHA-1 — and existing installs won't upgrade, they need a fresh install. **Do this before
   distribution, not after.**
4. **Reconsider cold starts.** 20–40s on first connection is tolerable for you and confusing for
   a tester holding a pendant. `--min-instances=1` is ~$15/mo.
5. **Set API spend caps** at OpenAI and Anthropic.

### Configuration that exists nowhere but in the live project

If you rebuilt from this repo today, these would all be missing:

- The two Firestore indexes (`messages`, `action_items`) — not in `firestore.indexes.json`
- The `iam.serviceAccountUser` binding
- The Cloud Run job, its `PYTHONPATH=/app`, and the scheduler
- `~/voidai-run-env.yaml` and `~/voidai-job-env.yaml` (untracked, on your laptop only)

### Also worth revisiting

- `ENVIRONMENT=development` and `OMI_ENV_STAGE=dev` are set on the production backend
- Image is ~3 GB; shrinking it would cut cold-start time
- Two March test conversations are permanently undecryptable and generate error noise on every
  conversation list request — safe to delete
