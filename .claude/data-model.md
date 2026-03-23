# Data Model & Storage

## Firestore (GCP project: based-hardware)
Client singleton: `backend/database/_client.py` → `db = firestore.Client()`

### Collections
```
users/{uid}/
  ├── conversations/            Audio conversation records
  ├── memories/                 Extracted memories
  ├── action_items/             Tasks / action items
  ├── chat_messages/            AI chat history
  ├── processing_conversations/ In-progress conversations
  ├── speech_samples/           Voice profile embeddings
  ├── daily_summaries/          Daily activity summaries
  ├── calendar_meetings/        Calendar sync data
  ├── goals/                    Goal tracking
  ├── folders/                  Organization folders
  ├── trends/                   Behavioral trends
  ├── knowledge_graph/          KG nodes/edges
  ├── people/                   Known people (speakers)
  ├── fcm_tokens/               Push tokens (ios_, android_, macos_ prefixed)
  ├── llm_usage/                LLM API usage tracking
  └── (user profile fields):    agentVm, subscription, data_protection_level,
                                 preferences, persona, onboarding_state, etc.

plugins/                        App/plugin definitions
public/                         Public app data (cached aggressively)
```

### Key Document Fields

**Conversation**: `id`, `source` (omi|desktop|phone|web|sdcard|frame|bee|etc.), `status`, `structured` (title, overview, action_items, category), `transcript_segments[]`, `photos[]`, `started_at`, `finished_at`, `audio_file`, `geolocation`, `language`, `data_protection_level`

**Memory**: `id`, `content` (text), `category`, `created_at`, `conversation_id`

**ActionItem**: `id`, `description`, `completed`, `due_date`, `source_conversation_id`, `priority`

**Message**: `id`, `text`, `type` (human|ai), `sender`, `created_at`, `plugin_id`

### Encryption
- **Method**: AES-GCM field-level encryption (`utils/encryption.py`)
- **Key derivation**: `ENCRYPTION_SECRET` + uid → per-user key
- **User field**: `data_protection_level` — `"enhanced"` (encrypted) or `"standard"`
- **Encrypted fields**: transcript_segments, structured data, memory content
- **Helpers**: `prepare_for_write()`, `prepare_for_read()` in `database/helpers.py`

---

## Redis
Client singleton: `backend/database/redis_db.py` → `r = redis.Redis(...)`
Connection: Upstash Redis (TCP + SSL)

### Key Patterns & TTLs
```
cache:{base64_path}                      Generic cache (5-15 min)
apps:{app_id}                            App metadata (10 min)
users:{uid}:in_progress_memory_id        Current conversation (5 min)
users:{uid}:name                         Cached user name (7 days)
users:{uid}:facts                        Memory cache (1 hour)
users:{uid}:enabled_plugins              Enabled apps (set)
users:{uid}:geolocation                  User location (30 min)
users:{uid}:listen_rate_limit            Rate limiting (7 sec)
users:{uid}:paid_apps:{app_id}           Subscription status
users:{uid}:daily_noti_count:{date}      Daily notification count
users:{uid}:speech_profile_duration      Profile length cache
users:{uid}:persona_updated              Persona update rate limit (daily)
username:{username}:uid                  Username→UID mapping
public-memories                          Set of public conversation IDs
conversation:{conv_id}:meeting_id        Calendar meeting linking (24 hrs)
mcp_api_key:{hashed}                     MCP API key cache (1 hour)
dev_api_key:{hashed}                     Dev API key cache (1 hour)
auth_session:{session_id}                Auth session state (10 min)
auth_code:{code}                         OAuth auth codes (5 min)
task_share:{token}                       Shared task tokens (30 days)
```

### Pub/Sub
- `database/redis_pubsub.py` — Real-time cache invalidation
- `database/cache.py` → `InMemoryCacheManager` — Local cache synced via pub/sub

---

## Pinecone (Vector DB)
Client: `backend/database/vector_db.py` → `pc = Pinecone(...); index = pc.Index(...)`
- **Namespace**: `"ns1"`
- **Vectors**: Conversation/memory embeddings for RAG
- **Metadata**: uid, memory_id, created_at
- **Used by**: `utils/retrieval/rag.py` for semantic search

---

## GCS Buckets
```
BUCKET_SPEECH_PROFILES    User voice profiles
BUCKET_BACKUPS            User data backups
BUCKET_PLUGINS_LOGOS      App marketplace logos
```
Client: `utils/other/storage.py` (42 KB) — upload, download, signed URLs

---

## End-to-End Data Flow
```
 1. Audio captured (device BLE / desktop mic / phone call / web)
 2. Streamed via WebSocket to backend/routers/transcribe.py
 3. Decoded (Opus/LC3/AAC) → forwarded to Pusher service
 4. Pusher → Deepgram STT → transcript segments returned
 5. Segments speaker-assigned via diarizer embeddings
 6. VAD gating filters silence → saves STT cost
 7. Conversation finalized → process_conversation.py
 8. LLM extracts: title, summary, action items, memories, KG, categories
 9. Stored: Firestore (conversations, memories, action_items)
           + Pinecone (embeddings for RAG)
           + Redis (cache invalidation)
10. Plugins notified via webhook (utils/app_integrations.py)
    → Push notifications sent to user devices
```
