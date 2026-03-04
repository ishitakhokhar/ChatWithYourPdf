# Chat with PDF — Chat History, Persistence & Sidebar Deep Dive

## Feature Overview

This document explains the **chat history persistence** and **ChatGPT-style sidebar** feature. It covers three capabilities:

1. **Save chats permanently** — Every Q&A is stored in a SQLite database on disk.
2. **Show chat history in UI** — Past conversations appear in the sidebar and can be reloaded.
3. **ChatGPT-style sidebar** — "New Chat" button, chat list, delete buttons — the full experience.

---

## New File: `chat_store.py` — Database Layer

### Why a separate file?

Follows the **Single Responsibility Principle** — `app.py` handles HTTP routing, `chat_store.py` handles data storage. This keeps each file focused and testable.

### Why SQLite?

| Factor | SQLite | Alternatives (MySQL, PostgreSQL, MongoDB) |
|--------|--------|------------------------------------------|
| Installation | ❌ None — built into Python | ✅ Must install and configure a server |
| Dependencies | Zero new pip packages | Need `psycopg2`, `pymongo`, etc. |
| Setup | Just `import sqlite3` | Connection strings, credentials, ports |
| Storage | Single `.db` file | Separate running process |
| Backup | Copy one file | Database dump/export tools |

**Bottom line**: For a single-user, local application, SQLite is the right choice. It matches the project's philosophy of "everything runs locally with minimal setup."

### Database Schema

```
┌──────────────────────────────────────┐
│ chats                                │
├──────────┬───────────────────────────┤
│ id       │ TEXT PK (UUID, 8 chars)   │
│ title    │ TEXT (auto-named)         │
│ pdf_name │ TEXT (uploaded filename)  │
│ created_at│ TEXT (ISO timestamp)     │
└──────────┴───────────────────────────┘
         │
         │ One-to-Many
         ▼
┌──────────────────────────────────────┐
│ messages                             │
├──────────┬───────────────────────────┤
│ id       │ INTEGER PK (auto-incr)   │
│ chat_id  │ TEXT FK → chats.id       │
│ role     │ TEXT (user/assistant)     │
│ content  │ TEXT (message text)       │
│ created_at│ TEXT (ISO timestamp)     │
└──────────┴───────────────────────────┘
```

**Why two tables?**
- **Normalized design** — chat metadata (title, PDF name) isn't repeated on every message row.
- **Fast sidebar** — `SELECT * FROM chats` doesn't need to load thousands of messages.
- **Cascade delete** — deleting a chat auto-deletes all its messages.

**Why UUIDs instead of auto-increment integers?**
- Appear in API URLs (`/chats/a1b2c3d4`) — harder to guess than `/chats/1`.
- No collisions if the database is recreated.

### Key Functions

| Function | SQL Operation | Called By |
|----------|--------------|-----------|
| `init_db()` | `CREATE TABLE IF NOT EXISTS` | `app.py` at startup |
| `create_chat()` | `INSERT INTO chats` | POST `/chats/new` |
| `get_all_chats()` | `SELECT * FROM chats ORDER BY created_at DESC` | GET `/chats` |
| `get_messages(chat_id)` | `SELECT * FROM messages WHERE chat_id=? ORDER BY created_at ASC` | GET `/chats/<id>` |
| `add_message(chat_id, role, content)` | `INSERT INTO messages` | POST `/ask` |
| `update_chat_title(chat_id, title)` | `UPDATE chats SET title=?` | POST `/ask` (first message) |
| `update_chat_pdf(chat_id, pdf_name)` | `UPDATE chats SET pdf_name=?` | POST `/upload` |
| `delete_chat(chat_id)` | `DELETE FROM chats WHERE id=?` | DELETE `/chats/<id>` |

---

## Modified File: `app.py` — New API Endpoints

### Why server-side storage instead of localStorage?

- **Survives cache clears** — browser clearing doesn't delete chats.
- **Single source of truth** — no sync issues between client and server.
- **Future-proof** — easy to add multi-user or device sync later.

### New Endpoints

```
GET  /chats          → List all chats (for sidebar)
POST /chats/new      → Create a new empty chat
GET  /chats/<id>     → Get all messages for a chat
DELETE /chats/<id>   → Delete a chat + messages
```

### Modified Endpoints

**POST /upload** — Now accepts optional `chat_id` form field:
```python
chat_id = request.form.get("chat_id")
if chat_id:
    chat_store.update_chat_pdf(chat_id, file.filename)
```

**POST /ask** — Now accepts `chat_id` in JSON body:
```python
chat_id = data.get("chat_id")
if chat_id:
    chat_store.add_message(chat_id, "user", question)
    chat_store.add_message(chat_id, "assistant", answer)
```

### Auto-Title Logic

After the first Q&A pair, the chat title is updated:
```python
if len(messages) <= 2:  # First Q&A = 2 messages
    title = question[:35] + ("..." if len(question) > 35 else "")
    chat_store.update_chat_title(chat_id, title)
```

**Why 35 characters?** Long enough to be readable, short enough to fit in the sidebar without wrapping.

---

## Modified File: `index.html` — Sidebar & JavaScript

