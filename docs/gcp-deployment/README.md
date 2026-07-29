# VoidAI — Cloud Deployment

**What this folder is:** the complete record of how VoidAI's backend was put on Google Cloud
and how the Android app was connected to it. Written so that a year from now, you — or an AI
assistant reading this — can pick up the full context without re-deriving anything.

**Status as of 29 July 2026:** the backend is live and the app works end to end on a real phone.

---

## Start here

If you read only one file, read this one. It tells the whole story in plain language.
The numbered files go deep on each phase — every command, every error, why we made each
choice. Use them when you need detail, not to get oriented.

| File | What's in it |
|---|---|
| **README.md** (this file) | The whole story, start to finish, in plain language |
| [01-foundation.md](01-foundation.md) | The Google Cloud account setup — project, database, storage, secrets, permissions |
| [02-docker-image.md](02-docker-image.md) | Packaging the backend into a shippable image, and the problems that caused |
| [03-cloud-run-deploy.md](03-cloud-run-deploy.md) | Putting that image on the internet as a running server |
| [04-android-app.md](04-android-app.md) | Getting the phone app to talk to *your* backend instead of Omi's |
| [05-post-deploy-fixes.md](05-post-deploy-fixes.md) | Everything that broke after launch, and how each was diagnosed |
| [06-runbook.md](06-runbook.md) | Day-to-day operations: redeploy, read logs, fix common problems |
| [07-omi-differences.md](07-omi-differences.md) | Every place VoidAI differs from upstream Omi, and why |

---

## What VoidAI is

An AI voice pendant. A small hardware device records what you say, streams the audio to a
server, the server turns it into text, and then uses AI to write summaries, extract to-do
items, and answer questions about your own conversations.

It's a fork of [Omi](https://github.com/BasedHardware/omi), an open-source project (MIT
licensed, so forking is allowed and encouraged). VoidAI targets India — Gujarati, Hindi and
English, including sentences that mix them.

Three pieces have to work together:

```
   [ Pendant ]  ──audio──>  [ Backend on Google Cloud ]  <──>  [ Android app ]
                                        │
                                        ├── Firestore   (the database)
                                        ├── Redis       (short-term memory / locks)
                                        ├── Pinecone    (semantic search)
                                        └── OpenAI, Anthropic, Modulate (the AI)
```

The goal for this stage was modest and specific: **get the backend running 24/7 on Google
Cloud so 5 people can use it privately.** Not scale, not polish — just real, always-on,
reachable from a phone.

---

## The story, in five phases

### Phase 1 — Building the foundation

Before any code can run in the cloud, the cloud needs somewhere to put it. This phase created
the account-level things: a Google Cloud project, a database, five storage buckets, a place to
store our packaged code, a locked box for API keys, and a robot identity for the server to act
as.

One decision shaped everything else: **the region is `asia-south1` (Mumbai)**. Firestore was
already created there, and a Firestore database's location can never be changed. So every other
piece had to follow it, or we'd be paying for traffic to cross the country.

→ [01-foundation.md](01-foundation.md)

### Phase 2 — Packaging the backend

Code on your laptop won't run in the cloud as-is. It needs to be packaged into a **container
image** — a sealed box containing the code, the Python version, and every library, so it runs
identically anywhere.

This is where things first went wrong. The Dockerfile we inherited from Omi pointed at a
*private* base image that only Omi's team can download. Every build failed until we understood
that. Then the image came out at 3 GB instead of the 865 MB we'd seen before, which sent us
investigating where the weight was.

→ [02-docker-image.md](02-docker-image.md)

### Phase 3 — Putting it on the internet

We deployed the image to **Cloud Run**, Google's service for running containers without
managing servers. It handles HTTPS, scaling, and restarts on its own.

The interesting decision here was what *not* to deploy. Omi's production runs about seven
services across two platforms, including Kubernetes. We deployed **one**. The piece we
skipped — a service called "pusher" — turned out to be replaceable by Google Cloud Tasks for
our purposes, which saved us from running Kubernetes for five users.

