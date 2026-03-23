# Infrastructure & CI/CD

## GCP Project: based-hardware

## Compute Topology
| Platform | Services |
|----------|----------|
| **Cloud Run** | Main backend, Rust desktop backend, web frontend, web app, plugins |
| **GKE** | Agent proxy, pusher, diarizer (GPU), VAD (GPU), deepgram self-hosted (GPU) |
| **Modal** | Backend (serverless), notifications job (cron), speech profile generation |
| **Codemagic** | Mobile app builds (iOS/Android), desktop macOS builds |

## Helm Charts (`backend/charts/`)
```
backend-listen/          Main API service
pusher/                  Audio pusher service
diarizer/                GPU speaker diarization
vad/                     GPU VAD + speaker ID
deepgram-self-hosted/    Self-hosted Deepgram STT (nova-2/, nova-3/)
agent-proxy/             WebSocket proxy to agent VMs
backend-secrets/         Shared secret management
monitoring/              Prometheus, Loki, Grafana, Alloy, Stackdriver exporter
```

## GitHub Actions Workflows (`.github/workflows/`)

### Backend
```
gcp_backend.yml                         Manual prod deploy
gcp_backend_auto_dev.yml                Auto dev deploy on main push (backend/**)
gcp_backend_listen_helm.yml             Helm deploy for backend-listen
gcp_backend_pusher.yml                  Pusher deploy
gcp_backend_pusher_auto_deploy.yml      Auto pusher deploy on main push
gcp_backend_agent_proxy.yml             Agent proxy deploy
gcp_backend_agent_proxy_auto_deploy.yml Auto agent proxy deploy on main push
gcp_diarizer.yml                        Diarizer GPU deploy
gcp_notifications_job.yml               Notifications cron job deploy
gcp_models.yml                          ML model deploy
```

### Frontend / Apps
```
gcp_frontend.yml       Web frontend deploy (web/frontend/**)
gcp_app.yml            Web app deploy
gcp_apps_js.yml        JS-based apps deploy (web/app/**)
gcp_personas.yml       Personas service deploy (web/personas/**)
gcp_plugins.yml        Plugins service deploy (plugins/**)
```

### Desktop
```
desktop_auto_release.yml            Auto version bump + tag on main push (desktop/**)
desktop_backend_auto_dev.yml        Auto Rust backend dev deploy
```

### Docs / Quality
```
deploy_docs.yml                     Mintlify docs deploy (docs/**)
sync-docs.yml                       Docs sync
lint.yml                            Linting
main.yml                            Main CI (tests)
pr-declined-comment.yml             PR automation
entellegence_issues.yml             Issue triage
entelligence-pr-reviewer.yml        PR review
```

## Codemagic (`codemagic.yaml`)
```
ios-internal-auto       iOS TestFlight build on main push (app/**)
android-internal-auto   Android build on main push (app/**)
omi-desktop-swift-release  macOS build on v*-macos tag
                          (universal binary, signed, notarized, DMG + Sparkle ZIP, GitHub release)
```
**Build number rule**: `app/pubspec.yaml` version+N must bump for new TestFlight upload.

## Deployment Rules
- **Dev**: Auto-deploys on push to `main` with matching directory changes
- **Prod**: Manual trigger only (`gh workflow run gcp_backend.yml -f environment=prod -f branch=main`)
- **Desktop**: Auto-increments version, tags `v*-macos`, Codemagic handles rest
- Full runbook: `docs/runbooks/deploy.md`

## Key Environment Variables (across services)
```
# GCP/Firebase
GOOGLE_APPLICATION_CREDENTIALS, SERVICE_ACCOUNT_JSON

# Database
REDIS_DB_HOST, REDIS_DB_PORT, REDIS_DB_PASSWORD
PINECONE_API_KEY, PINECONE_INDEX_NAME

# AI Services
OPENAI_API_KEY, DEEPGRAM_API_KEY, SONIOX_API_KEY
LANGSMITH_API_KEY, LANGSMITH_PROJECT

# Service URLs
HOSTED_PUSHER_API_URL, HOSTED_SPEAKER_EMBEDDING_API_URL
HOSTED_VAD_API_URL, HOSTED_SPEECH_PROFILE_API_URL
DEEPGRAM_SELF_HOSTED_URL, DEEPGRAM_SELF_HOSTED_ENABLED

# Security
ENCRYPTION_SECRET (>= 32 bytes)
FIREBASE_API_KEY, FIREBASE_AUTH_DOMAIN, FIREBASE_PROJECT_ID

# Payments
STRIPE_API_KEY, STRIPE_WEBHOOK_SECRET

# Integrations
GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
APPLE_CLIENT_ID, APPLE_TEAM_ID, APPLE_KEY_ID, APPLE_PRIVATE_KEY
TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
HUME_API_KEY, PERPLEXITY_API_KEY
```
