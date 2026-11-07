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

_BUDGET_SECONDS = 6.5
_FLOP_SAMPLES = 28
_RIVER_SAMPLES = 64


def new_half(config: AgentConfig, memory: dict) -> None:
    memory["used"] = 0.0


def _fallback(obs: Observation) -> Action:
    if obs.to_call == 0 and Action.CHECK_CALL in obs.legal_actions:
        return Action.CHECK_CALL
    if Action.FOLD in obs.legal_actions:
        return Action.FOLD
    return obs.legal_actions[0]


def _shape(cards):
    ranks = [card_rank(card) for card in cards]
    suits = [card_suit(card) for card in cards]
    pairs = sum(1 for rank in set(ranks) if ranks.count(rank) >= 2)
    trips = any(ranks.count(rank) >= 3 for rank in set(ranks))
    suited = max(suits.count(suit) for suit in set(suits))
    high = sum(1 for rank in ranks if rank >= 6)
    return pairs, trips, suited, high


def _equity(obs: Observation, samples: int) -> float:
    known = set(obs.hole_cards) | set(obs.board)
    deck = [card for card in range(36) if card not in known]
    need_board = 5 - len(obs.board)
    seed = (sum(obs.hole_cards) * 131 + sum((obs.board or [0])) * 17 + obs.pot + samples) & 0xFFFFFFFF
    rng = random.Random(seed)
    wins = ties = 0
    for _ in range(samples):
        draw = rng.sample(deck, need_board + 5)
        board = list(obs.board) + draw[:need_board]
        opponent = draw[need_board:]
        mine = omaha_score(obs.hole_cards, board)
        theirs = omaha_score(opponent, board)
        if mine > theirs:
            wins += 1
        elif mine == theirs:
            ties += 1
    return (wins + 0.5 * ties) / samples


def _price(obs: Observation) -> float:
    if obs.to_call <= 0:
        return 0.0
    return obs.to_call / (obs.pot + obs.to_call)


def choose_action(obs: Observation, memory: dict) -> Action:
    started = time.perf_counter()
    try:
        if memory.get("used", 0.0) >= _BUDGET_SECONDS:
            return _fallback(obs)
        if obs.street == Street.PREFLOP:
            pairs, trips, suited, high = _shape(obs.hole_cards)
            strong = trips or pairs >= 2 or suited >= 4 or (pairs and suited >= 3) or (high >= 3 and suited >= 2 and pairs)
            playable = pairs or suited >= 3 or high >= 3 or trips
            if obs.to_call == 0:
                if strong and Action.RAISE_POT in obs.legal_actions:
                    return Action.RAISE_POT
                return Action.CHECK_CALL
            if strong and obs.to_call <= obs.big_blind * 8 and Action.RAISE_POT in obs.legal_actions:
                return Action.RAISE_POT
            if playable and Action.CHECK_CALL in obs.legal_actions:
                return Action.CHECK_CALL
            return _fallback(obs)
        samples = _RIVER_SAMPLES if len(obs.board) == 5 else _FLOP_SAMPLES
        if memory.get("used", 0.0) > 5.5:
            samples = 6
        equity = _equity(obs, samples)
        price = _price(obs)
        if abs(equity - price) < 0.08 and memory.get("used", 0.0) < 4.0:
            equity = _equity(obs, samples + 32)
        if equity >= 0.66 and Action.RAISE_POT in obs.legal_actions and obs.raises_this_street < 3:
            if obs.to_call == 0 or equity >= price + 0.10:
                return Action.RAISE_POT
        if obs.to_call == 0 and equity >= 0.54 and Action.RAISE_HALF in obs.legal_actions and obs.raises_this_street < 2:
            return Action.RAISE_HALF
        if equity >= price and Action.CHECK_CALL in obs.legal_actions:
            return Action.CHECK_CALL
        return _fallback(obs)
    except Exception:
        return _fallback(obs)
    finally:
        memory["used"] = memory.get("used", 0.0) + (time.perf_counter() - started)


def on_hand_end(result: HandResult, memory: dict) -> None:
    return None

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
