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
_SWALLOWED = 0


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
    seed = (sum(obs.hole_cards) * 131 + sum((obs.board or [0])) * 17 + obs.pot + samples + obs.hand_index * 997) & 0xFFFFFFFF
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


def _note_opponent(obs: Observation, memory: dict) -> None:
    """Count villain folds, calls, and raise sizes seen so far this half."""
    if memory.get("hand") != obs.hand_index:
        memory["hand"] = obs.hand_index
        memory["counted"] = 0
    stats = memory.setdefault("opp", {"f": 0, "c": 0, "h": 0, "p": 0})
    history = obs.action_history
    for action in history[memory.get("counted", 0):]:
        if action.is_me:
            continue
        if action.action == Action.FOLD:
            stats["f"] += 1
        elif action.action == Action.RAISE_HALF:
            stats["h"] += 1
        elif action.action == Action.RAISE_POT:
            stats["p"] += 1
        else:
            stats["c"] += 1
    memory["counted"] = len(history)


def _model(memory: dict) -> str:
    """Which challenge policy the actions look like. 'mix' until that is clear."""
    stats = memory.get("opp", {"f": 0, "c": 0, "h": 0, "p": 0})
    total = stats["f"] + stats["c"] + stats["h"] + stats["p"]
    if total < 16:
        return "mix"
    raises = stats["h"] + stats["p"]
    fold_rate = stats["f"] / total
    raise_rate = raises / total
    # A tight player folds a lot and rarely raises. Random folds less often.
    if fold_rate >= 0.40 and raise_rate < 0.20:
        return "nit"
    if stats["f"] >= 2:
        return "random"
    if raises >= 8 and raise_rate >= 0.4:
        return "pot" if stats["p"] >= stats["h"] else "half"
    return "station"


def _showdown(stack: int, pot: int, equity: float) -> float:
    return stack + equity * pot


def _stack_off(stack: int, opp_stack: int, pot: int, equity: float) -> float:
    """Hero's stack if both players put the shorter stack in and see showdown."""
    put = min(stack, opp_stack)
    return (stack - put) + equity * (pot + 2 * put)


def _leaf(state, equity: float, model: str) -> float:
    """Value once this street's betting is over.

    A jammer does not check the next street. We either call the all-in or fold
    and keep only the chips still in our stack. A calling station puts the
    rest in when we are ahead and checks it down when we are not.
    """
    pot, hs, vs, _hb, _vb, _raises, _inc, _hero_acted, _vill_acted, street = state
    if hs == 0 or vs == 0 or street >= 3:
        return _showdown(hs, pot, equity)
    # A calling station pays the rest off once we are ahead. A jammer's next
    # bet is not an all-in yet, so the current street's tree prices that bet.
    if model == "station" and equity > 0.5:
        return _stack_off(hs, vs, pot, equity)
    return _showdown(hs, pot, equity)


def _apply(state, actor_is_hero: bool, action: Action):
    """One chip update. Last field is True if the hero folded, False if the villain folded, None otherwise."""
    pot, hs, vs, hb, vb, raises, inc, hero_acted, vill_acted, street = state
    if action == Action.FOLD:
        return pot, hs, vs, hb, vb, raises, inc, hero_acted, vill_acted, street, actor_is_hero
    my_bet, opp_bet, my_stack = (hb, vb, hs) if actor_is_hero else (vb, hb, vs)
    if action == Action.CHECK_CALL:
        amount = min(max(0, opp_bet - my_bet), my_stack)
        new_inc = inc
        new_raises = raises
        opp_acted_reset = False
    else:
        to_call = max(0, opp_bet - my_bet)
        pot_to = opp_bet + pot + to_call
        half_to = opp_bet + (pot + to_call) // 2
        target = half_to if action == Action.RAISE_HALF else pot_to
        new_total = min(max(target, opp_bet + max(inc, 2)), pot_to, my_bet + my_stack)
        amount = new_total - my_bet
        new_inc = new_total - opp_bet
        new_raises = raises + 1
        opp_acted_reset = True
    if actor_is_hero:
        return (pot + amount, hs - amount, vs, hb + amount, vb, new_raises, new_inc,
                True, False if opp_acted_reset else vill_acted, street, None)
    return (pot + amount, hs, vs - amount, hb, vb + amount, new_raises, new_inc,
            False if opp_acted_reset else hero_acted, True, street, None)


def _legal(state, actor_is_hero: bool) -> list:
    pot, hs, vs, hb, vb, raises, inc, hero_acted, vill_acted, street = state
    my_bet, opp_bet, my_stack, opp_stack = (hb, vb, hs, vs) if actor_is_hero else (vb, hb, vs, hs)
    to_call = max(0, opp_bet - my_bet)
    actions = []
    if to_call > 0:
        actions.append(Action.FOLD)
    actions.append(Action.CHECK_CALL)
    if raises < 4 and my_stack > to_call and opp_stack > 0:
        actions.extend((Action.RAISE_HALF, Action.RAISE_POT))
    return actions


def _closed(state) -> bool:
    _pot, hs, vs, hb, vb, _raises, _inc, hero_acted, vill_acted, _street = state
    matched = hb == vb or hs == 0 or vs == 0
    return hero_acted and vill_acted and matched


