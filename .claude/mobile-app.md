# Mobile App (Flutter)

## Package: omi (`app/`)
- **Flavors**: dev / prod (`lib/flavors.dart`, `env/dev_env.dart`, `env/prod_env.dart`)
- **Firebase options**: `firebase_options_dev.dart` / `firebase_options_prod.dart`
- **Entry**: `lib/main.dart` → MultiProvider setup (25+ providers) → AppShell
- **Version**: pubspec.yaml `version: 1.0.526+777` (build# must bump for TestFlight)

## Architecture: Provider Pattern
State managed via `provider` package (ChangeNotifier + ProxyProvider chaining).

### Core Providers (`lib/providers/`)
```
capture_provider.dart         Audio capture + BLE streaming orchestration
conversation_provider.dart    Conversation list, grouping, search
device_provider.dart          BLE device connection state
message_provider.dart         Chat messages, history
auth_provider.dart            Firebase auth state
home_provider.dart            Home tab orchestration
app_provider.dart             Plugin/app store state
memories_provider.dart        Memories list
speech_profile_provider.dart  Voice enrollment state
sync_provider.dart            WAL sync state
usage_provider.dart           Subscription/credit tracking
```

### Feature Providers
```
action_items_provider.dart    Tasks, reminders
calendar_provider.dart        Calendar integration
connectivity_provider.dart    Network status
developer_mode_provider.dart  Debug features
folder_provider.dart          Conversation folders
goals_provider.dart           Goals tracking
integration_provider.dart     OAuth connections
locale_provider.dart          Localization
mcp_provider.dart             Model Context Protocol
onboarding_provider.dart      Setup flow
people_provider.dart          Known people/speakers
phone_call_provider.dart      Phone integration
user_provider.dart            User profile
voice_recorder_provider.dart  Audio recording
announcement_provider.dart    Announcements
```

## Pages (`lib/pages/`)
```
home/                Main dashboard
capture/             Live recording UI
conversations/       Conversation list
conversation_detail/ Single conversation view
chat/                AI chat interface
memories/            Memory browser
apps/                App store browser
action_items/        Tasks view
settings/            Settings screens
payments/            Subscription management
onboarding/          First-run onboarding
speech_profile/      Voice enrollment flow
persona/             AI persona config
phone_calls/         Twilio call management
goals/               Goal tracking
sdcard/              SD card data import
announcements/       In-app notifications
referral/            Referral program
```

## Backend HTTP API (`lib/backend/http/api/`)
26 API modules mapping 1:1 to backend routers:
```
conversations.dart  memories.dart       messages.dart      users.dart
apps.dart           speech_profile.dart agents.dart        notifications.dart
payments.dart       integrations.dart   task_integrations.dart
action_items.dart   calendar_meetings.dart  folders.dart   goals.dart
knowledge_graph_api.dart  mcp_api.dart  dev_api.dart      phone_calls.dart
imports.dart        wrapped.dart        announcements.dart audio.dart
device.dart         privacy.dart
```

**Shared HTTP config**: `lib/backend/http/shared.dart` — centralized `makeApiCall()`, auth headers, retry on 401, connection pooling (`http_pool_manager.dart`), GET request deduplication
**Preferences**: `lib/backend/preferences.dart` — SharedPreferencesUtil

## Data Models (`lib/backend/schema/`)
```
conversation.dart        ConversationSource (omi, desktop, phone, web, etc.)
message.dart             ServerMessage, MessageRole
action_item.dart         ActionItem, Priority
person.dart              Person (extracted speakers)
app.dart                 App metadata
agent.dart               Agent metadata
memory.dart              Memory model
folder.dart              Conversation folder
structured.dart          Typed data structures
transcript_segment.dart  Transcript segment
message_event.dart       Real-time message events
bt_device/bt_device.dart Bluetooth device info, audio codec
geolocation.dart         Location data
```

## BLE Device Support (`lib/services/devices/`)
```
omi_connection.dart              OMI DevKit 1/2
void_connection.dart             Void device
friend_pendant_connection.dart   Friend Pendant
frame_connection.dart            Brilliant Frame
bee_connection.dart              Bee device
plaud_connection.dart            Plaud Note
limitless_connection.dart        Limitless Pendant
fieldy_connection.dart           Fieldy
custom_connection.dart           Custom BLE devices
omiglass_connection.dart         OMI Glass (ESP32-S3)
apple_watch_connection.dart      Apple Watch bridge
device_connection.dart           Base class
```

## Transcription Pipeline (`lib/services/sockets/`)
```
transcription_service.dart              Orchestrator
composite_transcription_socket.dart     Multi-source composition
pure_socket.dart                        Raw WebSocket to backend /listen
pure_streaming_stt.dart                 On-device STT (Whisper)
on_device_whisper_provider.dart         Whisper model management
on_device_apple_provider.dart           Apple on-device speech
pure_polling.dart                       Polling fallback
transcription_polling_service.dart      Polling implementation
```

## WAL System (`lib/services/wals/`)
Write-ahead log for offline-first reliability:
```
wal.dart / wal_service.dart       Core WAL logic
local_wal_sync.dart               Local storage sync
flash_page_wal_sync.dart          Firmware flash page sync
sdcard_wal_sync.dart              SD card sync
```

## UI Design System (`lib/ui/`)
- **Atoms**: `omi_button`, `omi_text_input`, `omi_checkbox`, `omi_avatar`, `omi_badge`, `omi_search_input`
- **Molecules**: `omi_chat_bubble`, `omi_confirm_dialog`, `omi_empty_state`, `omi_popup_menu`
- **Theme**: Dark theme only, SF Pro Display font, deep purple accent

## Localization
- 34 locales in `lib/l10n/` (English + 33 translations)
- Config: `l10n.yaml`
- Generated files: `lib/gen/`
- **Rule**: Never read full ARB files (large). Use `jq` to add keys. Provide real translations for all locales.
- Regenerate: `cd app && flutter gen-l10n`

## Key Packages
```
provider (state)         flutter_blue_plus (BLE)    firebase_* (auth, messaging, crashlytics)
opus_dart (audio codec)  flutter_sound (playback)   just_audio (player)
mixpanel_flutter         growthbook_sdk_flutter      intercom_flutter
web_socket_channel       marionette_flutter (e2e)    geolocator
flutter_contacts         fl_chart                    flutter_map
```

## Services (`lib/services/`)
```
auth_service.dart           Firebase Auth, Google/Apple Sign-In
sockets.dart                WebSocket pool management (mutex-protected)
notifications.dart          FCM setup, handlers
devices.dart                BLE discovery, pairing
phone_call_service.dart     Phone call detection
calendar_service.dart       Calendar event fetch
apple_health_service.dart   Apple Health integration
apple_reminders_service.dart  Apple Reminders sync
audio_download_service.dart   Audio file download
```
