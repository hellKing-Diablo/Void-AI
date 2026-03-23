# Void-AI (OMI) Codebase Context

## Project Identity
- **Product**: OMI — AI wearable ecosystem (device, mobile app, desktop app, web dashboard, plugins, MCP server)
- **Website**: omi.me | **API**: api.omi.me
- **GCP Project**: based-hardware | **Firebase Project**: void-ai-489016
- **Monorepo**: 800+ source files across 5 platforms

## Context Files (read the relevant one for your task)
| File | Read when |
|------|-----------|
| [backend.md](.claude/backend.md) | Working in `backend/` — Python, FastAPI, routers, services |
| [mobile-app.md](.claude/mobile-app.md) | Working in `app/` — Flutter, Dart, mobile UI |
| [desktop-app.md](.claude/desktop-app.md) | Working in `desktop/` — Swift, SwiftUI, Rust backend |
| [web-apps.md](.claude/web-apps.md) | Working in `web/` — Next.js, React, TypeScript |
| [data-model.md](.claude/data-model.md) | Touching Firestore, Redis, Pinecone, or data flow |
| [infra-cicd.md](.claude/infra-cicd.md) | Deployment, Helm charts, CI/CD, Codemagic |
| [firmware.md](.claude/firmware.md) | Working in `omi/` or `omiGlass/` — embedded C/C++ |
| [plugins-sdks.md](.claude/plugins-sdks.md) | Plugins, MCP server, SDKs |

## Top-Level Directory Map
```
backend/           Python FastAPI backend + microservices (pusher, diarizer, VAD, agent-proxy)
app/               Flutter mobile app (iOS + Android)
desktop/           macOS Swift app + embedded Rust backend
web/frontend/      Next.js public website (app marketplace, wrapped)
web/app/           Next.js authenticated dashboard (conversations, tasks, chat)
omi/               nRF52840 Zephyr firmware (OMI DevKit)
omiGlass/          ESP32-S3 Arduino firmware (OMI Glass)
plugins/           Plugin host (FastAPI, 100+ community plugins)
mcp/               MCP server Python package
sdks/              React Native, Expo, Swift, Python SDKs
docs/              Mintlify documentation site
scripts/           Utility scripts (pre-commit, OTA, analytics)
.github/workflows/ 24 CI/CD workflow files
```

## Cross-Cutting References
- **Coding rules, git policy, formatting**: `CLAUDE.md` (root)
- **Agent-format rules**: `AGENTS.md` (root)
- **Deploy procedures**: `docs/runbooks/deploy.md`
- **Log access**: `docs/runbooks/logging.md`
- **Desktop-specific rules**: `desktop/CLAUDE.md`
