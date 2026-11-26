"""Subscription-aware routing for local agent CLIs."""
import json
import math
import os
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from threading import Timer
from zoneinfo import ZoneInfo

LEVELS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
TIERS = ("light", "general", "advanced")


def task_tier(text):
    if re.search(r"recovery|rollback|concurren|locking|state transitions?|복구|동시성|상태 전이|잠금", text, re.I):
        return "advanced"
    # Only lower the starting model when every requested action is document work.
    actions = [part.strip(" #-*.\t") for part in re.split(
        r"[\n;!?]+|\.(?:\s+|$)|\band\b|하고\s+|하며\s+", text, flags=re.I) if part.strip(" #-*.\t")]
    document_action = (
        r"(?:update|edit|revise|write)\s+(?:the\s+)?(?:api\s+)?(?:docs?\b|documentation\b|readme\b)"
        r"|(?:reflect|copy|record)\b.*\b(?:in|into|to)\s+(?:the\s+)?(?:docs?|documentation|readme)\b"
        r"|(?:document|describe)\s+"
        r"|.*(?:문서|README)(?:에|를|을|의|로|만|\s).*?(?:반영|옮|기록|정리|갱신|수정|설명|작성)"
    )
    if actions and all(re.match(document_action, action, re.I) for action in actions):
        return "light"
    return "general"


@dataclass(frozen=True)
class Candidate:
    agent: str
    model: str
    effort: str
    remaining: float
    observed: float
    resets: tuple


def effort_for(tier, levels, raised=False):
    if not levels:
        if raised:
            raise ValueError("model uses default effort")
        return "default"
    minimum = LEVELS.index({"light": "none", "general": "low", "advanced": "medium"}[tier])
    options = [level for level in LEVELS[minimum:] if level in levels]
    if not options or raised and len(options) == 1:
        raise ValueError("required reasoning effort unavailable")
    return options[int(raised)]


def reset_time(value, now):
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo:
            return stamp.timestamp()
    except ValueError:
        pass
    match = re.fullmatch(r"(.+?)(?:\s*\(([^()]+)\))?", value)
    if not match:
        raise ValueError("invalid reset")
    date, zone = match.groups()
    local = datetime.fromtimestamp(now).astimezone()
    if zone and zone != local.tzname():
        fixed = {"UTC": timezone.utc, "Asia/Seoul": timezone(timedelta(hours=9))}
        local = local.astimezone(fixed.get(zone) or ZoneInfo(zone))
    for fmt in ("%I%p", "%I:%M%p", "%H:%M", "%b %d, %I%p", "%b %d at %I%p",
                "%b %d, %I:%M%p", "%b %d at %I:%M%p"):
        try:
            parsed = datetime.strptime(f"{date.strip()} 2000", fmt + " %Y")
        except ValueError:
            continue
        stamp = local.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
        if "%b" in fmt:
            stamp = stamp.replace(month=parsed.month, day=parsed.day)
            if stamp.timestamp() <= now:
                stamp = stamp.replace(year=stamp.year + 1)
        elif stamp.timestamp() <= now:
            stamp += timedelta(days=1)
        return stamp.timestamp()
    raise ValueError("unrecognized reset time")


def claude_windows(output, alias, now):
    body = re.sub(r"\x1b\[[0-9;]*m", "", output).split("What's contributing to your usage?", 1)[0]
    sections = re.split(r"(?im)^\s*(Current session|Current week\s*\([^()\n]+\))\s*:?[ \t]*", body)
    found = {}
    for heading, content in zip(sections[1::2], sections[2::2]):
        heading = heading.lower()
        if heading not in ("current session", "current week (all models)") and alias not in heading:
            continue
        used = re.findall(r"(?<![\w.])(-?\d+(?:\.\d+)?)%\s*used\b", content, re.I)
        reset = re.findall(r"(?im)\bresets\s+(?:at\s+)?([^\n\r]+)", content)
        if heading in found or len(used) != 1 or len(reset) != 1:
            raise ValueError("ambiguous Claude usage")
        percent = float(used[0])
        if not 0 <= percent <= 100:
            raise ValueError("invalid Claude usage percentage")
        found[heading] = percent, reset_time(reset[0].strip(), now)
    if not {"current session", "current week (all models)"} <= found.keys():
        raise ValueError("missing Claude usage window")
    return list(found.values())


def codex_inventory(executable, cwd, env, timeout):
    # App Server requires a completed initialize handshake before subsequent requests.
    with subprocess.Popen([executable, "app-server"], cwd=cwd, env=env, stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, encoding="utf-8") as proc:
        def stop():
            if proc.poll() is not None:
                return
            # On Windows the executable can be the npm .cmd launcher. Its children own the pipes.
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                proc.kill()

        timer = Timer(timeout, stop)
        timer.start()

        def send(message):
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()

        def request(number, method, params):
            send({"id": number, "method": method, "params": params})
            for line in proc.stdout:
                response = json.loads(line)
                if response.get("id") == number:
                    if "result" not in response:
                        raise ValueError(f"{method} unavailable")
                    return response["result"]
            raise ValueError("Codex App Server stopped or timed out")
        try:
            request(1, "initialize", {"clientInfo": {"name": "harness", "version": "1"}})
            send({"method": "initialized"})
            account = request(2, "account/read", {})
            if (account.get("account") or {}).get("type") not in ("chatgpt", "chatgptAuthTokens"):
                raise ValueError("ChatGPT login required")
            limits = request(3, "account/rateLimits/read", {})
            models = []
            cursor = None
            while True:
                page = request(4, "model/list", {"cursor": cursor})
                models.extend(page["data"])
                cursor = page.get("nextCursor")
                if not cursor:
                    return models, limits
        finally:
            proc.stdin.close()
            try:
                proc.wait(timeout=1)
            except subprocess.TimeoutExpired:
                stop()
            finally:
                timer.cancel()