def _value(state, equity: float, model: str, hero_turn: bool, depth: int, budget: list) -> float:
    """Expected hero stack. An all-in ends the hand; a jammer does not give a free showdown later."""
    budget[0] -= 1
    pot, hs, vs, hb, vb, raises, inc, hero_acted, vill_acted, street = state
    if budget[0] <= 0 or depth > 8 or _closed(state):
        return _leaf(state, equity, model)
    if hero_turn:
        best = None
        for action in _legal(state, True):
            nxt = _apply(state, True, action)
            folded = nxt[-1]
            value = hs if folded else _value(nxt[:-1], equity, model, False, depth + 1, budget)
            if best is None or value > best:
                best = value
        return hs if best is None else best
    choices = _legal(state, False)
    if model == "station":
        choices = [Action.CHECK_CALL]
    elif model == "pot":
        choices = [Action.RAISE_POT] if Action.RAISE_POT in choices else [Action.CHECK_CALL]
    elif model == "half":
        choices = [Action.RAISE_HALF] if Action.RAISE_HALF in choices else [Action.CHECK_CALL]
    elif model == "nit":
        # Continues with a strong-looking hand and folds the rest. No light shoves.
        facing = max(0, hb - vb)
        weights = {Action.FOLD: 0.62, Action.CHECK_CALL: 0.38} if facing > 0 else {
            Action.CHECK_CALL: 0.78,
            Action.RAISE_POT: 0.22,
        }
        choices = [action for action in choices if weights.get(action, 0) > 0]
        total = 0.0
        weight_sum = 0.0
        for action in choices:
            nxt = _apply(state, False, action)
            folded = nxt[-1]
            weight = weights[action]
            weight_sum += weight
            if folded is False:
                total += weight * _showdown(hs, pot, 1.0)
            else:
                total += weight * _value(nxt[:-1], equity, model, True, depth + 1, budget)
        return total / weight_sum
    total = 0.0
    for action in choices:
        nxt = _apply(state, False, action)
        folded = nxt[-1]
        if folded is False:
            total += _showdown(hs, pot + (nxt[0] - pot), 1.0)
        elif model == "random" and depth >= 2:
            total += _showdown(nxt[1], nxt[0], equity)
        else:
            total += _value(nxt[:-1], equity, model, True, depth + 1, budget)
    return total / len(choices)


def _best_action(obs: Observation, equity: float, model: str) -> Action:
    """Pick the legal action with the highest chip value against the challenge model."""
    street_actions = [action for action in obs.action_history if action.street == obs.street]
    state = (
        obs.pot, obs.my_stack, obs.opp_stack, obs.my_bet, obs.opp_bet,
        obs.raises_this_street, max(2, obs.min_raise_to - obs.opp_bet),
        any(action.is_me for action in street_actions),
        any(not action.is_me for action in street_actions),
        int(obs.street),
    )
    models = ("station", "pot", "half", "random", "nit") if model == "mix" else (model,)
    best_action = None
    best_value = None
    for action in obs.legal_actions:
        total = 0.0
        for name in models:
            budget = [2500 if name == "random" else 800]
            nxt = _apply(state, True, action)
            folded = nxt[-1]
            if folded:
                total += obs.my_stack
            else:
                total += _value(nxt[:-1], equity, name, False, 0, budget)
        if action == Action.FOLD:
            invested = 0
        elif action == Action.CHECK_CALL:
            invested = max(0, obs.to_call)
        else:
            invested = max(0, obs.raise_to.get(action, obs.my_bet) - obs.my_bet)
        # Equal chip value: get stacks in while ahead, and keep them out while behind.
        total += (1e-4 if equity >= 0.5 else -1e-4) * invested
        if best_value is None or total > best_value:
            best_value = total
            best_action = action
    return best_action if best_action is not None else _fallback(obs)


def _preflop_shape(obs: Observation) -> Action:
    """Cheap preflop classes. A 12-sample equity read is too noisy to stack off on."""
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


def choose_action(obs: Observation, memory: dict) -> Action:
    started = time.perf_counter()
    try:
        if memory.get("used", 0.0) >= _BUDGET_SECONDS:
            return _fallback(obs)
        _note_opponent(obs, memory)
        all_in = obs.my_stack > 0 and obs.to_call >= obs.my_stack
        # Ordinary preflop bets are priced by hand shape. An all-in is priced
        # by equity, with enough samples that a favorite is not folded by noise.
        if obs.street == Street.PREFLOP and not all_in and obs.to_call <= obs.big_blind * 10:
            return _preflop_shape(obs)
        if obs.street == Street.PREFLOP:
            samples = 12
        elif len(obs.board) == 5:
            samples = _RIVER_SAMPLES
        else:
            samples = _FLOP_SAMPLES
        if all_in and memory.get("used", 0.0) < 5.0:
            samples = max(samples, 48)
        if memory.get("used", 0.0) > 5.5:
            samples = 4
        equity = _equity(obs, samples)
        price = 0.0 if obs.to_call <= 0 else obs.to_call / (obs.pot + obs.to_call)
        if abs(equity - price) < 0.06 and memory.get("used", 0.0) < 4.0 and samples >= 12:
            equity = _equity(obs, samples + 24)
        return _best_action(obs, equity, _model(memory))
    except Exception:
        global _SWALLOWED
        _SWALLOWED += 1
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
