# Web Applications

## 1. Public Website — `web/frontend/`
- **Framework**: Next.js + React + TypeScript + Tailwind CSS
- **Deploy**: Cloud Run via `gcp_frontend.yml`

### Routes (`src/app/`)
```
/apps              App marketplace (list, categories, popular)
/apps/[id]         Individual app page
/create-app        App creation wizard
/my-apps           Developer's apps dashboard
/memories          Public shared memories
/tasks             Task management
/wrapped           Year-in-review feature
/dreamforce        Event landing page
/unlimited         Premium tier landing
```

### Key Directories
```
src/actions/       Server actions (apps, memories, plugins, tasks, trends)
src/components/    Shared UI: dashboard, memories, plugins, trends, shared, ui
src/hooks/         React hooks
src/lib/           API client (lib/api/), Firebase config (firebase.ts), utils
src/constants/     App constants
src/types/         TypeScript type definitions
```

---

## 2. Authenticated Dashboard — `web/app/`
- **Framework**: Next.js 16 (App Router) + React 19 + TypeScript + Tailwind CSS
- **Deploy**: Cloud Run via `gcp_apps_js.yml`

### Routes (`src/app/`)
```
/login                  Auth flow (Firebase: Google/Apple)
/(authenticated)/       Protected layout:
  /chat                 AI chat interface
  /conversations        Conversation browser
  /memories             Memory browser
  /my-apps              App management
  /recaps               Conversation recaps
  /settings             User settings
  /tasks                Task management
/(public)/              Public shared content
/record                 Audio recording
/api/apps               App API proxy
/api/proxy              General API proxy
```

### Key Directories
```
src/components/
  auth/                 Sign-in, OAuth callbacks
  chat/                 Chat UI (ChatWindow, messages)
  conversations/        Conversation list/detail
  layout/               App shell, navbar, sidebar
  ui/                   Design system (Radix UI primitives)
  settings/             Settings panels
  tasks/                Task management
  memories/             Memory browser
  apps/                 Integration manager
  marketplace/          App store
  notifications/        Toast notifications
  recording/            Audio recording
src/hooks/              Custom React hooks
src/lib/api/            Fetch wrappers to backend API
src/lib/analytics/      Mixpanel tracking
src/types/              TypeScript types
src/workers/            Web Workers (background processing)
```

### Key Packages
```
firebase               Auth, Firestore real-time
react-markdown         Render markdown messages
framer-motion          Animations
react-force-graph-3d   3D knowledge graph visualization
@radix-ui/*            Accessible UI primitives
lucide-react           Icons
tailwind-merge         Dynamic class merging
fuse.js                Client-side search
idb                    IndexedDB caching
three.js               3D rendering
react-window           Virtual scrolling
```

---

## 3. Personas Builder — `web/personas-open-source/`
- **Framework**: Next.js + React
- **Deploy**: Cloud Run via `gcp_personas.yml`
- Open-source personas creation and sharing
