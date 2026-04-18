# Pi Connectivity Troubleshooting

This note is the short version of recurring Raspberry Pi connectivity failures
seen during `bluetooth_2_usb` development and validation.

Use it to classify the problem quickly. For the concrete commands and recovery
sequence, go to [pi-connectivity-recovery-playbook.md](pi-connectivity-recovery-playbook.md).

## Typical symptoms

- `ssh pi-host` times out even though the Pi is probably still on Wi-Fi
- `ping pi-host` fails, but `ping pi-host.local` or a direct IPv6 address works
- `ssh` only works when you include an IPv6 link-local scope such as
  `%wlp38s0`
- package downloads or `pip install` fail with DNS errors even though the Pi is
  otherwise online
- the Pi becomes flaky again after idle time or after reconnecting to Wi-Fi

## What has caused this in practice

- the workstation resolved the Pi hostname to a link-local IPv6 address without
  the required interface scope
- SSH relied on an ambiguous hostname instead of a pinned `~/.ssh/config` alias
- NetworkManager fell back to router-only DNS instead of explicit resolvers
- Wi-Fi powersave remained at the default behavior instead of being explicitly
  disabled

## Fast guidance

- prefer a pinned SSH alias that uses the Pi's IPv6 link-local address and the
  workstation interface scope
- treat successful link-local SSH as a better health signal than consumer-Wi-Fi
  IPv4 ping behavior
- if DNS starts failing, inspect `nmcli device show wlan0` and
  `/etc/resolv.conf` before blaming Python packaging or the repo
- for repeatable remote work, make sure the Pi user has passwordless sudo so
  `sudo -n`-based playbooks and smoke checks do not fail early

## Next step

Run the full recovery flow in
[pi-connectivity-recovery-playbook.md](pi-connectivity-recovery-playbook.md).
