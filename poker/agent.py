"""
agent.py - YOUR poker bot. This one file is a complete web server.

Run it:
    python agent.py                  # listens on port 5008
    PORT=5010 python agent.py        # or pick a port

Play a match against a baseline (three windows):
    python agent.py                                 # your bot on port 5008
    python baseline-bots/baseline_random.py         # opponent on port 5009
    python judge_engine.py                          # judge: both halves (uses those two ports)

Check that the tournament can run it:
    python -m pytest -q              # tests in test_agent.py
    ./tools/check_build.sh           # builds and smoke-tests it like the tournament

TODO:
    1. Assign your agent a unique PARTICIPANT and AGENT_NAME below.
    2. Implement the three functions between "YOUR CODE HERE" and "END OF YOUR CODE".

Everything under "SERVER PLUMBING" talks to the judge. You normally never
need to change it, and if you break it the judge can't talk to your bot.
"""

import os
import traceback

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

import random
import time

from evaluator import card_rank, card_suit, cards_to_str, omaha_score, warmup  # handy helpers, see evaluator.py
from game import Action, AgentConfig, HandResult, Observation, Street

# Build omaha_score's lookup table now, while the server starts, instead of
# during your first decision (where it would eat into your time bank).
# Do any other slow setup (loading a model, ...) here too: the server must
# answer within 15 seconds of starting.
warmup()

# rename as your team/bot's name
PARTICIPANT = "PitBoss"
AGENT_NAME = "PitBossEquity"


# ===== YOUR CODE HERE =====

_RNG = random.Random(7)
_BUDGET_SECONDS = 6.5


def new_half(config: AgentConfig, memory: dict) -> None:
    memory["used"] = 0.0
    memory["showdowns"] = 0
    memory["showdown_wins"] = 0


def _fallback(obs: Observation) -> Action:
    if obs.to_call == 0 and Action.CHECK_CALL in obs.legal_actions:
        return Action.CHECK_CALL
    if Action.FOLD in obs.legal_actions:
        return Action.FOLD
    return obs.legal_actions[0]


def _preflop_score(cards) -> int:
    ranks = [card_rank(card) for card in cards]
    suits = [card_suit(card) for card in cards]
    pairs = sum(1 for rank in set(ranks) if ranks.count(rank) >= 2)
    suited = max(suits.count(suit) for suit in set(suits))
    high = sum(1 for rank in ranks if rank >= 6)
    span = max(ranks) - min(ranks)
    return pairs * 3 + suited + high - (1 if span > 6 else 0)


def _equity(obs: Observation, samples: int) -> float:
    known = set(obs.hole_cards) | set(obs.board)
    deck = [card for card in range(36) if card not in known]
    need_board = 5 - len(obs.board)
    wins = ties = 0
    for _ in range(samples):
        draw = _RNG.sample(deck, need_board + 5)
        board = list(obs.board) + draw[:need_board]
        opponent = draw[need_board:]
        mine = omaha_score(obs.hole_cards, board)
        theirs = omaha_score(opponent, board)
        if mine > theirs:
            wins += 1
        elif mine == theirs:
            ties += 1
    return (wins + 0.5 * ties) / samples


def _pot_odds(obs: Observation) -> float:
    if obs.to_call <= 0:
        return 0.0
    return obs.to_call / (obs.pot + obs.to_call)


def choose_action(obs: Observation, memory: dict) -> Action:
    started = time.perf_counter()
    try:
        if memory.get("used", 0.0) >= _BUDGET_SECONDS:
            return _fallback(obs)
        opponent_raises = sum(1 for item in obs.action_history if not item.is_me and item.action in (Action.RAISE_HALF, Action.RAISE_POT))
        if obs.street == Street.PREFLOP:
            score = _preflop_score(obs.hole_cards)
            if score >= 8 and Action.RAISE_POT in obs.legal_actions and obs.to_call <= obs.big_blind * 4:
                return Action.RAISE_POT
            if obs.to_call == 0:
                return Action.CHECK_CALL
            if score >= 4 and obs.to_call <= obs.big_blind * 6:
                return Action.CHECK_CALL
            return _fallback(obs)
        samples = 8 if len(obs.board) < 5 else 24
        if memory.get("used", 0.0) > 4.5:
            samples = 4
        equity = _equity(obs, samples)
        if opponent_raises:
            equity -= min(0.08, 0.02 * opponent_raises)
        price = _pot_odds(obs)
        if equity >= 0.72 and Action.RAISE_POT in obs.legal_actions and obs.raises_this_street < 3:
            return Action.RAISE_POT
        if equity + 0.03 >= price:
            return Action.CHECK_CALL if Action.CHECK_CALL in obs.legal_actions else _fallback(obs)
        return _fallback(obs)
    except Exception:
        return _fallback(obs)
    finally:
        memory["used"] = memory.get("used", 0.0) + (time.perf_counter() - started)


