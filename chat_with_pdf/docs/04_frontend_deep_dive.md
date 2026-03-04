# Chat with PDF — Frontend Deep Dive (`index.html` + `style.css`)

## File Purpose

`index.html` is a **single-page application** that provides the complete chat interface. It includes inline JavaScript for all client-side logic (upload, chat, UI state). `style.css` provides a premium dark theme with glassmorphism, animations, and responsive design.

---

## HTML Structure Overview

```
<body>
├── .bg-blob (×3)              ← Animated background gradient blobs
└── .app-container             ← Flexbox layout (sidebar + main)
    ├── <aside> .sidebar       ← Left panel
    │   ├── .sidebar-header    ← Logo ("PDF Chat")
    │   ├── .upload-section    ← Drag-and-drop upload zone
    │   ├── .file-info         ← Shows filename + chunk count after upload
    │   ├── .upload-progress   ← Progress bar during processing
    │   └── .sidebar-footer    ← "Powered by Ollama + ChromaDB"
    │
    └── <main> .chat-area      ← Right panel
        ├── .chat-header       ← Title + status badge + mobile menu
        ├── .messages-container ← Chat message list
        │   └── .welcome-screen ← Initial feature cards
        └── .input-bar         ← Textarea + send button
```

---

## JavaScript — Functional Breakdown

### DOM References (Lines 159–176)

All interactive elements are cached in variables at startup for performance:
```javascript
const uploadZone     = document.getElementById("uploadZone");
const fileInput      = document.getElementById("fileInput");
// ... 12 more element references
let pdfReady = false;    // Global flag gating question input
```

### Upload Logic (Lines 182–250)

**Three input methods supported:**
1. **Click** → `uploadZone.addEventListener("click", () => fileInput.click())`
2. **Drag-over** → Adds `.drag-over` CSS class for visual feedback
3. **Drop** → Extracts file from `DataTransfer`, calls `handleUpload()`

**`handleUpload(file)` flow:**
```
1. Validate .pdf extension (client-side check)
2. Show progress bar (30% → "Uploading...")
3. Create FormData, append file
4. Update progress (60% → "Extracting & indexing...")
5. POST /upload with FormData
6. On success:
   - Progress → 100% → "Done!"
   - After 600ms delay: hide progress, show file card
   - Enable question input + send button
   - Set status badge to active (green pulsing dot)
   - Add success message to chat
7. On error:
   - Hide progress, show error in chat
```

### Chat Logic (Lines 252–296)

**`sendQuestion()` flow:**
```
1. Get question text, validate non-empty + pdfReady
2. Add user message bubble to chat
3. Clear input, reset height
4. Show typing indicator (animated dots)
5. POST /ask with JSON { question }
6. Remove typing indicator
7. Add AI response bubble (or error message)
```

**Enter key handling**: `Enter` sends, `Shift+Enter` creates a new line.

**Auto-resize textarea**: On `input` event, sets height to `scrollHeight` (up to 120px max).

### Message Rendering (Lines 299–343)

```javascript
function addMessage(role, text) {
    welcomeScreen.style.display = "none";   // Hide welcome on first message
    // Creates: <div class="message {role}">
    //            <div class="msg-avatar">You/AI/ℹ️</div>
    //            <div class="msg-content">{text}</div>
    //          </div>
    messagesEl.scrollTop = messagesEl.scrollHeight;  // Auto-scroll
}
```

**Typing indicator**: Creates a temporary message with three animated dots. Removed by ID once the real response arrives.

---

## CSS Design System (`style.css`)

### CSS Custom Properties (Design Tokens)

```css
:root {
    --bg:          #0b0f1a;       /* Deep navy background */
    --surface:     #111827;       /* Card/panel background */
    --surface-2:   #1e293b;       /* Elevated surface */
    --border:      rgba(255,255,255,0.06);  /* Subtle borders */
    --text:        #e2e8f0;       /* Primary text (light gray) */
    --text-muted:  #94a3b8;       /* Secondary text */
    --accent:      #818cf8;       /* Indigo — primary brand */
    --accent-2:    #c084fc;       /* Purple — secondary brand */
    --user-bubble: #312e81;       /* Deep indigo for user messages */
    --ai-bubble:   #1e293b;       /* Dark slate for AI messages */
    --danger:      #f87171;       /* Error state (red) */
    --success:     #34d399;       /* Success state (green) */
}
```

### Visual Features

| Feature | Technique |
|---------|-----------|
| **Glassmorphism** | `backdrop-filter: blur(24px)` + semi-transparent backgrounds |
| **Animated blobs** | Three fixed `div`s with `filter: blur(120px)`, animated with `@keyframes blobFloat` |
| **Gradient buttons** | `linear-gradient(135deg, var(--accent), var(--accent-2))` |
| **Typing dots** | `@keyframes dotBounce` — three spans with staggered `animation-delay` |
| **Status pulse** | `@keyframes pulse` on the green dot with `box-shadow` glow |
| **Message animation** | `@keyframes msgIn` — fade up on every new message |
| **Responsive sidebar** | At ≤768px: sidebar becomes a fixed overlay with `transform: translateX(-100%)`, toggled via `.open` class |

### Responsive Breakpoint (≤768px)

```css
@media (max-width: 768px) {
    .sidebar { position: fixed; transform: translateX(-100%); }
    .sidebar.open { transform: translateX(0); }
    .menu-btn { display: block; }
}
```
The sidebar slides in from the left on mobile, controlled by the hamburger menu button.

---

## Frontend ↔ Backend API Contract

| Endpoint | Method | Request | Success Response | Error Response |
|----------|--------|---------|-----------------|----------------|
| `/` | GET | — | HTML page | — |
| `/upload` | POST | `multipart/form-data` with `file` field | `{message, filename, chunks}` | `{error}` (400/500) |
| `/ask` | POST | `application/json` with `{question}` | `{answer}` | `{error}` (400/500) |
