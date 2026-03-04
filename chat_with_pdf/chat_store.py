"""
Chat Store — SQLite Database for Chat History Persistence.
This module handles saving, loading, and deleting chats and their messages.

WHY SQLite?
  - Built into Python (import sqlite3) — no extra pip installs needed.
  - Data is stored in a single file (chat_history.db) — easy to backup or delete.
  - Perfect for single-user, local applications like this.
  - No database server setup required — matches the project's "run locally" philosophy.
"""

# 'sqlite3' — Python's built-in module for SQLite database operations.
# No installation needed — it ships with every Python distribution.
import sqlite3

# 'os' — for building the database file path relative to this file's location.
import os

# 'datetime' — for generating timestamps when creating chats and messages.
from datetime import datetime

# 'uuid' — for generating unique chat IDs.
# WHY UUIDs instead of auto-increment integers?
#   - IDs appear in API URLs (/chats/abc123) — UUIDs are harder to guess.
#   - No collisions if the database is ever recreated.
#   - Industry standard for resource identifiers in web APIs.
import uuid


# ---------------------------------------------------------------------------
# Database path — stored alongside the source code, just like chroma_db/
# ---------------------------------------------------------------------------

# This creates a path like "D:\MLDL\DL\chat_with_pdf\chat_history.db"
DB_PATH = os.path.join(os.path.dirname(__file__), "chat_history.db")


# ---------------------------------------------------------------------------
# Database initialization — creates tables if they don't exist
# ---------------------------------------------------------------------------

def _get_connection():
    """
    Create and return a database connection.

    WHY a function instead of a global connection?
      - SQLite connections are not thread-safe by default.
      - Flask may handle requests in different threads.
      - Creating a fresh connection per operation is the safest approach.
      - The 'check_same_thread=False' flag allows cross-thread usage as a fallback.
    """
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)

    # Return rows as dictionaries instead of tuples.
    # WHY? So we can access columns by name (row["title"]) instead of index (row[0]).
    # This makes the code much more readable and maintainable.
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    Create the database tables if they don't already exist.
    Called once when the Flask app starts.

    TABLE DESIGN:
    ┌──────────────────────────────────────────────────────┐
    │ chats                                                │
    ├──────────┬─────────┬─────────────────────────────────┤
    │ id       │ TEXT PK │ UUID — unique identifier        │
    │ title    │ TEXT    │ Display name (first question)   │
    │ pdf_name │ TEXT    │ Name of the uploaded PDF        │
    │ created_at│ TEXT   │ ISO timestamp of creation       │
    └──────────┴─────────┴─────────────────────────────────┘
            │
            │ One-to-Many (one chat has many messages)
            ▼
    ┌──────────────────────────────────────────────────────┐
    │ messages                                             │
    ├──────────┬─────────┬─────────────────────────────────┤
    │ id       │ INT PK  │ Auto-increment ID               │
    │ chat_id  │ TEXT FK │ References chats.id             │
    │ role     │ TEXT    │ "user", "assistant", or "system"│
    │ content  │ TEXT    │ The actual message text         │
    │ created_at│ TEXT   │ ISO timestamp                   │
    └──────────┴─────────┴─────────────────────────────────┘

    WHY two tables instead of one?
      - Normalized design — avoids repeating chat info on every message row.
      - Can query chats list without loading all messages (faster sidebar).
      - Can delete a chat and cascade-delete all its messages in one operation.
    """
    conn = _get_connection()
    cursor = conn.cursor()

    # Create the 'chats' table — stores metadata about each conversation
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT 'New Chat',
            pdf_name TEXT DEFAULT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # Create the 'messages' table — stores individual messages within a chat
    # FOREIGN KEY ensures referential integrity: every message must belong to a valid chat
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (chat_id) REFERENCES chats (id) ON DELETE CASCADE
        )
    """)

    # Enable foreign key enforcement
    # WHY? SQLite has foreign keys disabled by default for backwards compatibility.
    # Without this, deleting a chat would leave orphaned messages in the database.
    cursor.execute("PRAGMA foreign_keys = ON")

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# CRUD Operations — Create, Read, Update, Delete
# ---------------------------------------------------------------------------

