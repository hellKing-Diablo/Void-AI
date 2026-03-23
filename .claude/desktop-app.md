# Desktop App (macOS)

## Structure
```
desktop/Desktop/          Swift/SwiftUI macOS app (SPM, no .xcodeproj)
desktop/Backend-Rust/     Embedded Rust backend (Actix-web, runs locally)
desktop/acp-bridge/       ACP (Agent Computer Protocol) bridge (Node.js)
desktop/agent-cloud/      Agent cloud connector (Node.js)
```

## Build System
- **Swift Package Manager**: `desktop/Desktop/Package.swift`
- **Dev build & run**: `./run.sh` (builds Swift, starts Rust backend, Cloudflare tunnel, launches app)
- **Release build**: `./build.sh`
- **NEVER** use bare `swift build` or `xcodebuild` — always use `run.sh` or `build.sh`
- **Bundle IDs**: Dev `com.omi.desktop-dev` | Prod `com.omi.computer-macos`
- **Verify UI changes**: `agent-swift` (Accessibility API, no app instrumentation needed)

## Swift App (`desktop/Desktop/Sources/`)

### Entry: `OmiApp.swift`

### Core Services
```
AppState.swift                 Global app state (112 KB — central hub, all models)
APIClient.swift                REST client to api.omi.me (4574 lines)
AuthService.swift              Firebase Auth (Apple/Google via backend OAuth, 54 KB)
TranscriptionService.swift     Audio → STT pipeline
AudioCaptureService.swift      System + mic audio capture (25 KB)
AudioLevelMonitor.swift        Real-time audio level metering
AudioMixer.swift               Multi-source audio mixing
ScreenCaptureService.swift     Screen recording (ScreenCaptureKit)
ScreenActivitySyncService.swift Screen activity upload
VADGateService.swift           Voice activity detection gate
LiveTranscriptMonitor.swift    Real-time transcript display
BluetoothManager.swift         BLE device management (Bluetooth/)
AgentVMService.swift           Agent VM WebSocket connection
AgentSyncService.swift         Agent state synchronization
AnalyticsManager.swift         Mixpanel + PostHog (42 KB)
DesktopAutomationBridge.swift  Automation server
Logger.swift                   Logging to /tmp/omi-dev.log
```

### Feature Modules
```
FloatingControlBar/     Global floating UI bar (ask AI, shortcuts, push-to-talk)
LiveNotes/              Real-time conversation notes (models, monitor, storage)
Rewind/                 Screen rewind/search
  Core/                 Data models, storage (SQLite via GRDB)
  Services/             OCR embedding, indexing, power monitoring
  UI/                   Timeline player, search, filmstrip
ProactiveAssistants/    AI assistants (scheduled/contextual)
  Assistants/           Advice, MemoryExtraction, TaskExtraction, TaskAgent
  Services/             Scheduling, embedding, notifications, overlay, profile
  UI/                   Prompt editors, glow overlays
FileIndexing/           Local file system monitoring + knowledge graph
Chat/                   AI chat (via ACP bridge to Claude)
  ACPBridge.swift       Desktop automation integration
  ChatPrompts.swift     System prompts
```

### Pages (`MainWindow/Pages/`)
```
DesktopHomeView.swift          Dashboard (daily score, tasks, conversations)
ChatPage.swift                 AI chat interface
ConversationsPage.swift        Conversation list
ConversationDetailView.swift   Single conversation detail
TasksPage.swift                Task management
MemoriesPage.swift             Memory recall
MemoryGraph/                   Force-directed knowledge graph visualization
GoalsHistoryPage.swift         Goals tracking
AppsPage.swift                 Integrations marketplace
PersonaPage.swift              User persona settings
FocusPage.swift                Focus mode
AdvicePage.swift               Advice feed
SettingsPage.swift             Preferences
PermissionsPage.swift          macOS permissions
DeviceSettingsPage.swift       Device pairing
RewindPage.swift               Screen rewind
```

### State Management
```
Stores/TasksStore.swift               Task persistence
Providers/AppProvider.swift            Root state
Providers/ChatProvider.swift           Chat state
Providers/DeviceProvider.swift         Device state
Providers/ChatToolExecutor.swift       Tool execution for chat
```

### Audio Pipeline
```
Audio/AudioCodecDecoder.swift    Codec decoding (Opus, LC3)
Audio/AudioSourceManager.swift   Audio source selection
Audio/BleAudioProcessor.swift    BLE audio frame processing
Audio/BleAudioService.swift      BLE audio streaming
```

### WAL System (`WAL/`)
```
WALModel.swift           Write-ahead log data model
WALService.swift         WAL lifecycle management
StorageSyncService.swift Cloud sync for local data
WifiSyncService.swift    WiFi-based device sync
StorageSyncView.swift    Sync status UI
```

## Rust Backend (`desktop/Backend-Rust/`)
- **Framework**: Actix-web
- **Entry**: `src/main.rs`
- **Connects directly** to Firestore + Redis (not through Python backend)

### Routes (`src/routes/`)
```
conversations  memories     chat          chat_sessions  messages
action_items   goals        agents        apps           users
auth           people       personas      knowledge_graph
screen_activity focus_sessions folders     staged_tasks   stats
daily_score    advice       llm_usage     updates        webhooks
crisp          health
```

### Services (`src/services/`)
```
firestore.rs       Firestore client (direct)
redis.rs           Redis client
integrations.rs    External integrations
```

### LLM (`src/llm/`)
```
client.rs    OpenAI/Claude API client
persona.rs   Persona-specific prompts
prompts.rs   System prompts
```

### Models (`src/models/`) — 20 model files mirroring backend Pydantic models
