"""In-process deal stress test. A failure is an exception, an illegal action, or a stuck hand."""

from __future__ import annotations

import math
import os
import random
import sys
import time

from itertools import combinations

from game import Action, Deal, Game, IllegalActionError, make_deal
from evaluator import omaha_score

import agent


def _random(obs, _memory):
    return random.choice(obs.legal_actions)


def _call(obs, _memory):
    return Action.CHECK_CALL if Action.CHECK_CALL in obs.legal_actions else obs.legal_actions[0]


def _pot(obs, _memory):
    if Action.RAISE_POT in obs.legal_actions:
        return Action.RAISE_POT
    return _call(obs, _memory)


def _half(obs, _memory):
    if Action.RAISE_HALF in obs.legal_actions:
        return Action.RAISE_HALF
    return _call(obs, _memory)


POLICIES = {"self": agent.choose_action, "random": _random, "call": _call, "pot": _pot, "half": _half}


def play_hand(deal, button, policy, memory, opp, hero: int = 0, opp_memory: dict | None = None) -> tuple[int, str]:
    game = Game(deal, button_seat=button)
    boxes = {hero: memory, 1 - hero: {} if opp_memory is None else opp_memory}
    steps = 0
    while not game.is_terminal:
        steps += 1
        if steps > 48:
            return 0, "stuck"
        obs = game.observation(game.to_act)
        actor = policy if game.to_act == hero else opp
        box = boxes[game.to_act]
        try:
            action = actor(obs, box)
        except Exception as exc:
            return 0, f"raise:{type(exc).__name__}"
        if action not in obs.legal_actions:
            return 0, f"illegal:{action}"
        try:
            game.apply(action)
        except IllegalActionError as exc:
            return 0, f"apply:{exc}"
    return game.result().nets[hero], ""


def run(hands: int, seed: int, opponent: str) -> dict:
    policy = agent.choose_action
    opp = POLICIES[opponent]
    memory: dict = {}
    agent.new_half(None, memory)
    before = agent._SWALLOWED
    fails = []
    nets = []
    started = time.perf_counter()
    for index in range(hands):
        deal = make_deal(seed, index)
        for button in (0, 1):
            net, reason = play_hand(deal, button, policy, memory, opp)
            if reason:
                fails.append({"deal": index, "button": button, "reason": reason})
                if len(fails) >= 5:
                    break
            else:
                nets.append(net)
        if len(fails) >= 5:
            break
        if index and index % 80 == 0:
            agent.new_half(None, memory)
    elapsed = time.perf_counter() - started
    return {
        "hands_ok": len(nets),
        "fails": fails,
        "swallowed": agent._SWALLOWED - before,
        "mean_net": (sum(nets) / len(nets)) if nets else None,
        "seconds": round(elapsed, 3),
        "seed": seed,
        "opponent": opponent,
    }


def match_bb(deals: int, seed: int, opponent: str) -> dict:
    """Official pairing: half 1 hero is seat 0, half 2 hero is seat 1, same deals."""
    opp = POLICIES[opponent]
    by_half: list[list[int]] = []
    fails = 0
    used = []
    for hero in (0, 1):
        memory: dict = {}
        opp_memory: dict = {}
        agent.new_half(None, memory)
        if opponent == "self":
            agent.new_half(None, opp_memory)
        nets: list[int] = []
        for index in range(deals):
            deal = make_deal(seed, index)
            net, reason = play_hand(
                deal, index % 2, agent.choose_action, memory, opp, hero=hero,
                opp_memory=opp_memory if opponent == "self" else None,
            )
            if reason:
                fails += 1
                break
            nets.append(net)
        used.append(round(memory.get("used", 0.0), 3))
        by_half.append(nets)
        if fails:
            break
    n = min(len(half) for half in by_half) if by_half else 0
    paired = [(by_half[0][i] + by_half[1][i]) / 2 for i in range(n)] if n and not fails else []
    halves = paired
    n = len(halves)
    mean = sum(halves) / n if n else 0.0
    var = sum((x - mean) ** 2 for x in halves) / max(1, n - 1) if n else 0.0
    stderr = math.sqrt(var / n) if n else 0.0
    lo, hi = mean - 1.96 * stderr, mean + 1.96 * stderr
    if fails:
        verdict = "FAIL"
    elif hi < 0:
        verdict = "LOSS"
    elif lo > 0:
        verdict = "WIN"
    else:
        verdict = "CHOP"
    return {
        "seed": seed, "opponent": opponent, "deals": n, "bb": round(mean, 3),
        "lo": round(lo, 3), "hi": round(hi, 3), "verdict": verdict,
        "fails": fails, "thinking_s": used,
    }


def exhaustive_preflop(shard: int, shards: int) -> dict:
    """Every 5-card holding, both button seats, real preflop action must be legal."""
    checked = illegal = 0
    before = agent._SWALLOWED
    for hole in combinations(range(36), 5):
        if hole[0] % shards != shard:
            continue
        rest = [card for card in range(36) if card not in hole]
        deal = Deal(hole_cards=(hole, tuple(rest[:5])), board=tuple(rest[5:10]))
        for button in (0, 1):
            game = Game(deal, button_seat=button)
            guard = 0
            while not game.is_terminal and game.to_act != 0:
                obs = game.observation(game.to_act)
                game.apply(_call(obs, {}))
                guard += 1
                if guard > 8:
                    illegal += 1
                    break
            if game.is_terminal or game.to_act != 0:
                continue
            obs = game.observation(0)
            action = agent.choose_action(obs, {"used": 0.0})
            checked += 1
            if action not in obs.legal_actions:
                illegal += 1
    return {
        "shard": shard,
        "checked": checked,
        "illegal": illegal,
        "swallowed": agent._SWALLOWED - before,
    }


def deck_probe(count: int, seed: int) -> dict:
    """Distinct 15-card deals plus both Omaha scores. No bot, so this can run far."""
    bad = 0
    started = time.perf_counter()
    for index in range(count):
        deal = make_deal(seed, index)
        cards = deal.hole_cards[0] + deal.hole_cards[1] + deal.board
        if len(cards) != 15 or len(set(cards)) != 15:
            bad += 1
            continue
        try:
            omaha_score(deal.hole_cards[0], deal.board)
            omaha_score(deal.hole_cards[1], deal.board)
        except Exception:
            bad += 1
    elapsed = time.perf_counter() - started
    return {"seed": seed, "deals": count, "bad": bad, "seconds": round(elapsed, 3)}


if __name__ == "__main__":
    mode = sys.argv[1]
    if mode == "hands":
        print(run(int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]))
    elif mode == "match":
        print(match_bb(int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]))
    elif mode == "preflop":
        print(exhaustive_preflop(int(sys.argv[2]), int(sys.argv[3])))
    elif mode == "decks":
        print(deck_probe(int(sys.argv[2]), int(sys.argv[3])))
    else:
        raise SystemExit("hands|match|preflop|decks")
