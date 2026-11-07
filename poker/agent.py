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
from itertools import combinations, combinations_with_replacement

import numpy as np

from evaluator import card_rank, card_suit, cards_to_str, omaha_score, warmup, _score_ranks  # handy helpers, see evaluator.py
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


# Rank-multiset key: sum(5**rank). A 5-card non-flush score depends only on
# that multiset, so many hands are scored with one table lookup.
_KEY_SIZE = 5 ** 9
_NONFLUSH = np.zeros(_KEY_SIZE, dtype=np.int32)
_FLUSH = np.zeros(_KEY_SIZE, dtype=np.int32)
for _ranks in combinations_with_replacement(range(9), 5):
    if max(_ranks.count(rank) for rank in set(_ranks)) > 4:
        continue
    _key = sum(5 ** rank for rank in _ranks)
    _desc = tuple(sorted(_ranks, reverse=True))
    _NONFLUSH[_key] = _score_ranks(_desc, False)
    if len(set(_ranks)) == 5:
        _FLUSH[_key] = _score_ranks(_desc, True)

_CARD_KEY = np.array([5 ** (card >> 2) for card in range(36)], dtype=np.int32)
_CARD_SUIT = np.array([card & 3 for card in range(36)], dtype=np.int8)
_PAIRS_IX = np.array(list(combinations(range(5), 2)), dtype=np.intp)
_TRIPS_IX = np.array(list(combinations(range(5), 3)), dtype=np.intp)
_TRIPS4_IX = np.array(list(combinations(range(4), 3)), dtype=np.intp)
_RAISE_EQ = (0.56, 0.64, 0.68, 0.72)
_BET_HALF = (0.50, 0.51, 0.52, 0.54)
_BET_POT = (0.55, 0.60, 0.63, 0.66)
_CALL_MARGIN = (0.00, 0.03, 0.03, 0.02)


def _pair_parts(hole: np.ndarray):
    keys = _CARD_KEY[hole]
    suits = _CARD_SUIT[hole].astype(np.int16)
    left, right = _PAIRS_IX[:, 0], _PAIRS_IX[:, 1]
    pair_key = keys[:, left] + keys[:, right]
    pair_suit = np.where(suits[:, left] == suits[:, right], suits[:, left], -1)
    return pair_key, pair_suit


def _triple_parts(board: np.ndarray, triples: np.ndarray):
    keys = _CARD_KEY[board]
    suits = _CARD_SUIT[board].astype(np.int16)
    a, b, c = triples[:, 0], triples[:, 1], triples[:, 2]
    triple_key = keys[:, a] + keys[:, b] + keys[:, c]
    same = (suits[:, a] == suits[:, b]) & (suits[:, b] == suits[:, c])
    triple_suit = np.where(same, suits[:, a], -2)
    return triple_key, triple_suit


def _combine(pair_key, pair_suit, triple_key, triple_suit) -> np.ndarray:
    key = pair_key[:, :, None] + triple_key[:, None, :]
    flush = pair_suit[:, :, None] == triple_suit[:, None, :]
    scores = np.where(flush, _FLUSH[key], _NONFLUSH[key])
    return scores.reshape(scores.shape[0], -1).max(axis=1)


def _omaha_scores(hole: np.ndarray, board: np.ndarray) -> np.ndarray:
    pair_key, pair_suit = _pair_parts(hole)
    triple_key, triple_suit = _triple_parts(board, _TRIPS_IX)
    return _combine(pair_key, pair_suit, triple_key, triple_suit)


def _partial_scores(hole: np.ndarray, board: np.ndarray) -> np.ndarray:
    pair_key, pair_suit = _pair_parts(hole)
    width = board.shape[1]
    triples = _TRIPS_IX if width >= 5 else (_TRIPS4_IX if width == 4 else np.array([[0, 1, 2]], dtype=np.intp))
    triple_key, triple_suit = _triple_parts(board, triples)
    return _combine(pair_key, pair_suit, triple_key, triple_suit)


def _pct(values: np.ndarray) -> np.ndarray:
    """Percentile rank from 0 to 1. Tied values share one average rank."""
    count = int(values.shape[0])
    if count <= 1:
        return np.zeros(count, dtype=np.float64)
    order = np.argsort(values, kind="mergesort")
    ordered = values[order]
    ranks = np.empty(count, dtype=np.float64)
    start = 0
    while start < count:
        end = start + 1
        while end < count and ordered[end] == ordered[start]:
            end += 1
        ranks[order[start:end]] = (start + end - 1) / 2.0
        start = end
    return ranks / (count - 1)