def create_chat():
    """
    Create a new empty chat and return its data.

    WHAT HAPPENS:
      1. Generate a unique UUID for the chat.
      2. Set the title to "New Chat" (will be updated after the first question).
      3. Record the current timestamp.
      4. Insert into the database.
      5. Return the chat data as a dictionary.

    RETURNS: dict with keys: id, title, pdf_name, created_at
    """
    conn = _get_connection()
    cursor = conn.cursor()

    # Generate a short, unique ID (first 8 chars of a UUID)
    # WHY 8 chars? Full UUIDs are 36 chars — too long for URLs.
    # 8 hex chars = 4 billion possible values — more than enough for a local app.
    chat_id = uuid.uuid4().hex[:8]
    now = datetime.now().isoformat()

    cursor.execute(
        "INSERT INTO chats (id, title, created_at) VALUES (?, ?, ?)",
        (chat_id, "New Chat", now)
    )
    conn.commit()
    conn.close()

    return {"id": chat_id, "title": "New Chat", "pdf_name": None, "created_at": now}


def get_all_chats():
    """
    Return all chats, newest first.

    WHY ORDER BY created_at DESC?
      - Most recent chats appear at the top of the sidebar.
      - This matches the UX pattern users expect from ChatGPT, Slack, etc.

    RETURNS: list of dicts, each with keys: id, title, pdf_name, created_at
    """
    conn = _get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM chats ORDER BY created_at DESC")

    # Convert sqlite3.Row objects to plain dicts (so Flask's jsonify can serialize them)
    chats = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return chats


def get_messages(chat_id):
    """
    Return all messages for a specific chat, in chronological order.

    WHY ORDER BY created_at ASC?
      - Messages should appear in the order they were sent.
      - Oldest message at the top, newest at the bottom (standard chat layout).

    RETURNS: list of dicts, each with keys: id, chat_id, role, content, created_at
    """
    conn = _get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM messages WHERE chat_id = ? ORDER BY created_at ASC",
        (chat_id,)
    )
    messages = [dict(row) for row in cursor.fetchall()]
    conn.close()

    return messages


def add_message(chat_id, role, content):
    """
    Add a single message to a chat.

    PARAMETERS:
      - chat_id: which chat this message belongs to
      - role: "user", "assistant", or "system"
      - content: the actual message text

    WHY save both user AND assistant messages?
      - Need both sides to reconstruct the full conversation when the user switches chats.
      - Enables showing the complete Q&A history, not just questions or just answers.
    """
    conn = _get_connection()
    cursor = conn.cursor()

    now = datetime.now().isoformat()
    cursor.execute(
        "INSERT INTO messages (chat_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (chat_id, role, content, now)
    )
    conn.commit()
    conn.close()


def update_chat_title(chat_id, title):
    """
    Update the display title of a chat.

    WHEN IS THIS CALLED?
      - After the user sends their first question in a new chat.
      - The title is set to the first ~30 characters of the question.
      - This gives each chat a meaningful name in the sidebar.

    WHY not set the title at creation time?
      - We don't know what the user will ask until they send a message.
      - "New Chat" is a placeholder that gets replaced automatically.
    """
    conn = _get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE chats SET title = ? WHERE id = ?",
        (title, chat_id)
    )
    conn.commit()
    conn.close()


def update_chat_pdf(chat_id, pdf_name):
    """
    Associate a PDF filename with a chat.

    WHEN IS THIS CALLED?
      - When the user uploads a PDF while in a specific chat.
      - Stores the PDF name so the sidebar can show which PDF each chat used.
    """
    conn = _get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE chats SET pdf_name = ? WHERE id = ?",
        (pdf_name, chat_id)
    )
    conn.commit()
    conn.close()


def delete_chat(chat_id):
    """
    Delete a chat and all its messages.

    HOW CASCADE DELETE WORKS:
      - The 'messages' table has: FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE
      - When we delete a row from 'chats', SQLite automatically deletes all matching rows
        in 'messages' — no need to delete messages manually.
      - This prevents orphaned messages that would waste disk space.

    WHY not soft-delete (marking as deleted instead of removing)?
      - This is a local-only app — no need for audit trails.
      - Actual deletion saves disk space and keeps the database clean.
    """
    conn = _get_connection()
    cursor = conn.cursor()

    # Enable foreign keys for this connection (required for CASCADE to work)
    cursor.execute("PRAGMA foreign_keys = ON")
    cursor.execute("DELETE FROM chats WHERE id = ?", (chat_id,))

    conn.commit()
    conn.close()
