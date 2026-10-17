#!/usr/bin/env python3
"""
Optional Auto-Switch & Auto-Resume Daemon for Codex Account Center.
Monitors remaining 5-hour / weekly limits for Codex.
When remaining quota drops to <= threshold (default 2%), automatically switches to the
best available saved account, restarts the app, and resumes any active/interrupted task.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import runpy
import tempfile
import time

SWITCHER_PATH = Path.home() / ".local" / "bin" / "codex-acc"


def load_switcher_mod() -> dict:
    return runpy.run_path(str(SWITCHER_PATH), run_name="codex_acc_companion")


def emit(event: str, **details):
    payload = {
        "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
        "event": event,
        **{key: value for key, value in details.items() if key not in {"account", "aktif", "mevcut", "hedef", "eski", "yeni", "title", "baslik", "thread_id", "thread_ids"}},
    }
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def codex_candidate_score(lim: dict, threshold: float) -> float | None:
    if not lim or not lim.get("ok"):
        return None
    if not lim.get("allowed", False) or lim.get("limit_reached", False):
        return None
    rem_5h = float(lim.get("rem_5h", 0))
    rem_wk = float(lim.get("rem_weekly", 0))
    effective = min(rem_5h, rem_wk)
    if effective <= threshold:
        return None
    # Prefer higher 5h & weekly remaining
    return effective + (rem_wk * 0.001)




def check_codex(mod: dict, cfg: dict, apply: bool, allow_restart: bool, last_switch: float) -> float:
    threshold = float(cfg.get("codex_threshold", 2))
    cooldown = float(cfg.get("cooldown", 90))
    auto_resume = bool(cfg.get("codex_auto_resume", True))

    accounts, active = mod["list_accounts"]()
    if not accounts:
        return last_switch
    active_acc = next((a for a in accounts if a.get("is_active")), accounts[0])
    others = [a for a in accounts if a["id_key"] != active_acc["id_key"]]

    lim = mod["fetch_account_limits"](active_acc)
    if not lim.get("ok"):
        emit("codex_usage_unavailable", account=active_acc["email"], error=lim.get("error"))
        return last_switch

    rem_5h = lim.get("rem_5h", 100)
    rem_wk = lim.get("rem_weekly", 100)
    min_rem = min(rem_5h, rem_wk)

    # A rate-limited chat can coexist with several still-running chats.
    active_threads = mod["get_active_or_interrupted_codex_threads"](max_age_seconds=1800)
    recent_rl_abort = any(
        thread.get("is_rate_limit") and time.time() - (thread.get("last_turn_ts") or 0) <= 120
        for thread in active_threads
    )

    needs_sw = (
        lim.get("limit_reached", False)
        or not lim.get("allowed", True)
        or min_rem <= threshold
        or recent_rl_abort
    )

    if not needs_sw:
        emit(
            "codex_ok",
            aktif=active_acc["email"],
            remaining_5h=f"%{rem_5h}",
            remaining_weekly=f"%{rem_wk}",
            threshold=f"%{int(threshold)}",
        )
        return last_switch

    if time.monotonic() - last_switch < cooldown:
        emit("codex_cooldown", aktif=active_acc["email"])
        return last_switch

    if not others:
        emit("codex_no_other_accounts", aktif=active_acc["email"])
        return last_switch

    snapshots = mod["fetch_all_limits_parallel"](others)
    scored = []
    for cand in others:
        sc = codex_candidate_score(snapshots.get(cand["id_key"]), threshold)
        if sc is not None:
            scored.append((sc, cand, snapshots[cand["id_key"]]))

    if not scored:
        emit("codex_no_eligible_account", accounts_checked=len(others))
        return last_switch

    scored.sort(key=lambda x: x[0], reverse=True)
    _, best_acc, best_lim = scored[0]

    if not apply:
        emit(
            "codex_switch_proposed",
            mevcut=active_acc["email"],
            hedef=best_acc["email"],
            target_5h=f"%{best_lim.get('rem_5h')}",
            target_weekly=f"%{best_lim.get('rem_weekly')}",
        )
        return last_switch

    running = mod["is_chatgpt_app_running"]()
    if running and not allow_restart:
        emit("codex_restart_not_allowed")
        return last_switch

    # Capture ALL unfinished chats before the restart changes their statuses.
    # Completed chats are deliberately excluded from automatic continuation.
    threads_to_resume = mod["get_active_or_interrupted_codex_threads"](max_age_seconds=3600)
    emit("codex_resume_snapshot", chat_count=len(threads_to_resume),
         thread_ids=[t["thread_id"] for t in threads_to_resume])

    emit(
        "codex_switch_started",
        eski=active_acc["email"],
        yeni=best_acc["email"],
        previous_5h=f"%{rem_5h}",
        next_5h=f"%{best_lim.get('rem_5h')}",
    )
    try:
        launch = mod["switch_to_account"](best_acc, restart_app=running, start_app_if_closed=running)
    except Exception as exc:
        emit("codex_launch_unconfirmed", error=str(exc))
        return time.monotonic()
    emit("codex_switch_completed", app_ready=bool(launch.get("app_ready")))

    if auto_resume and running and launch.get("app_ready") and threads_to_resume:
        results = mod["resume_codex_threads"](
            threads_to_resume, prompt=cfg.get("resume_prompt"), wait_for_app_seconds=18.0,
        )
        for result in results:
            emit("codex_resume_result", **result)
        emit("codex_batch_resume_result", total=len(results),
             successful=sum(bool(result.get("ok")) for result in results))

    return time.monotonic()




def main():
    parser = argparse.ArgumentParser(description="Codex account switching and continuation monitor")
    parser.add_argument("--watch", action="store_true", help="Monitor continuously; default is one check")
    parser.add_argument("--apply", action="store_true", help="Apply account switches and continuation")
    parser.add_argument("--allow-restart", action="store_true", help="Allow restarting the desktop app")
    parser.add_argument("--threshold", type=float, default=None, help="Default remaining percentage threshold")
    parser.add_argument("--reserve", type=float, default=None, help="Legacy compatibility option")
    parser.add_argument("--interval", type=int, default=None)
    parser.add_argument("--cooldown", type=int, default=None)
    args = parser.parse_args()

    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", tempfile.gettempdir()))
    lock = runtime / f"codex-auto-switch-{os.getuid()}.lock"

    with ExitStack() as stack:
        if args.apply and args.watch:
            fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            handle = stack.enter_context(os.fdopen(fd, "w"))
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                parser.exit(1, "Another automatic switch monitor is already running.\n")

        last_codex_sw = -float("inf")

        try:
            while True:
                mod = load_switcher_mod()
                cfg = mod["get_auto_config"]()
                if args.threshold is not None and "codex_threshold" not in (mod["load_meta"]().get("auto_switch_config") or {}):
                    cfg["codex_threshold"] = args.threshold
                if args.interval is not None and "check_interval" not in (mod["load_meta"]().get("auto_switch_config") or {}):
                    cfg["check_interval"] = args.interval
                if args.cooldown is not None and "cooldown" not in (mod["load_meta"]().get("auto_switch_config") or {}):
                    cfg["cooldown"] = args.cooldown

                if cfg.get("codex_auto_switch", True):
                    try:
                        last_codex_sw = check_codex(mod, cfg, args.apply, args.allow_restart, last_codex_sw)
                    except Exception as e:
                        emit("codex_check_failed", error=str(e))


                if not args.watch:
                    break
                sleep_secs = max(15, int(cfg.get("check_interval", 30)))
                time.sleep(sleep_secs)
        except KeyboardInterrupt:
            emit("monitor_stopped")


if __name__ == "__main__":
    main()
