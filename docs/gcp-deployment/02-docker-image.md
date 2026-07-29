# Phase 2 — Packaging the Backend as a Container Image

## What this phase is

> **What a container image is.** Your backend needs Python 3.11, about 260 libraries, some
> system packages like `ffmpeg`, and a specific audio codec. Getting all of that onto a cloud
> server by hand would be fragile and unrepeatable. Instead you build an **image**: a sealed,
> layered snapshot containing the operating system files, the Python runtime, every library, and
> your code. Cloud Run downloads that image and runs it. Because the image is identical every
> time, "works on my machine" stops being a category of problem.
>
> **Image vs container:** the image is the recipe on disk; a container is one running instance
> of it. You build an image once and run many containers from it.

---

## The build command

```bash
source ~/voidai-env.sh                      # sets PROJECT, REGION, IMAGE
export TAG=$(git rev-parse --short HEAD)    # e.g. 9e7db6ad96

sudo docker build --platform linux/amd64 \
  --build-arg PYTHON_BASE_IMAGE=python:3.11-slim \
  -f backend/Dockerfile \
  -t "${IMAGE}:${TAG}" \
  .
```

Where `~/voidai-env.sh` contains:

```bash
export PROJECT=void-ai-489016
export REGION=asia-south1
export IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/voidai/backend"
```

### Every part of that command, explained

| Part | Why |
|---|---|
| `--platform linux/amd64` | Cloud Run runs on x86-64. Building on a different architecture produces an image that won't start, with an unhelpful error. Harmless to specify even on an x86 laptop — it makes intent explicit. |
| `--build-arg PYTHON_BASE_IMAGE=...` | Overrides the private base image the Dockerfile defaults to. **Without this the build fails.** See below. |
| `-f backend/Dockerfile` | The Dockerfile lives in `backend/`, but… |
| `.` (the trailing dot) | …the **build context** is the repo *root*, not `backend/`. This matters — see below. |
| `-t "${IMAGE}:${TAG}"` | Names the image and tags it with the git commit. |

### Why the trailing dot must be `.` and not `backend/`

The build context is the set of files Docker is allowed to copy from. The Dockerfile contains:

```dockerfile
COPY backend/ .
COPY .github/scripts/desktop_qualification_e... 
```

It copies from `backend/` **and** from `.github/`. Both paths are written relative to the repo
root. If you set the context to `backend/`, the `.github/` copies fail and the build dies. The
`-f` flag says *where the Dockerfile is*; the final argument says *what it can see*. They're
independent.

---

## Problem 1 — The private base image

This is the first thing that will happen to anyone rebuilding this project.

```
=> ERROR [internal] load metadata for gcr.io/based-hardware-dev/python:3.11-slim-forky
------
Dockerfile:4
   4 | >>> FROM ${PYTHON_BASE_IMAGE} AS builder
------
ERROR: failed to solve: failed to fetch anonymous token:
unexpected status from GET request to https://gcr.io/v2/token?...: 403 Forbidden
```

### The cause

`backend/Dockerfile` line 1:

```dockerfile
ARG PYTHON_BASE_IMAGE=gcr.io/based-hardware-dev/python:3.11-slim-forky
```

`gcr.io/based-hardware-dev/` is **Omi's own private container registry**. They pre-build a
hardened Python base image and every internal build pulls from it. You are not a member of that
project, so the pull is refused. `403 Forbidden` on an "anonymous token" request means exactly
that — you tried to fetch anonymously and there is nothing public there.

This is not a bug in the fork. It's an artifact of forking a codebase whose build assumes
company infrastructure.

### What we tried first (and why it failed)

The initial idea was to mirror Omi's base image into our own registry:

```bash
BASE=asia-south1-docker.pkg.dev/void-ai-489016/voidai/python:3.11-slim-forky
sudo docker tag gcr.io/based-hardware-dev/python:3.11-slim-forky $BASE
sudo docker push $BASE
```

This can't work, and understanding why is useful: `docker tag` only renames an image **you
already have locally**. We'd never successfully pulled the original — that was the whole
problem — so there was nothing to tag. Checking confirmed it:

```bash
sudo docker images --format '{{.Repository}}:{{.Tag}}' | grep -i based-hardware || echo "NOT FOUND"
# NOT FOUND
```

Mirroring is a valid strategy *when you have access to the source image*. We didn't.

### The fix

Point the build at the public upstream Python image instead:

```bash
--build-arg PYTHON_BASE_IMAGE=python:3.11-slim
```

`python:3.11-slim` is the official Docker Hub image the `-forky` variant was itself derived
from. Omi's version adds their own hardening; we lose that and gain a build that actually runs.

**Remember this flag.** It is not optional, and the Dockerfile default will silently send you
back to the 403 every time you forget.

---

## Problem 2 — The image tripled in size

An earlier build had produced **865 MB**. The new one came out at **3063 MB**. That's a big
enough jump to be worth understanding rather than shrugging at, because image size directly
affects cold-start time on Cloud Run — the container has to be downloaded before it can serve
its first request.

### How to investigate image size

```bash
sudo docker history $IMAGE:$TAG --human --format '{{.Size}}\t{{.CreatedBy}}' | head -15
```

Output:

```
0B      CMD ["uvicorn" "main:app" "--host" "0.0.0.0"…
0B      EXPOSE [8080/tcp]
135MB   COPY backend/ .
20.5kB  COPY .github/scripts/desktop_qualification_e…
2GB     COPY /opt/venv /opt/venv          ← the Python virtualenv
12.9MB  RUN ldconfig && pip install -…
156kB   COPY /tmp/wheels /tmp/wheels
483kB   COPY /opt/liblc3/ /usr/local/lib/
0B      ENV LD_PRELOAD=libjemalloc.so.2
625MB   RUN apt-get update && apt-get -y …  ← system packages
0B      ENV LD_LIBRARY_PATH=/usr/local/lib:
8.19kB  WORKDIR /app
```

