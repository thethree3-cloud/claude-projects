"""FastAPI HTTP layer -- a thin protocol wrapper over attempts.py,
hints.py, leaderboard.py, and puzzles.py. All the business logic was
already built and tested standalone before this file existed (same
"logic first, protocol wrapper after" pattern Project 11's server.py
uses for its MCP tools) -- this file's only job is HTTP request ->
function call -> HTTP response, and turning AttemptError/HintError into a
readable 4xx instead of a raw 500.

Run with:
    uvicorn api:app --reload
"""
from __future__ import annotations

import sqlite3

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel

from attempts import AttemptError, start_attempt, submit_guess
from db import DEFAULT_DB_PATH, get_connection, init_schema
from hints import apply_hint
from leaderboard import get_leaderboard
from puzzles import get_todays_puzzle

app = FastAPI(title="Big Money Movie")


def get_db():
    """One connection per request. SQLite + FastAPI's per-request
    dependency injection; init_schema is CREATE TABLE IF NOT EXISTS, so
    calling it every request is a cheap no-op once the schema exists."""
    conn = get_connection(DEFAULT_DB_PATH)
    init_schema(conn)
    try:
        yield conn
    finally:
        conn.close()


class StartAttemptRequest(BaseModel):
    puzzle_id: int
    player_id: str


class GuessRequest(BaseModel):
    guess_text: str


class HintRequest(BaseModel):
    tier: int


@app.get("/")
def health_check():
    return {"status": "ok", "game": "Big Money Movie"}


@app.get("/category/today")
def category_today(conn: sqlite3.Connection = Depends(get_db)):
    try:
        return get_todays_puzzle(conn)
    except AttemptError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@app.post("/attempt/start")
def attempt_start(body: StartAttemptRequest, conn: sqlite3.Connection = Depends(get_db)):
    try:
        attempt_id = start_attempt(conn, puzzle_id=body.puzzle_id, player_id=body.player_id)
    except AttemptError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"attempt_id": attempt_id}


@app.post("/attempt/{attempt_id}/guess")
def attempt_guess(
    attempt_id: int, body: GuessRequest, conn: sqlite3.Connection = Depends(get_db)
):
    try:
        return submit_guess(conn, attempt_id, body.guess_text)
    except AttemptError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.post("/attempt/{attempt_id}/hint")
def attempt_hint(attempt_id: int, body: HintRequest, conn: sqlite3.Connection = Depends(get_db)):
    try:
        # apply_hint raises hints.HintError, a subclass of AttemptError --
        # catching the parent here covers both.
        return apply_hint(conn, attempt_id, body.tier)
    except AttemptError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/leaderboard/{puzzle_id}")
def leaderboard(puzzle_id: int, limit: int = 10, conn: sqlite3.Connection = Depends(get_db)):
    return get_leaderboard(conn, puzzle_id, limit=limit)
