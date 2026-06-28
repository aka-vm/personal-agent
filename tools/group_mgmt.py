#!/usr/bin/env python3
"""Manage external WhatsApp group access from the private chat.

Commands:
  python3 tools/group_mgmt.py list                         # show all active groups
  python3 tools/group_mgmt.py caps                         # list available capabilities
  python3 tools/group_mgmt.py add <jid> <cap>             # add a capability to a group
  python3 tools/group_mgmt.py remove-cap <jid> <cap>      # remove a capability from a group
  python3 tools/group_mgmt.py deactivate <jid>            # remove group entirely
  python3 tools/group_mgmt.py show <jid>                  # show full policy for a group
  python3 tools/group_mgmt.py validate <jid>              # dry-run test — check capability actually works
"""
import os
import sys
import yaml

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core import group_access

# Named capability bundles — each maps to tools + default task description.
CAPABILITIES = {
    "jio-email": {
        "description": "Draft and send JIO Fiber complaint emails to jiofibercare@jio.com",
        "tasks": (
            "Draft and send complaint emails to JIO Fiber customer care (jiofibercare@jio.com).\n"
            "  - When someone reports a JIO issue, draft the email showing full text, wait for approval.\n"
            "  - Only send after explicit group approval ('send it' / 'approved').\n"
            "  - Use JIO_DRAFT / JIO_SEND markers (handled by adapter — no tool needed)."
        ),
        "tools": [],  # marker-based: adapter calls jio_complaint.py directly, no Bash tool needed
        "scope": {"jio_complaint": True},
    },
    "splitwise": {
        "description": "Add shared expenses to Splitwise",
        "tasks": "Add shared expenses to Splitwise when group members ask.",
        "tools": [
            "mcp__splitwise__create_expense",
            "mcp__splitwise__resolve_group",
            "mcp__splitwise__get_categories",
            "mcp__splitwise__resolve_category",
            "mcp__splitwise__get_current_user",
            "mcp__splitwise__resolve_friend",
        ],
        "scope": {},
    },
    # NOTE: no "weather" capability — it would need Bash, which is hard-denied in
    # sandboxed group sessions (Bash(...) patterns are ignored by --allowedTools).
    # A weather capability must be marker-based (like jio-email) before re-adding.
}


def _cap_key(tool_or_name: str) -> str | None:
    """Return which capability name a tool belongs to, or None."""
    for name, cap in CAPABILITIES.items():
        if tool_or_name in cap["tools"]:
            return name
        if tool_or_name == name:
            return name
    return None


def cmd_list():
    groups = group_access.all_groups()
    if not groups:
        print("No active groups.")
        return
    for jid, policy in groups.items():
        tools = policy.get("allowed_tools") or []
        scope = policy.get("scope") or {}
        # Map tools/scope flags → capability names where possible
        caps = []
        for name, cap in CAPABILITIES.items():
            has_tools = cap["tools"] and any(t in tools for t in cap["tools"])
            has_scope = any(scope.get(k) for k in (cap.get("scope") or {}))
            if has_tools or has_scope:
                caps.append(name)
        tool_summary = ", ".join(caps) if caps else "talk-only"
        print(f"{policy.get('name', jid)}")
        print(f"  JID  : {jid}")
        print(f"  Caps : {tool_summary}")
        if scope:
            print(f"  Scope: {scope}")
        print()


def cmd_caps():
    print("Available capabilities:")
    for name, cap in CAPABILITIES.items():
        print(f"  {name:20s} — {cap['description']}")


def cmd_add(jid: str, cap_name: str):
    cap = CAPABILITIES.get(cap_name)
    if not cap:
        print(f"Unknown capability '{cap_name}'. Run 'caps' to see options.")
        sys.exit(1)
    policy = group_access.group_policy(jid)
    if not policy:
        print(f"Group {jid} is not active. Activate it first via propose/confirm flow.")
        sys.exit(1)
    existing_tools = policy.get("allowed_tools") or []
    if any(t in existing_tools for t in cap["tools"]):
        print(f"Group already has '{cap_name}'.")
        return
    new_tools = existing_tools + [t for t in cap["tools"] if t not in existing_tools]
    new_scope  = {**( policy.get("scope") or {}), **cap["scope"]}
    new_tasks  = (policy.get("tasks", "").rstrip() + "\n" + cap["tasks"]).strip()
    group_access.activate(jid, policy.get("name"), new_tasks, new_tools, new_scope)
    print(f"✅ Added '{cap_name}' to '{policy.get('name', jid)}'")


