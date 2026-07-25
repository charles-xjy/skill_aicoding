"""Persistent checkpoint backend for the local LangGraph server."""

from pathlib import Path

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver


DB_PATH = Path(__file__).resolve().with_name("checkpoints.db")

# ``from_conn_string`` returns an async context manager. LangGraph Server owns
# its lifecycle when this object is referenced by ``checkpointer.path``.
checkpointer = AsyncSqliteSaver.from_conn_string(str(DB_PATH))
