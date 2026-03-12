"""
Chat Store — SQLite backend for chat history.
Handles saving, loading, and deleting chats + messages.

Using SQLite because it ships with Python, stores everything in one file,
and doesn't need a separate database server — perfect for a local app.
"""

# sqlite3 lets us talk to the SQLite database — it's built into Python so no pip install needed
import sqlite3

# os gives us file path utilities so we can place the DB file next to this script
import os

# datetime stamps each chat and message with when it was created
from datetime import datetime

# uuid generates unique IDs — we use short hex strings as chat identifiers
import uuid

# db file lives next to the source code, same as chroma_db/ — keeps everything in one project folder
DB_PATH = os.path.join(os.path.dirname(__file__), "chat_history.db")


def _get_connection():
    """
    Fresh connection each time — SQLite connections aren't great across
    threads and Flask might use different ones per request.
    """
    # open (or create) the database file — check_same_thread=False lets Flask's threads share it safely
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)

    # rows come back as dicts so we can do row["title"] instead of row[0] — much more readable
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """
    Create tables if they don't already exist. Called once at app startup.

    Two tables:
      chats    — one row per conversation (id, title, pdf_name, created_at)
      messages — individual messages tied to a chat via chat_id

    Keeping them separate means we can list chats quickly without loading
    every single message, and cascade-delete cleans up automatically.
    """
    # grab a fresh connection to run our setup queries
    conn = _get_connection()

    # cursor is what actually executes SQL statements
    cursor = conn.cursor()

    # create the chats table — IF NOT EXISTS means this won't crash if the table already exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT 'New Chat',
            pdf_name TEXT DEFAULT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # create the messages table — foreign key ties each message to its parent chat
    # ON DELETE CASCADE means deleting a chat automatically deletes its messages too
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

    # SQLite has foreign keys off by default — need to flip this on so cascade delete actually works
    cursor.execute("PRAGMA foreign_keys = ON")

    # save everything to disk — without commit, the table creation would be lost
    conn.commit()

    # close the connection so we don't leak file handles
    conn.close()


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def create_chat():
    """
    Create a new empty chat. Title starts as "New Chat" and gets
    updated after the user sends their first question.
    """
    # grab a fresh connection for this operation
    conn = _get_connection()

    # cursor executes our INSERT statement
    cursor = conn.cursor()

    # 8 hex chars is plenty of uniqueness for a local app — gives us ~4 billion possible IDs
    chat_id = uuid.uuid4().hex[:8]

    # ISO format timestamp — stored as text since SQLite doesn't have a native datetime type
    now = datetime.now().isoformat()

    # insert the new chat row with a default title — we'll rename it after the first question
    cursor.execute(
        "INSERT INTO chats (id, title, created_at) VALUES (?, ?, ?)",
        (chat_id, "New Chat", now)
    )

    # save the new row to disk
    conn.commit()

    # done with this connection
    conn.close()

    # return the chat as a dict so the caller can immediately use it without another DB query
    return {"id": chat_id, "title": "New Chat", "pdf_name": None, "created_at": now}


def get_all_chats():
    """
    All chats, newest first — for the sidebar.
    """
    # fresh connection for this read operation
    conn = _get_connection()

    # cursor to run our SELECT query
    cursor = conn.cursor()

    # ORDER BY created_at DESC puts the newest chats at the top — matches the sidebar layout
    cursor.execute("SELECT * FROM chats ORDER BY created_at DESC")

    # convert Row objects to plain dicts so jsonify can serialize them into JSON
    chats = [dict(row) for row in cursor.fetchall()]

    # close the connection when we're done reading
    conn.close()

    return chats


def get_messages(chat_id):
    """
    All messages for a chat, oldest first — standard chat order.
    """
    # fresh connection for this read operation
    conn = _get_connection()

    # cursor to run our SELECT query
    cursor = conn.cursor()

    # fetch messages for this specific chat, sorted chronologically so they display in order
    cursor.execute(
        "SELECT * FROM messages WHERE chat_id = ? ORDER BY created_at ASC",
        (chat_id,)
    )

    # convert Row objects to plain dicts for JSON serialization
    messages = [dict(row) for row in cursor.fetchall()]

    # close the connection when we're done reading
    conn.close()

    return messages


def add_message(chat_id, role, content):
    """
    Save a single message (user or assistant). We store both sides
    so we can reconstruct the full conversation when switching chats.
    """
    # fresh connection for this write operation
    conn = _get_connection()

    # cursor to run our INSERT statement
    cursor = conn.cursor()

    # timestamp the message so we know when it was sent
    now = datetime.now().isoformat()

    # insert the message — role is either "user" or "assistant"
    cursor.execute(
        "INSERT INTO messages (chat_id, role, content, created_at) VALUES (?, ?, ?, ?)",
        (chat_id, role, content, now)
    )

    # save to disk so the message persists
    conn.commit()

    # done with this connection
    conn.close()


def update_chat_title(chat_id, title):
    """
    Rename a chat — called after the first question so the sidebar
    shows something meaningful instead of "New Chat".
    """
    # fresh connection for this update operation
    conn = _get_connection()

    # cursor to run our UPDATE statement
    cursor = conn.cursor()

    # set the title for the matching chat — only affects one row since id is the primary key
    cursor.execute(
        "UPDATE chats SET title = ? WHERE id = ?",
        (title, chat_id)
    )

    # save the title change to disk
    conn.commit()

    # close the connection
    conn.close()


def update_chat_pdf(chat_id, pdf_name):
    """
    Link a PDF filename to a chat so the sidebar can display it.
    """
    # fresh connection for this update operation
    conn = _get_connection()

    # cursor to run our UPDATE statement
    cursor = conn.cursor()

    # store which PDF this chat is associated with — shown in the sidebar next to the chat title
    cursor.execute(
        "UPDATE chats SET pdf_name = ? WHERE id = ?",
        (pdf_name, chat_id)
    )

    # save the PDF link to disk
    conn.commit()

    # close the connection
    conn.close()


def delete_chat(chat_id):
    """
    Delete a chat — the ON DELETE CASCADE in the messages table
    takes care of removing related messages automatically.
    """
    # fresh connection for this delete operation
    conn = _get_connection()

    # cursor to run our DELETE statement
    cursor = conn.cursor()

    # need foreign keys enabled for cascade to kick in — SQLite resets this per-connection
    cursor.execute("PRAGMA foreign_keys = ON")

    # delete the chat row — cascade automatically removes all linked messages
    cursor.execute("DELETE FROM chats WHERE id = ?", (chat_id,))

    # save the deletion to disk
    conn.commit()

    # close the connection
    conn.close()
