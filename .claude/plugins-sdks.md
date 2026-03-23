# Plugins, MCP Server & SDKs

## Plugin Host (`plugins/`)
- **Framework**: FastAPI (`plugins/main.py`)
- **Deploy**: Cloud Run / Modal via `gcp_plugins.yml`
- **Registry**: `community-plugins.json` (118 KB, 100+ plugins)
- **Stats**: `community-plugin-stats.json`

### Plugin Types
- `conversation_created` — Triggered after conversation processing
- `realtime` — Triggered during live transcription (deprecated)
- `mentor` — Proactive notification plugins
- `subscription` — Subscription-gated plugins

### Plugin Dispatch Flow
```
Conversation processed → backend/utils/app_integrations.py
  → trigger_external_integrations()
  → For each enabled app: POST webhook with conversation data
```

### Plugin Categories (`plugins/`)
```
basic/              Simple webhook plugins
advanced/           Complex multi-step plugins (Breadboard Ecosystem)
oauth/              OAuth-authenticated plugins
apps-js/            JavaScript-based apps
notifications/      Notification-triggered (hey_omi, mentor)
chatgpt/            ChatGPT integration
composio/           Composio integration
hume-ai/            Hume AI emotion analysis
import/             Data import plugins
instructions/       Instruction-based plugins
```

### OAuth App Plugins (`plugins/omi-*-app/`)
```
omi-slack-app          omi-notion-app        omi-linear-app
omi-github-app         omi-google-calendar-app  omi-clickup-app
omi-dropbox-app        omi-hive-app          omi-shipbob-app
omi-shopify-app        omi-hubspot-app       omi-zapier-app
```

---

## MCP Server (`mcp/`)
- **Package**: `mcp/src/mcp_server_omi/`
- **Entry**: `mcp/src/mcp_server_omi/server.py`
- **Purpose**: Expose OMI data (conversations, memories, etc.) via Model Context Protocol
- **Tests**: `mcp/tests/`

### Backend MCP Endpoints
- `routers/mcp.py` — MCP tool endpoint (streamable HTTP)
- `routers/mcp_sse.py` — MCP over SSE (legacy)
- `database/mcp_api_key.py` — MCP API key management
- `utils/mcp_client.py` (26 KB) — MCP protocol client

---

## SDKs (`sdks/`)
```
sdks/react-native/     React Native SDK
sdks/omi-expo/         Expo SDK
sdks/swift/            Swift SDK
sdks/python/           Python SDK
```

---

## App/Plugin Registration Flow

### Backend
- **CRUD**: `routers/apps.py` (76 KB) — create, update, delete, list, review apps
- **Dev keys**: `routers/developer.py` — developer API key management, sandbox
- **Database**: `database/apps.py` — app metadata storage
- **Models**: `models/app.py` — App, ProactiveNotification, UsageHistoryType
- **Utils**: `utils/apps.py` (53 KB) — app marketplace logic

### Frontend (web)
- **Marketplace**: `web/frontend/src/app/apps/` — browse, install
- **Create wizard**: `web/frontend/src/app/create-app/` — app creation UI
- **Dashboard**: `web/frontend/src/app/my-apps/` — developer management

### Documentation
- **App dev guides**: `docs/doc/developer/apps/` (14 guides)
- **SDK docs**: `docs/doc/developer/sdk/`
- **MCP docs**: `docs/doc/developer/MCP.mdx`
- **API reference**: `docs/doc/developer/api/` (memories, conversations, action-items, keys)
