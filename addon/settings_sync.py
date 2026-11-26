"""Player preferences kept the same on every device through /api/settings/{user}.

The shared keys are defined in tests/fixtures/synced_settings.json; tests keep `KEYS` equal to
its desktop names. Each synced setting remembers when it last changed on this computer, and the
newer side wins, key by key."""

from . import countdowns, optimize_reminder

FEATURE = "settings_sync"

# This device's switch; never synced.
SWITCH = "sync_settings"

# Shared key -> milliseconds of the last change made here; 0 or absent for a value chosen
# before sync existed.
CHANGED_KEY = "synced_settings_changed_at"

# Shared key -> (config key, default, allowed range for numbers). A list or dict default is
# never changed in place.
KEYS = {
    "notify_rank": ("notify_rank", True, None),
    "streak_warning_hours": ("streak_hours", 2, (0, 12)),
    "session_summary": ("session_summary", True, None),
    "goal_celebrations": ("goal_celebrations", True, None),
    "deck_status": ("deck_status", True, None),
    "review_heatmap": ("review_heatmap", True, None),
    "countdowns": (countdowns.CONFIG_KEY, [], None),
    "optimize_reminder": (optimize_reminder.CONFIG_KEY, optimize_reminder.DEFAULT, None),
}

# Keys only a server with this feature can keep: an older one refuses an unknown value over
# 1024 bytes, which a countdown list can exceed.
NEEDS = {"countdowns": countdowns.FEATURE}


# Synced settings that belong to the account, not the computer: countdowns name the player's
# own exams and decks. Each account's values are put away when another account signs in.
PRIVATE = ("countdowns",)

# Server address -> username -> private key -> {"value", "changed_at"}.
ACCOUNTS_KEY = "synced_private_accounts"

# Private key -> {"value", "changed_at"}: what was made while signed out. It stays on this
# computer, shown whenever no one is signed in, until the player adds it to an account.
DEVICE_KEY = "synced_private_signed_out"


def switch_account(current, old, new):
    """`current` with the private settings of account `old` put away and those of `new` brought
    back. Accounts are (server address, username), or None when signed out, whose values stay
    on this computer; an account seen for the first time starts from the defaults, which a sync
    never sends."""
    result = dict(current)
    kept = {base: dict(users) for base, users in (current.get(ACCOUNTS_KEY) or {}).items()}
    changed = dict(current.get(CHANGED_KEY) or {})

    # Put the old values away: with their account, or on this computer when signed out.
    values = {}
    for key in PRIVATE:
        value, stamp = local(current, key)
        values[key] = {"value": value, "changed_at": stamp}
    if old is not None:
        kept.setdefault(old[0], {})[old[1]] = values
    else:
        result[DEVICE_KEY] = values

    # Bring the new account's values back, the signed-out ones, or the defaults.
    if new is not None:
        saved = kept.get(new[0], {}).get(new[1], {})
    else:
        saved = current.get(DEVICE_KEY) or {}
    for key in PRIVATE:
        name, default, _ = KEYS[key]
        entry = saved.get(key) or {}
        value, stamp = entry.get("value", default), entry.get("changed_at", 0)
        if not usable(key, value) or type(stamp) is not int or stamp < 0:
            value, stamp = default, 0
        result[name] = value
        changed[key] = stamp

    result[CHANGED_KEY] = changed
    result[ACCOUNTS_KEY] = kept
    return result


def signed_out(config, key):
    """The value of private `key` made while signed out; an unusable one counts as the default."""
    _, default, _ = KEYS[key]
    entry = (config.get(DEVICE_KEY) or {}).get(key)
    value = entry.get("value", default) if isinstance(entry, dict) else default
    return value if usable(key, value) else default


def keep_signed_out(config, key, value):
    """`config` with `value` as private `key`'s signed-out value, for after an import."""
    device = dict(config.get(DEVICE_KEY) or {})
    entry = dict(device.get(key) or {})
    entry["value"] = value
    entry.setdefault("changed_at", 0)
    device[key] = entry
    return dict(config, **{DEVICE_KEY: device})


def path(api):
    return "/api/settings/" + api.user


def enabled(config):
    return config.get(SWITCH, True) is not False


def usable(key, value):
    """Whether `value` has the type and range this computer can use for `key`."""
    _, default, bounds = KEYS[key]
    if key == "countdowns":
        return countdowns.valid(value)
    if key == "optimize_reminder":
        return optimize_reminder.valid(value)
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


def synced(features):
    """The keys this server can keep."""
    return [key for key in KEYS if NEEDS.get(key, FEATURE) in features]


def plan(config, remote, keys=tuple(KEYS)):
    """The config values to apply, the change times to keep and the body to send for `keys`,
    from the server's `settings`."""
    updates, changed, push = {}, {}, {}
    for key in keys:
        name, default, _ = KEYS[key]
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
    features = api.capabilities()
    if FEATURE not in features:
        return None
    answer = api._request(path(api))
    updates, changed, push = plan(config, _settings(answer), synced(features))
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
    its new value and time, and the next sync sends it. Keys the sync left out keep theirs."""
    before = snapshot.get(CHANGED_KEY) or {}
    stamps = dict(current.get(CHANGED_KEY) or {})
    result = dict(current)
    applied = False
    for key, (name, _, _) in KEYS.items():
        if key not in changed or stamps.get(key, 0) != before.get(key, 0):
            continue
        stamps[key] = changed[key]
        if name in updates:
            result[name] = updates[name]
            applied = True
    result[CHANGED_KEY] = stamps
    return result, applied