def claude_models(executable, cwd, env, timeout):
    status = subprocess.run([executable, "auth", "status", "--json"], cwd=cwd, env=env,
                            capture_output=True, encoding="utf-8", check=True, timeout=timeout)
    auth = json.loads(status.stdout)
    if not auth.get("loggedIn") or auth.get("authMethod") != "claude.ai":
        raise ValueError("Claude subscription login required")
    request = {"type": "control_request", "request_id": "models",
               "request": {"subtype": "initialize"}}
    output = subprocess.run([executable, "-p", "--input-format", "stream-json", "--output-format",
                             "stream-json", "--verbose"], cwd=cwd, env=env, capture_output=True,
                            input=json.dumps(request) + "\n", encoding="utf-8", check=True, timeout=timeout)
    for line in output.stdout.splitlines():
        message = json.loads(line)
        response = message.get("response", {})
        if message.get("type") == "control_response" and response.get("request_id") == "models":
            return response["response"]["models"]
    raise ValueError("Claude subscription model inventory unavailable")


def codex_windows(limits, model):
    buckets = limits.get("rateLimitsByLimitId") or {}
    key = model.get("limitId") or model["model"]
    if key in buckets:
        applicable = [buckets[key]]
        if key != "codex" and "codex" in buckets:
            applicable.append(buckets["codex"])
    elif not buckets:
        bucket = limits["rateLimits"]
        if bucket.get("limitId", "codex") != (model.get("limitId") or "codex"):
            raise ValueError("model limit unavailable")
        applicable = [bucket]
    elif set(buckets) == {"codex"} and not model.get("limitId"):
        applicable = [buckets["codex"]]
    else:
        raise ValueError("model limit unavailable")
    windows = []
    for bucket in applicable:
        reported = [w for w in (bucket.get("primary"), bucket.get("secondary")) if w is not None]
        if not reported or bucket.get("rateLimitReachedType"):
            raise ValueError("Codex quota exhausted or missing window")
        windows.extend((w["usedPercent"], w["resetsAt"]) for w in reported)
    return windows


def candidate(agent, executable, env, cwd, timeout, tier, raised=False):
    now = time.time()
    if agent == "codex":
        models, limits = codex_inventory(executable, cwd, env, timeout)
    else:
        models = claude_models(executable, cwd, env, timeout)
    for rank in TIERS[TIERS.index(tier):]:
        if rank != tier and not raised:
            break
        if agent == "codex":
            pattern = {"light": r"mini|luna|spark", "general": r"sol$|^gpt-[\d.]+(?:-codex)?$",
                       "advanced": r"astra$|codex-max$"}[rank]
            matches = [m for m in models if re.search(pattern, m["model"]) and not m.get("hidden")]
        else:
            alias = {"light": "haiku", "general": "sonnet", "advanced": "opus"}[rank]
            entities = {m["value"]: m for m in models}
            matches = []
            for entry in models:
                if entry["value"] == alias or entry["value"].startswith(f"claude-{alias}-"):
                    model = entry.get("resolvedModel") or entry["value"]
                    matches.append(dict(entities.get(model, entry), model=model))
        for item in matches:
            model = item["model"]
            levels = ([e["reasoningEffort"] for e in item["supportedReasoningEfforts"]]
                      if agent == "codex" else item.get("supportedEffortLevels", []))
            if item.get("supportsEffort") and not levels:
                continue
            try:
                effort = effort_for(rank, levels, raised and tier == rank)
            except ValueError:
                continue
            if agent == "claude":
                flags = [] if effort == "default" else ["--effort", effort]
                output = subprocess.run([executable, "-p", "//usage", "--model", model, *flags],
                                        cwd=cwd, env=env, capture_output=True, check=True,
                                        encoding="utf-8", timeout=timeout).stdout
                windows = claude_windows(output, alias, now)
            else:
                windows = codex_windows(limits, item)
            if not windows or any(type(u) not in (float, int) or not 0 <= u <= 100 or
                                  not math.isfinite(t) or t <= now for u, t in windows):
                raise ValueError("invalid usage window")
            return Candidate(agent, model, effort, min(100 - u for u, _ in windows), now,
                             tuple(t for _, t in windows))
    raise ValueError("required model or reasoning effort unavailable")


def choose(candidates, phase, fixed, now):
    usable = {c.agent: c for c in candidates if 0 <= now - c.observed <= 300 and
              c.remaining > 0 and all(t > now for t in c.resets)}
    if not usable or phase == "implement" and len(usable) != 2:
        return None
    if fixed:
        return usable.get(fixed)
    return max(usable.values(), key=lambda c: (c.remaining, c.agent == "codex"))


def select(phase, text, cwd, timeout, runtime, log, fixed=None, raised=False, reviewer_raised=False):
    tier = task_tier(text)
    candidates, errors = [], {}
    for agent in ("codex", "claude"):
        if phase == "review" and agent != fixed:
            continue
        try:
            executable, env = runtime(agent)
            escalate = reviewer_raised if fixed and fixed != agent else raised
            candidates.append(candidate(agent, executable, env, cwd, min(timeout, 15), tier, escalate))
        except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError, subprocess.SubprocessError) as exc:
            errors[agent] = str(exc)
    choice = choose(candidates, phase, fixed, time.time())
    record = {"tier": tier, "phase": phase, "candidates": [asdict(c) for c in candidates],
              "unknown": errors, "selected": asdict(choice) if choice else None}
    log.with_suffix(".json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    if not choice:
        reason = errors or "quota exhausted or stale"
        raise ValueError(f"Auto held: {reason}. Retry after reset or specify codex or claude. Log: {log.with_suffix('.json')}")
    return choice