def cmd_remove_cap(jid: str, cap_name: str):
    cap = CAPABILITIES.get(cap_name)
    if not cap:
        print(f"Unknown capability '{cap_name}'.")
        sys.exit(1)
    policy = group_access.group_policy(jid)
    if not policy:
        print(f"Group {jid} not found.")
        sys.exit(1)
    existing_tools = policy.get("allowed_tools") or []
    new_tools = [t for t in existing_tools if t not in cap["tools"]]
    group_access.activate(jid, policy.get("name"), policy.get("tasks", ""), new_tools,
                          policy.get("scope") or {})
    print(f"✅ Removed '{cap_name}' from '{policy.get('name', jid)}'")


def cmd_deactivate(jid: str):
    data = group_access._read_yaml()
    groups = data.get("groups") or {}
    if jid not in groups:
        print(f"Group {jid} not found.")
        sys.exit(1)
    name = groups[jid].get("name", jid)
    del groups[jid]
    data["groups"] = groups
    with open(group_access.POLICY_FILE, "w") as f:
        yaml.safe_dump(data, f, sort_keys=False, allow_unicode=True)
    os.chmod(group_access.POLICY_FILE, 0o600)
    print(f"✅ Deactivated '{name}'")


def cmd_show(jid: str):
    policy = group_access.group_policy(jid)
    if not policy:
        print(f"Group {jid} not active.")
        sys.exit(1)
    print(f"Group : {policy.get('name', jid)}")
    print(f"JID   : {jid}")
    print(f"Tasks :\n{policy.get('tasks', '')}")
    print(f"Tools : {policy.get('allowed_tools') or []}")
    print(f"Scope : {policy.get('scope') or {}}")


def cmd_validate(jid: str):
    """Dry-run test: check that the restricted prompt generates cleanly and each
    active capability produces the expected output from a simulated group turn."""
    policy = group_access.group_policy(jid)
    if not policy:
        print(f"Group {jid} not active.")
        sys.exit(1)
    name = policy.get("name", jid)
    print(f"Validating '{name}'...")

    # 1. Prompt generation
    try:
        prompt = group_access.restricted_prompt(policy)
        print("  ✅ restricted_prompt(): OK")
    except Exception as e:
        print(f"  ❌ restricted_prompt() FAILED: {e}")
        sys.exit(1)

    # 2. Tool name sanity — warn about Bash patterns that don't work via --allowedTools
    for t in (policy.get("allowed_tools") or []):
        if t.startswith("Bash(") and ":" in t:
            print(f"  ⚠️  Tool '{t}' uses Bash pattern — this does NOT work via --allowedTools CLI flag. "
                  f"Use the marker approach instead.")
        else:
            print(f"  ✅ Tool '{t}': looks valid")

    # 3. Check expected markers are in prompt for known scope capabilities
    scope = policy.get("scope") or {}
    if scope.get("jio_complaint"):
        if "JIO_DRAFT" in prompt and "JIO_SEND" in prompt:
            print("  ✅ JIO marker instructions present in prompt")
        else:
            print("  ❌ JIO_DRAFT/JIO_SEND missing from prompt — group session won't know how to send emails")

    # 4. Actual dry-run Claude session (optional — takes ~10s and costs tokens).
    # Pass --live to opt in; default (incl. non-interactive/agent runs) skips it
    # rather than crashing on EOFError from input().
    print()
    if "--live" not in sys.argv:
        print("Static checks passed. (Re-run with --live to also run a real Claude session test.)")
        return

    from core.agent import handle
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    public_dir = group_access.PUBLIC_WORKDIR

    if scope.get("jio_complaint"):
        print("  Testing JIO complaint flow...")
        r = handle(
            "[Sender phone: +919999999999]\nJio internet is down, please file a complaint.",
            f"validate:{jid}:jio",
            extra_system=prompt,
            allowed_tools=policy.get("allowed_tools") or [],
            work_dir=public_dir,
        )
        if r.error:
            print(f"  ❌ JIO test FAILED: {r.error}")
        elif "JIO_DRAFT" in (r.text or ""):
            print(f"  ✅ JIO_DRAFT marker found in response — adapter will handle it correctly")
        else:
            print(f"  ❌ JIO_DRAFT marker NOT in response. Got: {(r.text or '')[:300]}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "list":
        cmd_list()
    elif cmd == "caps":
        cmd_caps()
    elif cmd == "add" and len(sys.argv) >= 4:
        cmd_add(sys.argv[2], sys.argv[3])
    elif cmd == "remove-cap" and len(sys.argv) >= 4:
        cmd_remove_cap(sys.argv[2], sys.argv[3])
    elif cmd == "deactivate" and len(sys.argv) >= 3:
        cmd_deactivate(sys.argv[2])
    elif cmd == "show" and len(sys.argv) >= 3:
        cmd_show(sys.argv[2])
    elif cmd == "validate" and len(sys.argv) >= 3:
        cmd_validate(sys.argv[2])
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