def _preflop_strength(hands: np.ndarray) -> np.ndarray:
    """Rank hole cards by a short equity rollout against a random hand.

    Four runouts is enough to separate the hands a raiser keeps from the
    hands a raiser folds. The rank is only used as a weight, not as the
    decision equity.
    """
    count = hands.shape[0]
    wins = np.zeros(count, dtype=np.float64)
    rng = np.random.default_rng(1)
    rows = np.arange(count)
    for _ in range(4):
        noise = rng.random((count, 36))
        for column in range(5):
            noise[rows, hands[:, column]] = -1.0
        picked = np.argpartition(noise, -10, axis=1)[:, -10:]
        board = picked[:, :5]
        other = picked[:, 5:]
        mine = _omaha_scores(hands, board)
        theirs = _omaha_scores(other, board)
        wins += (mine > theirs) + 0.5 * (mine == theirs)
    return wins


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


def _range_equity(obs: Observation, samples: int, q_pre: float, q_post: float, cap: float) -> float:
    """Equity against the part of the sample the opponent still holds.

    q_pre and q_post are the fraction of hands they continue with. cap is the
    top of that range when they have checked this street. Hands outside the
    window keep a small weight, so a bluff or a slowplay is not equity zero.
    """
    hole = list(obs.hole_cards)
    board = list(obs.board)
    known = set(hole) | set(board)
    rest = np.array([card for card in range(36) if card not in known], dtype=np.intp)
    need = 5 + (5 - len(board))
    seed = (obs.hand_index * 7919 + len(obs.action_history) * 104729 + sum(hole) * 31 + int(obs.street)) & 0xFFFFFFFF
    draw = np.random.default_rng(seed).permuted(np.tile(rest, (samples, 1)), axis=1)[:, :need]
    opponent = draw[:, :5]
    width = len(board)
    if width:
        full = np.concatenate(
            [np.broadcast_to(np.array(board, dtype=np.intp), (samples, width)), draw[:, 5:]],
            axis=1,
        )
    else:
        full = draw[:, 5:]
    mine = np.broadcast_to(np.array(hole, dtype=np.intp), (samples, 5))
    if width == 5:
        my_score = _omaha_scores(mine[:1], full[:1])[0]
    else:
        my_score = _omaha_scores(mine, full)
    opp_score = _omaha_scores(opponent, full)
    win = (my_score > opp_score) + 0.5 * (my_score == opp_score)
    # Hands outside the continuing range still show up as draws and bluffs.
    # A tighter leftover weight made every raise look like the nuts.
    leftover = (0.12, 0.18, 0.12, 0.06)[min(3, int(obs.street))]
    weight = np.ones(samples, dtype=np.float64)
    if q_pre < 0.999:
        rank = _pct(_preflop_strength(opponent))
        weight *= np.where(rank >= 1.0 - q_pre, 1.0, leftover)
    if width >= 3 and (q_post < 0.999 or cap < 0.999):
        current = _partial_scores(opponent, np.broadcast_to(np.array(board, dtype=np.intp), (samples, width)))
        strength = _pct(opp_score) if width == 5 else 0.6 * _pct(current) + 0.4 * _pct(opp_score)
        ranked = _pct(strength)
        if q_post < 0.999:
            weight *= np.where(ranked >= 1.0 - q_post, 1.0, leftover)
        if cap < 0.999:
            weight *= np.where(ranked <= cap, 1.0, 0.15)
    return float((weight * win).sum() / weight.sum())


