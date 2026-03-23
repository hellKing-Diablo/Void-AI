# Backend Architecture

## Services (5 deployable units)

### 1. Main API — `backend/main.py`
- FastAPI app, 37+ routers
- Deploy: Cloud Run (dev auto, prod manual) + Modal
- Auth: Firebase ID token via `utils/other/endpoints.py` → `get_current_user()`
- Middleware: TimeoutMiddleware (per-method HTTP timeouts from `utils/other/timeout.py`)

### 2. Pusher — `backend/pusher/main.py`
- Receives binary audio via WebSocket from Main API
- Runs Deepgram STT (cloud), speaker diarization
- Env: `HOSTED_PUSHER_API_URL`

### 3. Diarizer — `backend/diarizer/main.py`
- GPU service: pyannote speaker embeddings
- Endpoints: `/v1/diarization`, `/v2/embedding`
- Env: `HOSTED_SPEAKER_EMBEDDING_API_URL`

### 4. VAD — `backend/modal/main.py`
- GPU service: voice activity detection + speaker identification
- Endpoints: `/v1/vad`, `/v1/speaker-identification`
- Env: `HOSTED_VAD_API_URL`, `HOSTED_SPEECH_PROFILE_API_URL`

### 5. Agent Proxy — `backend/agent-proxy/main.py`
- GKE deployment, WebSocket proxy to per-user Agent VMs
- Flow: validate Firebase token → Firestore `users/{uid}.agentVm` → `ws://<vm-ip>:8080/ws`
- Handles encryption (AES-GCM) for enhanced data protection users
- Prepends last 10 chat messages from Firestore as context

## Module Hierarchy (imports flow upward, never downward)
```
database/   → Firestore client, Redis, Pinecone, cache, pubsub
models/     → Pydantic data models
utils/      → Business logic (imports database/)
routers/    → API endpoints (imports utils/, database/)
main.py     → App assembly (imports routers/)
```

## Router Inventory (`backend/routers/`)

**Core Audio & Conversation:**
- `transcribe.py` — WebSocket `/v4/listen`: live audio transcription pipeline (125 KB, most critical file)
- `conversations.py` — CRUD, post-processing, search, bulk ops
- `speech_profile.py` — Speaker voice enrollment `/v3/speech-profile`
- `pusher.py` — Pusher service router

**Chat & AI:**
- `chat.py` — `/v2/messages`: multi-app chat, streaming, file attachments
- `knowledge_graph.py` — Entity/relationship extraction CRUD
- `goals.py` — Goal tracking extraction
- `action_items.py` — Task extraction & management
- `trends.py` — Behavioral trends/insights

**Apps & Plugins:**
- `apps.py` — App store CRUD (76 KB)
- `plugins.py` — Legacy plugin endpoints
- `developer.py` — Dev API key management, sandbox
- `mcp.py` / `mcp_sse.py` — MCP protocol endpoints
- `agent_tools.py` — Tools exposed to agent VMs

**Auth & Users:**
- `auth.py` — Firebase + OAuth (Google, Apple)
- `oauth.py` — OAuth provider for third-party apps
- `custom_auth.py` — Custom auth logic
- `users.py` — User profile, preferences, people management

**Integrations:**
- `integrations.py` — OAuth integration state (Gmail, Calendar, etc.)
- `integration.py` — Generic integration endpoint
- `task_integrations.py` — Sync with Todoist, Asana, ClickUp, Google Tasks
- `phone_calls.py` — Twilio phone call handling
- `calendar_meetings.py` — Calendar context linking

**Infrastructure:**
- `payment.py` — Stripe subscription/billing
- `notifications.py` — FCM push notifications
- `firmware.py` — Device firmware updates
- `sync.py` — Device data sync
- `metrics.py` — Prometheus metrics
- `other.py` — Health checks

**Content:**
- `memories.py` — Long-term memory CRUD
- `folders.py` — Conversation organization
- `announcements.py` — Feature releases
- `wrapped.py` — Year-in-review stats
- `imports.py` — External data imports (Limitless)

