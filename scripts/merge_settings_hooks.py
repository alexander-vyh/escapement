#!/usr/bin/env python3
"""Additively merge the template's hooks block into the live settings.json.

Part of the deploy-drift fix (escapement-e9v.8). INSTALL.sh previously
only WARNED that hooks needed manual merging, so newly-registered hooks (e.g.
bypass_guard) never fired even after their files were symlinked. This makes the
merge automatic and safe:

  - ADDITIVE: never removes the user's own settings or their own hook entries;
    only adds template-registered hook commands that are missing.
  - DEDUPED by command string: idempotent — re-running adds nothing.
  - SCOPED to the `hooks` block: every other settings key is preserved verbatim.
  - BACKED UP before writing; output is validated JSON.

Usage: merge_settings_hooks.py <template.json> <live_settings.json>
Exit 0 on success (or no-op); 1 on error.
"""

from __future__ import annotations

import copy
import datetime
import json
import os
import sys


def merge_hooks(template: dict, settings: dict) -> dict:
    """Return settings with template['hooks'] additively merged in.

    Groups are matched by their `matcher` field (absent == no matcher). Within a
    group, hook commands already present are left untouched; missing ones are
    appended. The input dicts are not mutated.
    """
    out = copy.deepcopy(settings) if isinstance(settings, dict) else {}
    out.setdefault("hooks", {})
    template_hooks = (template or {}).get("hooks", {})
    for event, template_groups in template_hooks.items():
        live_groups = out["hooks"].setdefault(event, [])
        for template_group in template_groups:
            matcher = template_group.get("matcher")
            live_group = next((g for g in live_groups if g.get("matcher") == matcher), None)
            if live_group is None:
                live_group = {"hooks": []}
                if matcher is not None:
                    live_group["matcher"] = matcher
                live_groups.append(live_group)
            live_group.setdefault("hooks", [])
            present = {h.get("command") for h in live_group["hooks"]}
            for hook in template_group.get("hooks", []):
                if hook.get("command") not in present:
                    live_group["hooks"].append(copy.deepcopy(hook))
                    present.add(hook.get("command"))
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: merge_settings_hooks.py <template.json> <live_settings.json>", file=sys.stderr)
        return 1
    template_path, settings_path = argv[1], argv[2]
    try:
        with open(template_path) as f:
            template = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"merge-settings: cannot read template {template_path}: {e}", file=sys.stderr)
        return 1

    settings: dict = {}
    if os.path.exists(settings_path):
        try:
            with open(settings_path) as f:
                settings = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"merge-settings: cannot read settings {settings_path}: {e} — "
                  "refusing to overwrite; merge manually.", file=sys.stderr)
            return 1

    merged = merge_hooks(template, settings)
    if merged == settings:
        print("merge-settings: settings hooks already up to date.")
        return 0

    try:
        text = json.dumps(merged, indent=2) + "\n"  # validate serializable before touching disk
    except (TypeError, ValueError) as e:
        print(f"merge-settings: refusing to write invalid JSON: {e}", file=sys.stderr)
        return 1

    if os.path.exists(settings_path):
        stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = f"{settings_path}.backup-{stamp}"
        with open(settings_path) as src, open(backup, "w") as dst:
            dst.write(src.read())
        print(f"merge-settings: backup -> {backup}")
    with open(settings_path, "w") as f:
        f.write(text)
    print(f"merge-settings: merged template hooks into {settings_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