→ [03-cloud-run-deploy.md](03-cloud-run-deploy.md)

### Phase 4 — Connecting the app

The Flutter app had to be pointed at *our* backend and *our* Firebase project instead of Omi's.

This was the most frustrating phase, and almost all of it traced to one cause: a setup script
in the repo (`setup.sh`) that silently overwrites your configuration with Omi's. It repointed
the app at Omi's servers, replaced the Firebase config, and installed a signing key whose
private half is public in their repository. Each of those produced a different confusing error
on a different day.

→ [04-android-app.md](04-android-app.md)

### Phase 5 — Fixing what only showed up in production

Once real data started flowing, four things broke that could never have been caught locally:

- Conversations recorded but never summarized — a missing cloud permission
- Chat completely dead — a missing database index
- To-do items extracted but never appearing on the tasks page — a *second* missing index
- Daily recaps never generated — the hourly job that produces them was never deployed

Each one was found by reading server logs, tracing to the exact line of code, and fixing the
cause rather than the symptom.

→ [05-post-deploy-fixes.md](05-post-deploy-fixes.md)

---

## What works today

Verified by actually using it on a Samsung phone, not by assuming:

- ✅ Google sign-in
- ✅ Live transcription streaming to the phone as you speak
- ✅ Conversations auto-finalize and get AI summaries and titles
- ✅ Chat — asking questions about your own conversations
- ✅ Action items extracted and shown on the tasks page — **re-verified 29 July on a freshly
  recorded conversation**, after the composite index landed
- ✅ Everything encrypted at rest, keys stored in Secret Manager
- ⚠️ Daily recaps — **still unverified as of 29 July.** Not because they fail: the hourly job
  crashed with `ModuleNotFoundError: No module named 'utils'` until 21:28 UTC on 28 July, so the
  17:00 UTC tick that fires local hour 22 for `Asia/Kolkata` had never once run. The job now
  exits 0 every hour. Force one to test: **Settings → Daily Summary → ⋮ menu, top-right →
  "Generate Summary"** — it is in the app-bar overflow menu, not on the page body.

## What it costs

| Item | Roughly |
|---|---|
| Cloud Run (scale-to-zero) | $5–15/month |
| Firestore, Storage, Cloud Tasks, Scheduler | Free tier covers 5 users comfortably |
| OpenAI + Anthropic | Depends entirely on usage — **not covered by any GCP alert** |
| Upstash Redis, Pinecone | Free tier |

A budget alert is set at **₹2000/month** with warnings at 50%, 90% and 100%. Two things to
understand about it: it only *emails* you, it does not stop spending — and it only sees Google
Cloud. Your OpenAI and Anthropic bills are invisible to it and need their own caps set in their
own dashboards.

There are **no free trial credits** on this account. The trial expired 7 July 2026. Charges go
to a real card.

---

## Where we stopped

The deployment goal is met. What remains is written up in full at the end of
[06-runbook.md](06-runbook.md), but in short:

1. **The app is still a developer build.** It identifies as "Omi Dev", is signed with a personal
   debug key, and the production flavor still points at Omi's Firebase project. Before handing
   APKs to other people, that needs a real release key and a real production identity.
2. **App bugs and rebranding** — known, being tracked separately.
3. **Per-user cost tracking** — the backend already records token usage and cost per user per
   day (see [06-runbook.md](06-runbook.md)); what's missing is an export and charts, not the
   tracking itself.
4. **Repo cleanup** — several branches carry ad-hoc changes that need sorting.

---

## Two things worth knowing before you touch anything

**Never run `app/setup.sh` again.** It overwrites your app configuration with Omi's — the API
URL, the Firebase project, and the signing key. It caused four separate bugs across two days.
Full detail in [04-android-app.md](04-android-app.md).

**Config files are not the same as running config.** Editing `.dev.env` changes nothing in the
app until you re-run the code generator, and editing it a second time may still change nothing
because the generator caches. This cost hours. See [04-android-app.md](04-android-app.md#the-generated-env-trap).