### Sidebar Layout

```
┌─────────────────────────┐
│  Logo    [+ New Chat]   │  ← sidebar-header
├─────────────────────────┤
│  📄 Chat Title 1     🗑 │  ← chat-list (scrollable)
│  💬 Chat Title 2     🗑 │
│  📄 Chat Title 3     🗑 │
├─────────────────────────┤  ← sidebar-divider
│  ┌───────────────────┐  │
│  │  Drop PDF here    │  │  ← upload-section
│  └───────────────────┘  │
│  📄 filename.pdf        │  ← file-info
├─────────────────────────┤
│  Powered by Ollama      │  ← sidebar-footer
└─────────────────────────┘
```

### New JavaScript State Variables

```javascript
let currentChatId = null;  // Which chat is currently active
let allChats = [];         // Cache of all chats (for sidebar rendering)
```

### Data Flow — Creating a New Chat

```
User clicks "+ New Chat"
    │
    ├── POST /chats/new → Server creates DB record → Returns {id, title, ...}
    │
    ├── Set currentChatId = new chat's ID
    │
    ├── GET /chats → Reload sidebar list
    │
    └── Clear messages area → Show welcome screen
```

### Data Flow — Asking a Question (with persistence)

```
User types question → clicks Send
    │
    ├── addMessage("user", question)  ← Display in UI immediately
    │
    ├── POST /ask {question, chat_id}
    │     │
    │     ├── Server: engine.ask(question) → Get answer from RAG
    │     ├── Server: add_message(chat_id, "user", question)  ← Save to DB
    │     ├── Server: add_message(chat_id, "assistant", answer)  ← Save to DB
    │     └── Server: update_chat_title() if first message
    │
    ├── addMessage("assistant", answer)  ← Display in UI
    │
    └── loadChats()  ← Refresh sidebar (title may have changed)
```

### Data Flow — Switching Between Chats

```
User clicks a chat item in sidebar
    │
    ├── Set currentChatId = clicked chat's ID
    │
    ├── renderChatList()  ← Update "active" highlight
    │
    ├── GET /chats/<id> → Fetch all messages
    │
    ├── Clear messages container
    │
    ├── Loop: addMessage(role, content) for each saved message
    │
    └── Update status badge (PDF name, if any)
```

---

## Modified File: `style.css` — New Styles

### Key New CSS Classes

| Class | Purpose |
|-------|---------|
| `.new-chat-btn` | "+" button in sidebar header |
| `.chat-list` | Scrollable container for chat items |
| `.chat-item` | Individual chat entry (clickable) |
| `.chat-item.active` | Highlighted with gradient accent bar |
| `.chat-item-icon` | 📄 or 💬 icon |
| `.chat-item-title` | Truncated chat name |
| `.chat-delete-btn` | Trash icon (appears on hover) |
| `.sidebar-divider` | Separator line between chat list and upload |

### Active Chat Indicator

Uses a CSS `::before` pseudo-element to create a gradient accent bar:
```css
.chat-item.active::before {
    content: '';
    position: absolute;
    left: 0;
    top: 20%;
    bottom: 20%;
    width: 3px;
    background: linear-gradient(180deg, var(--accent), var(--accent-2));
}
```

This is the same pattern used by ChatGPT, Discord, and Slack for indicating active items.

---

## Where State Now Lives (Updated)

| State | Location | Lifetime |
|-------|----------|----------|
| Uploaded PDF file | `uploads/` directory | Persists on disk |
| Vector embeddings | `chroma_db/` directory | Replaced on each new upload |
| RAG chain | `engine.chain` (Python memory) | Replaced on each new upload |
| **Chat metadata** | **`chat_history.db` → chats table** | **Permanent until deleted** |
| **Chat messages** | **`chat_history.db` → messages table** | **Permanent until deleted** |
| UI chat messages | Browser DOM | Loaded from DB on chat switch |
| `pdfReady` flag | Browser JS variable | Set per-session |
| `currentChatId` | Browser JS variable | Set per-session |

---

## Interview Q&A

### Q: Why did you add chat history persistence?
**A**: The original app had no persistence — messages lived only in the DOM and were lost on page refresh. For a usable chat application, users need to see their past conversations and continue from where they left off.

### Q: Why SQLite instead of localStorage?
**A**: Three reasons: (1) Data survives browser cache clears. (2) Server is the single source of truth — no sync issues. (3) Foundation for future multi-user or multi-device support.

### Q: How does the auto-naming work?
**A**: After the first Q&A pair (2 messages in the database), the chat title is updated to the first 35 characters of the user's question. This gives each chat a meaningful name without requiring the user to manually name it.

### Q: What's the relationship between chats and PDFs?
**A**: Each chat can have one associated PDF name (`pdf_name` column). However, the RAG engine is still a singleton — uploading a new PDF replaces the previous one's vectors. The `pdf_name` is purely for display purposes in the sidebar.

### Q: How would you scale this for multiple users?
**A**: Add a `user_id` column to the `chats` table, implement authentication (sessions/JWT), and filter queries by user. The current architecture supports this because all CRUD operations already accept `chat_id` — adding `user_id` would be one more filter.