def _continue_fraction(obs: Observation, memory: dict) -> tuple[float, float, float]:
    """How much of a random hand the opponent still has after the raises we saw."""
    raised = [0, 0, 0, 0]
    for action in obs.action_history:
        if action.is_me or int(action.action) < int(Action.RAISE_HALF):
            continue
        raised[min(3, int(action.street))] += 1
    stats = memory.get("opp", {"f": 0, "c": 0, "h": 0, "p": 0})
    seen = stats["f"] + stats["c"] + stats["h"] + stats["p"]
    freq = (stats["h"] + stats["p"] + 0.30 * 12.0) / (seen + 12.0)
    street = min(3, int(obs.street))
    q_pre = 1.0
    if raised[0]:
        q_pre = max(0.12, freq ** (1.0 + 0.5 * (raised[0] - 1)))
    q_post = 1.0
    for street_index in range(1, street + 1):
        if raised[street_index]:
            q_post *= max(0.12, freq ** (1.0 + 0.5 * (raised[street_index] - 1)))
    if q_post < 1.0:
        q_post = max(0.12, q_post)
    # A check stands for the hands they chose not to bet. Leave a little
    # weight on the top, because a strong hand does sometimes check.
    cap = 1.0
    if street >= 1 and raised[street] == 0:
        for action in obs.action_history:
            if action.is_me or int(action.street) != street:
                continue
            if int(action.action) == int(Action.CHECK_CALL) and action.amount == 0:
                cap = 0.62
                break
    return q_pre, q_post, cap


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
    """Name the opponent only after the counts separate a pure baseline.

    A player who has folded twice is not a random actor. The public field
    folds weak hands and continues with equity, so that is the prior.
    """
    stats = memory.get("opp", {"f": 0, "c": 0, "h": 0, "p": 0})
    total = stats["f"] + stats["c"] + stats["h"] + stats["p"]
    if total < 24:
        return "reg"
    fold_rate = stats["f"] / total
    raise_rate = (stats["h"] + stats["p"]) / total
    if fold_rate >= 0.42 and raise_rate < 0.18:
        return "nit"
    if raise_rate >= 0.50 and fold_rate < 0.12:
        return "pot" if stats["p"] >= stats["h"] else "half"
    if fold_rate <= 0.10 and raise_rate < 0.22:
        return "station"
    return "reg"


def _reg_action(obs: Observation, equity: float, memory: dict) -> Action:
    """Bet when ahead of a continuing range. Call when equity clears the price."""
    street = min(3, int(obs.street))
    stats = memory.get("opp", {"f": 0, "c": 0, "h": 0, "p": 0})
    seen = stats["f"] + stats["c"] + stats["h"] + stats["p"]
    raise_rate = (stats["h"] + stats["p"] + 0.30 * 12.0) / (seen + 12.0)
    raise_at = _RAISE_EQ[street] + (0.10 if raise_rate > 0.55 else 0.0)
    legal = obs.legal_actions
    if obs.to_call > 0:
        price = obs.to_call / (obs.pot + obs.to_call)
        if equity >= raise_at and Action.RAISE_POT in legal:
            return Action.RAISE_POT
        if equity >= price + _CALL_MARGIN[street] and Action.CHECK_CALL in legal:
            return Action.CHECK_CALL
        if Action.FOLD in legal:
            return Action.FOLD
        return _fallback(obs)
    if equity >= _BET_POT[street] and Action.RAISE_POT in legal:
        return Action.RAISE_POT
    if equity >= _BET_HALF[street] and Action.RAISE_HALF in legal:
        return Action.RAISE_HALF
    if Action.CHECK_CALL in legal:
        return Action.CHECK_CALL
    return _fallback(obs)


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
        model = _model(memory)
        all_in = obs.my_stack > 0 and obs.to_call >= obs.my_stack
        # Pure baselines still get the chip-value tree. Everyone else is
        # priced by equity against a continuing range.
        if model != "reg" and obs.street == Street.PREFLOP and not all_in and obs.to_call <= obs.big_blind * 10:
            return _preflop_shape(obs)
        if model == "reg":
            samples = 160 if memory.get("used", 0.0) > 4.5 else 480
        elif obs.street == Street.PREFLOP:
            samples = 12
        elif len(obs.board) == 5:
            samples = _RIVER_SAMPLES
        else:
            samples = _FLOP_SAMPLES
        if all_in and memory.get("used", 0.0) < 5.0:
            samples = max(samples, 48)
        if memory.get("used", 0.0) > 5.5:
            samples = 4
        if model == "reg":
            q_pre, q_post, cap = _continue_fraction(obs, memory)
            equity = _range_equity(obs, samples, q_pre, q_post, cap)
            return _reg_action(obs, equity, memory)
        equity = _equity(obs, samples)
        return _best_action(obs, equity, model)
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