## Key Utils Subsystems

### STT Pipeline (`utils/stt/`)
- `streaming.py` (27 KB) — Real-time STT (Deepgram, Soniox, Speechmatics)
- `vad_gate.py` (30 KB) — Voice activity detection gating (cost optimization)
- `pre_recorded.py` — Batch STT for uploaded audio
- `speaker_embedding.py` — Speaker diarization embeddings
- `speech_profile.py` — Voice profile generation

### LLM (`utils/llm/`)
- `chat.py` (57 KB) — Chat LLM calls, multi-app streaming, tool use
- `persona.py` — Persona-based chat system
- `goals.py` — Goal extraction from conversations
- `knowledge_graph.py` — KG extraction from memories
- `usage_tracker.py` — LLM token usage tracking
- `langsmith_prompts.py` — LangSmith prompt management

### Conversation Processing (`utils/conversations/`)
- `process_conversation.py` (39 KB) — **Critical**: post-processing pipeline (title, summary, action items, memories, KG, integrations)
- `conversation_processing.py` (47 KB) — Additional processing logic
- `merge_conversations.py` — Merge partial conversations
- `search.py` — Conversation search

### Retrieval / RAG (`utils/retrieval/`)
- `rag.py` — Basic RAG (Pinecone semantic search)
- `agentic.py` (705 lines) — Multi-turn tool use with safeguards
- `graph.py` (732 lines) — Knowledge graph structured retrieval
- `safety.py` — Hallucination detection, scope validation
- `tools/` — 16 integrated tools: calendar, Gmail, memories, tasks, health, screen activity, Perplexity, etc.

### Other Key Utils
- `app_integrations.py` (22 KB) — Plugin/app webhook dispatch
- `mcp_client.py` (26 KB) — MCP protocol client
- `encryption.py` — AES-GCM field-level encryption
- `log_sanitizer.py` — PII/sensitive data redaction
- `prompts.py` (29 KB) — LLM system prompts
- `speaker_identification.py` (17 KB) — Speaker ID from audio
- `notifications.py` (20 KB) — Notification dispatch
- `subscription.py` (12 KB) — Credit-based usage limits
- `other/storage.py` (42 KB) — GCS bucket operations

## Database Layer (`backend/database/`)
- `_client.py` — Firestore + Redis client singletons
- `redis_db.py` (903 KB) — Redis caching layer (massive)
- `vector_db.py` — Pinecone client, embedding upsert/query
- `conversations.py` (42 KB) — Conversation CRUD with encryption
- `memories.py` — Memory storage with encryption
- `users.py` (32 KB) — User profiles, subscriptions, speech profiles
- `chat.py` — Chat message storage
- `apps.py` — App store data
- `cache.py` / `cache_manager.py` — In-memory cache + Redis invalidation
- `redis_pubsub.py` — Real-time cache invalidation
- 15+ more collection modules (action_items, goals, folders, notifications, knowledge_graph, etc.)

## Audio Pipeline (Critical Path)
```
1. Device → WebSocket → routers/transcribe.py (decode Opus/LC3/AAC)
2. transcribe.py → utils/pusher.py WebSocket → Pusher service
3. Pusher → Deepgram streaming STT → transcript segments
4. Pusher → Diarizer → speaker embeddings
5. transcribe.py receives segments, runs VAD gating
6. Speaker assignment (utils/speaker_identification.py)
7. On conversation end → utils/conversations/process_conversation.py
8. LLM extracts: title, summary, action items, memories, KG, categories
9. Results → Firestore + Pinecone vectors + Redis cache
10. Plugins notified via webhook → Push notifications sent
```

## Testing
- `backend/tests/unit/` — ~55 unit tests (pytest)
- `backend/tests/integration/` — Live service integration tests
- `backend/tests/eval/` — LLM output evaluation tests
- `backend/test.sh` — Test runner (sets ENCRYPTION_SECRET)
- `backend/test-preflight.sh` — Environment verification