def on_hand_end(result: HandResult, memory: dict) -> None:
    if result.went_to_showdown:
        memory["showdowns"] = memory.get("showdowns", 0) + 1
        if result.winner == "me":
            memory["showdown_wins"] = memory.get("showdown_wins", 0) + 1

# ===== END OF YOUR CODE =====


# ===== SERVER PLUMBING (you normally don't need to edit below) =====
# The judge calls these routes:
#   GET  /           -> who you are (also used as the health check)
#   POST /new-half   -> start a fresh half: memory is wiped
#   POST /act        -> the judge sends any finished hands plus an Observation;
#                       on_hand_end() runs for each hand, then you answer an action
#   POST /hand-end   -> the judge sends the last finished hands of a half
#
# Why "async def"? The routes run on one thread and call your functions
# directly, so your functions never run twice at once. Your own functions
# stay normal "def" (don't make them async).
#
# Keep your per-half state in `memory`. In the tournament every half runs in
# a fresh server process, so everything starts over. When you test locally,
# though, one process can play both halves and only `memory` is wiped, NOT
# other global variables. Using `memory` makes your bot behave the same way
# in both places.

app = FastAPI()
MEMORY: dict = {}                                   # your memory for this half
STATUS = {"started": False}                         # has /new-half been called?
TOKEN = os.environ.get("AGENT_TOKEN") or None       # set by the tournament


async def _read_request(request: Request, path: str) -> tuple[dict, JSONResponse | None]:
    """Check the token (and that the half has started) BEFORE reading the body.

    Checking first means a request without the right token costs your bot
    almost nothing, so nobody else can slow it down by sending junk.
    Returns (body, None) when the request is fine, or ({}, error response).
    """
    if TOKEN and request.headers.get("x-agent-token") != TOKEN:
        return {}, JSONResponse({"error": "bad or missing X-Agent-Token"}, status_code=401)
    if not STATUS["started"] and path != "/new-half":
        return {}, JSONResponse({"error": "call /new-half first"}, status_code=409)
    try:
        body = await request.json()
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return {}, JSONResponse({"error": "the request body must be a JSON object"}, status_code=400)
    return body, None


def _error_info(exc: Exception) -> dict:
    """Describe an exception from your code (call this inside `except`)."""
    return {"error": f"{type(exc).__name__}: {exc}", "traceback": traceback.format_exc()}


def _crash(exc: Exception, hand_end_errors: list | None = None) -> JSONResponse:
    """Report an exception from your code to the judge (with traceback)."""
    return JSONResponse({**_error_info(exc), "hand_end_errors": hand_end_errors or []},
                        status_code=500)


def _deliver_results(raw_results) -> list:
    """Call on_hand_end() for each finished hand the judge sent.
    Returns a list of error reports (one per hand that crashed)."""
    errors = []
    for raw in raw_results or []:
        try:
            on_hand_end(HandResult.from_dict(raw), MEMORY)
        except Exception as exc:
            errors.append(_error_info(exc))
    return errors


@app.get("/")
async def info():
    """Health check: tells the judge who this bot is."""
    return {"participant": PARTICIPANT, "agent_name": AGENT_NAME}


@app.post("/new-half")
async def route_new_half(request: Request):
    """Wipe memory and call your new_half(). The body is {"config": {...}}."""
    body, refused = await _read_request(request, "/new-half")
    if refused:
        return refused
    MEMORY.clear()
    STATUS["started"] = True
    try:
        new_half(AgentConfig.from_dict(body.get("config", {})), MEMORY)
    except Exception as exc:
        return _crash(exc)
    return {"ok": True}


@app.post("/act")
async def route_act(request: Request):
    """Deliver finished hands, then turn the JSON into an Observation, call
    choose_action(), and send the answer back."""
    body, refused = await _read_request(request, "/act")
    if refused:
        return refused
    hand_end_errors = _deliver_results(body.get("hand_results"))
    try:
        obs = Observation.from_dict(body["observation"])
        action = choose_action(obs, MEMORY)
    except Exception as exc:
        return _crash(exc, hand_end_errors)
    # Send the action's name; anything strange is passed on for the judge to reject.
    if isinstance(action, Action):
        answer = action.name
    elif action is None or isinstance(action, (str, int, float, bool)):
        answer = action
    else:
        answer = repr(action)
    return {"action": answer, "hand_end_errors": hand_end_errors}


@app.post("/hand-end")
async def route_hand_end(request: Request):
    """Call on_hand_end() for the last finished hands of a half."""
    body, refused = await _read_request(request, "/hand-end")
    if refused:
        return refused
    return {"ok": True, "hand_end_errors": _deliver_results(body.get("results"))}


if __name__ == "__main__":
    # The tournament sets PORT as an environment variable, so each bot is compliant to our evaluation platform
    # Locally it defaults to 5008 for your own testing convenience
    port = int(os.environ.get("PORT", "5008"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info", access_log=False)
