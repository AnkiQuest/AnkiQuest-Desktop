"""Player preferences kept the same on every device through /api/settings/{user}.

The shared keys are defined in tests/fixtures/synced_settings.json; tests keep `KEYS` equal to
its desktop names. Each synced setting remembers when it last changed on this computer, and the
newer side wins, key by key."""

FEATURE = "settings_sync"

# This device's switch; never synced.
SWITCH = "sync_settings"

# Shared key -> milliseconds of the last change made here; 0 or absent for a value chosen
# before sync existed.
CHANGED_KEY = "synced_settings_changed_at"

# Shared key -> (config key, default, allowed range for numbers).
KEYS = {
    "notify_rank": ("notify_rank", True, None),
    "streak_warning_hours": ("streak_hours", 2, (0, 12)),
    "system_notifications": ("system_notifications", False, None),
    "session_summary": ("session_summary", True, None),
    "goal_celebrations": ("goal_celebrations", True, None),
    "deck_status": ("deck_status", True, None),
    "review_heatmap": ("review_heatmap", True, None),
}


def path(api):
    return "/api/settings/" + api.user


def enabled(config):
    return config.get(SWITCH, True) is not False


def usable(key, value):
    """Whether `value` has the type and range this computer can use for `key`."""
    _, default, bounds = KEYS[key]
    if type(value) is not type(default):
        return False
    return bounds is None or bounds[0] <= value <= bounds[1]


def merge(key, value, changed_at, remote):
    """This computer's value and change time after reading `remote` ({value, updated_at} or None),
    and what to send ({value, updated_at} or None). Cases: tests/fixtures/synced_settings.json."""
    # The server's value wins a tie, as the server keeps the stored value then.
    if remote is not None and remote["updated_at"] >= changed_at:
        if not usable(key, remote["value"]):
            return value, changed_at, None
        return remote["value"], remote["updated_at"], None

    # A value chosen before sync existed only goes up when it differs from the default.
    if remote is None and changed_at == 0 and value == KEYS[key][1]:
        return value, changed_at, None
    return value, changed_at, {"value": value, "updated_at": changed_at}


def local(config, key):
    """`key`'s value and change time in `config`; an unusable value counts as the default."""
    name, default, _ = KEYS[key]
    value = config.get(name, default)
    if not usable(key, value):
        value = default
    changed = config.get(CHANGED_KEY) or {}
    stamp = changed.get(key, 0)
    return value, stamp if type(stamp) is int and stamp >= 0 else 0


def stamped(config, values, now_ms):
    """The change times after saving `values` over `config`: synced settings whose value
    changes get `now_ms`. None when no synced setting changes."""
    changed = dict(config.get(CHANGED_KEY) or {})
    touched = False
    for key, (name, default, _) in KEYS.items():
        if name in values and values[name] != config.get(name, default):
            changed[key] = now_ms
            touched = True
    return changed if touched else None


def turned_on(config, values):
    return SWITCH in values and values[SWITCH] is not False and not enabled(config)


def plan(config, remote):
    """The config values to apply, the change times to keep and the body to send, from the
    server's `settings`."""
    updates, changed, push = {}, {}, {}
    for key, (name, default, _) in KEYS.items():
        value, stamp = local(config, key)
        found = remote.get(key)
        if not _entry(found):
            found = None
        new_value, new_stamp, send = merge(key, value, stamp, found)
        if new_value != config.get(name, default):
            updates[name] = new_value
        changed[key] = new_stamp
        if send is not None:
            push[key] = send
    return updates, changed, push


def _entry(found):
    return isinstance(found, dict) and type(found.get("updated_at")) is int and "value" in found


def run(api, config):
    """Reads the server's settings, sends newer local ones and returns (config values to apply,
    change times), or None when this server does not sync settings. Runs in the background."""
    if FEATURE not in api.capabilities():
        return None
    answer = api._request(path(api))
    updates, changed, push = plan(config, _settings(answer))
    if not push:
        return updates, changed

    # Keep the server's time for what it stored, so a fast clock here does not resend forever.
    merged = _settings(api._request(path(api), {"settings": push}, method="PUT"))
    for key, sent in push.items():
        stored = merged.get(key)
        if _entry(stored) and stored["value"] == sent["value"]:
            changed[key] = stored["updated_at"]
    return updates, changed


def _settings(answer):
    found = answer.get("settings") if isinstance(answer, dict) else None
    return found if isinstance(found, dict) else {}


def settle(snapshot, current, updates, changed):
    """`current` config with a finished sync applied, and whether any setting value changed.
    `snapshot` is the config the sync started from: a setting changed here meanwhile keeps
    its new value and time, and the next sync sends it."""
    before = snapshot.get(CHANGED_KEY) or {}
    stamps = dict(current.get(CHANGED_KEY) or {})
    result = dict(current)
    applied = False
    for key, (name, _, _) in KEYS.items():
        if stamps.get(key, 0) != before.get(key, 0):
            continue
        stamps[key] = changed[key]
        if name in updates:
            result[name] = updates[name]
            applied = True
    result[CHANGED_KEY] = stamps
    return result, applied
