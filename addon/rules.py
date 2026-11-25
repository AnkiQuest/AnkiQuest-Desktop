"""The shared rules for the add-on's pages: AnkiQuest-Server's crates/rules built as one
WebAssembly module, the same Rust the server runs and the Android app links.

The packager writes the module to rules/ankiquest_rules.wasm from the release
ankiquest-rules.json pins. A page gets it inline and compiles it in Anki's Qt WebEngine, so it
needs no web export, request or per-OS library:

    rules/ankiquest_rules.wasm ──base64──▶ promise() in the page ──▶ exports
                                                                    └─ heatmap_intensity

Plain Python, so the tests load it without Anki.
"""

import base64
import json
from pathlib import Path

# The module, as the packager writes it.
MODULE = Path(__file__).resolve().parent / "rules" / "ankiquest_rules.wasm"

# The interface this add-on is written for (abi_version in crates/rules-wasm).
ABI_VERSION = 1

# A promise of the module's exports; refuses a module with another interface.
PROMISE = """WebAssembly.instantiate(Uint8Array.from(atob(%s),function(c){return c.charCodeAt(0);}),{})
.then(function(found){var rules=found.instance.exports;
if(rules.abi_version()!==%d){throw new Error("ankiquest rules: interface "+rules.abi_version()+", not %d");}
return rules;})"""

_cache = {}


def promise():
    """A JavaScript expression for a promise of the module's exports. Reads the module once."""
    if "promise" not in _cache:
        data = base64.b64encode(MODULE.read_bytes()).decode("ascii")
        _cache["promise"] = PROMISE % (json.dumps(data), ABI_VERSION, ABI_VERSION)
    return _cache["promise"]
