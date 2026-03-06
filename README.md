# Void AI: Academic Edge-Computing Ecosystem

**Founder & Lead Engineer:** Yagnik Vanodiya  
**Status:** Active Prototype / Backend Stable

## The Vision
Void AI is not a generic life-logger. It is a stealth, high-performance edge-computing ecosystem engineered specifically for academia. 

Modern university lectures are dense, complex, and fast-paced. Existing AI recorders are optimized for corporate meeting action items. Void AI solves the academic bottleneck by acting as a continuous real-time lecture parser. It streams audio via Bluetooth Low Energy (BLE) to a custom-built processing pipeline, leveraging multimodal LLMs to dynamically generate structured study guides, extract core formulas, and build a searchable vector-database of a student's entire semester.

*Note: This project builds upon the robust open-source Omi architecture, but the core infrastructure has been completely decoupled, overridden, and re-engineered with a proprietary backend and custom data schemas to support our academic focus.*

## Core Architecture & Tech Stack

Void AI operates on a distributed microservices architecture, spanning from bare-metal hardware to cloud-based AI generation.

**1. The Hardware (The Edge)**
* **Current Iteration:** ESP32-S3 with I2S microphones transmitting continuous audio chunks via BLE protocols.
* **Next Phase:** Custom-routed, miniaturized printed circuit boards (PCBs) designed in KiCad for optimal power efficiency and form factor.
* **Future Expansion:** Multi-sensor spatial analytics integration (e.g., BME680 environmental sensors and mmWave radar) for complete room occupancy and contextual environment tracking.

**2. The Client (The Interface)**
* **Framework:** Flutter / Dart (Cross-platform)
* **State Management:** Optimized for high-frequency WebSocket streams to prevent Out-Of-Memory (OOM) compiler crashes during continuous lecture recording.

**3. The Backend (The Brain)**
* **Server:** Python FastAPI deployed on a native Linux environment, securely tunneled via Ngrok for rapid local development.
* **Speech-to-Text:** Real-time streaming integration with Deepgram.
* **AI Agent Pipeline:** OpenAI integrations orchestrated via LangGraph for contextual memory extraction and RAG (Retrieval-Augmented Generation).

**4. The Database (The Memory)**
* **Primary Store:** Firebase Firestore with manually built composite indexes for rapid, complex query filtering.
* **Caching layer:** Upstash TCP database with SSL encryption enabled (replacing default Redis configs to prevent silent 500 internal server errors).
* **Vector Search:** Pinecone database for semantic retrieval of lecture concepts.

## Recent Engineering Milestones
- [x] Successfully bypassed upstream Linux C++ Out-Of-Memory compilation errors for the Flutter client.
- [x] Decoupled upstream cloud dependencies, rerouting authentication and database logic to a proprietary Google Cloud / Firebase instance.
- [x] Resolved hidden streaming errors by configuring custom Firestore composite indexes for AI memory retrieval.
- [x] Stabilized the complete RAG text pipeline: Flutter → FastAPI → Upstash → Pinecone → OpenAI.

## Local Development (Isolation Strategy)
To prevent merge conflicts with upstream open-source branches, Void AI employs a strict Isolation Strategy. The `main` branch acts as a clean upstream mirror, while all proprietary logic, UI overhauls, and backend overrides are engineered and maintained in `void-ai-main` and dedicated feature branches.

---
*Building the ultimate cheat code for the modern classroom.*