> **How to read this.** A Docker image is a stack of read-only **layers**, one per instruction in
> the Dockerfile. `docker history` lists them with sizes. The two fat layers are almost always
> the same two: installed system packages (`apt-get`) and installed Python packages.

### What it means

- **2 GB — `/opt/venv`**: the Python virtual environment with ~260 packages. The heavy ones are
  ML/audio libraries: torch-adjacent packages, numpy/scipy, the LangChain stack, Pinecone and
  OpenAI clients.
- **625 MB — apt layer**: `ffmpeg` and friends. `ffmpeg` alone pulls in a large codec tree.
- **135 MB — the app code** itself.

The difference from the 865 MB build comes from the base image and dependency resolution path
differing between the two attempts, not from anything in your code. **3 GB is large but not
broken.** With `--startup-cpu-boost` enabled (which it is), cold starts land in the 20–40s range
— acceptable for a 5-user pilot, worth revisiting before wider release.

If you want to shrink it later, the levers in order of payoff are: drop unused ML dependencies,
switch to a slimmer ffmpeg build, and use multi-stage copying to leave build tools behind.

---

## Tags, commits, and why they're linked

```bash
export TAG=$(git rev-parse --short HEAD)   # 9e7db6ad96
```

> **What a tag is.** A label on an image, the part after the colon:
> `…/voidai/backend:9e7db6ad96`. Tags are how you refer to a specific build.

**Why tag with the git commit hash rather than `latest`:**

- `latest` is a lie waiting to happen. Two people build `latest` from different code and the
  registry now serves whichever was pushed last. You can never tell what's actually deployed.
- With a commit tag, `gcloud run services describe` tells you the image tag, and
  `git show 9e7db6ad96` tells you the exact source. The deployment becomes traceable.
- Rollback is `gcloud run deploy --image=…:<older-tag>`. No rebuild, no guessing.

**The catch:** the tag reflects your last *commit*, not your working directory. If you have
uncommitted changes, `git rev-parse HEAD` gives you the previous commit's hash and you'll build
an image labelled with code it doesn't contain. **Commit before you build.**

---

## Registry authentication

```bash
gcloud auth print-access-token | sudo docker login \
  -u oauth2accesstoken --password-stdin https://asia-south1-docker.pkg.dev
```

> **Why you have to do this again every time.** `gcloud auth print-access-token` produces a
> short-lived OAuth token — about one hour. Docker stores it and keeps using it until it
> expires, at which point pushes start failing with `denied` or `unauthorized`. There's nothing
> wrong; the token simply aged out. Re-run the login.
>
> `--password-stdin` pipes the token in rather than putting it on the command line, which keeps
> it out of your shell history.

**Why `sudo`:** on this machine the Docker daemon requires root. That means `sudo docker` uses
*root's* credential store, not yours — so the `docker login` must also be run with `sudo`, or
the push will use an empty credential set. (You can remove the need for `sudo` entirely by
adding yourself to the `docker` group.)

---

## Verify before you push

Three checks were run against the built image before it went anywhere near the cloud. Each one
catches a class of mistake that's expensive to find later.

### Check 1 — no secrets baked into the image

```bash
sudo docker run --rm $IMAGE:$TAG ls /app/.env /app/google-credentials.json
```

**You want this to fail** with "No such file or directory". If those files are present, your API
keys are inside the image — and anyone who can pull the image has them. `.dockerignore` is what
keeps them out.

### Check 2 — Redis TLS actually switches

```bash
sudo docker run --rm -e REDIS_DB_HOST=dummy -e REDIS_DB_SSL=true $IMAGE:$TAG \
  python -c "from database.redis_db import r; print(r.connection_pool.connection_class.__name__)"
# expect: SSLConnection

sudo docker run --rm -e REDIS_DB_HOST=dummy $IMAGE:$TAG \
  python -c "from database.redis_db import r; print(r.connection_pool.connection_class.__name__)"
# expect: Connection
```

Upstash requires TLS. This proves the env var genuinely changes behaviour rather than being
read and ignored.

### Check 3 — it boots and answers

```bash
sudo docker run --rm -d --name voidai-verify -p 8080:8080 \
  -v $(pwd)/backend/.env:/app/.env:ro \
  -v $(pwd)/backend/google-credentials.json:/app/google-credentials.json:ro \
  $IMAGE:$TAG
sleep 20
curl -s localhost:8080/v1/health; echo
sudo docker logs voidai-verify 2>&1 | head -40
sudo docker rm -f voidai-verify
```

Expect `{"status":"ok"}`. Note the secrets are **mounted at runtime** (`-v`), not built in — the
same separation Cloud Run uses with Secret Manager.

---

## Push

```bash
sudo docker push $IMAGE:$TAG
```

Confirm it arrived:

```bash
gcloud artifacts docker images list \
  asia-south1-docker.pkg.dev/void-ai-489016/voidai \
  --include-tags --project=void-ai-489016
```

### Deleting a bad image

```bash
gcloud artifacts docker images delete \
  asia-south1-docker.pkg.dev/void-ai-489016/voidai/backend:<tag> \
  --delete-tags --quiet
```

`--delete-tags` is required when the image has tags pointing at it; without it the delete is
refused. Safe to do for any image not currently deployed — storage is cheap, but stale images
are confusing.

---

## Current state

| | |
|---|---|
| Deployed image | `asia-south1-docker.pkg.dev/void-ai-489016/voidai/backend:9e7db6ad96` |
| Pushed | 2026-07-28 21:30 UTC |
| Size | ~3 GB |
| Base | `python:3.11-slim` (public), overriding the private default |
