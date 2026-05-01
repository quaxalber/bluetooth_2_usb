from __future__ import annotations

import re


def redact(text: str, hostname: str) -> str:
    """Redact host-specific identifiers from diagnostics text.

    :param text: Raw diagnostics text.
    :param hostname: Local hostname to redact when present.
    :return: Text with UUIDs, PARTUUIDs, Bluetooth MACs, machine IDs, and hostname redacted.
    """
    patterns = [
        (r"PARTUUID=[^\s]+", "PARTUUID=<<REDACTED_PARTUUID>>"),
        (r"UUID=[^\s]+", "UUID=<<REDACTED_UUID>>"),
        (r"/dev/disk/by-uuid/[^\s]+", "/dev/disk/by-uuid/<<REDACTED_UUID>>"),
        (r"/dev/disk/by-partuuid/[^\s]+", "/dev/disk/by-partuuid/<<REDACTED_PARTUUID>>"),
        (r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "<<REDACTED_UUID>>"),
        (r"^(?:[0-9a-f]{32})$", "<<REDACTED_MACHINE_ID>>"),
        (r"\b(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}\b", "<<REDACTED_BT_MAC>>"),
    ]
    redacted = text
    if hostname:
        redacted = re.sub(rf"\b{re.escape(hostname)}\b", "<<REDACTED_HOSTNAME>>", redacted)
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted, flags=re.IGNORECASE | re.MULTILINE)
    return redacted
