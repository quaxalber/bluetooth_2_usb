# Pi Connectivity Recovery Playbook

Use this playbook when a Raspberry Pi used for `bluetooth_2_usb` is flaky or
unreachable over SSH, especially when plain hostnames or IPv4 look broken but
the Pi is likely still on the local network.

This playbook is intentionally focused on:

- SSH reachability from the workstation to the Pi
- hostname, mDNS, and IPv6 link-local diagnosis
- recurring Wi-Fi stability issues on Raspberry Pi OS with NetworkManager
- minimal host-side fixes that make repeated remote validation reliable again

## Assumptions

- the workstation and Pi are on the same local network
- the workstation knows which network interface reaches the Pi, for example
  `wlp38s0`
- the Pi user can authenticate over SSH
- passwordless sudo is strongly recommended for repeatable agentic work and
  remote validation:

```bash
PI_HOST="${PI_HOST:-your-pi-host}"

ssh "$PI_HOST" 'sudo -n true'
```

## 1. Check the workstation view first

Start on the workstation, not on the Pi.

```bash
PI_HOST="${PI_HOST:-your-pi-host}"

getent hosts "$PI_HOST" || true
getent ahosts "$PI_HOST" || true
avahi-resolve -n "${PI_HOST}.local" 2>/dev/null || true
ip -6 addr show dev wlp38s0
```

Interpretation:

- if `getent` only shows a bare `fe80::...` address, SSH still needs an
  interface scope such as `%wlp38s0`
- if `PI_HOST.local` resolves but `PI_HOST` does not, mDNS is healthier than
  the local DNS search path
- if the workstation interface does not have its own link-local IPv6 address,
  direct link-local reachability will not work until that interface is up

## 2. Test direct reachability before trusting the hostname

Probe the Pi through the paths that matter most:

```bash
ping -c 1 "${PI_HOST}.local" || true
ping -6 -c 1 "fe80::YOUR-PI-LINK-LOCAL%wlp38s0" || true
ssh -6 "user@fe80::YOUR-PI-LINK-LOCAL%wlp38s0" 'hostname && whoami'
```

Interpretation:

- a successful link-local IPv6 ping or SSH session is a stronger signal than an
  IPv4 ping failure on consumer Wi-Fi
- do not treat missing IPv4 ICMP replies as proof that the Pi is down if
  link-local SSH still works
- if direct link-local SSH works, pin that path in `~/.ssh/config` instead of
  repeatedly relying on ambiguous hostname resolution

## 3. Pin a stable SSH alias

Use a host alias that always resolves to the known-good link-local address and
interface scope.

```sshconfig
Host pi0w pi0w.local
    User user
    HostName fe80::YOUR-PI-LINK-LOCAL%wlp38s0
    AddressFamily inet6
    HostKeyAlias pi0w
    ConnectTimeout 5
```

Then validate:

```bash
ssh pi0w 'hostname && whoami'
ssh pi0w.local 'hostname && whoami'
```

`HostKeyAlias` matters here because the same Pi may previously have been known
under `pi0w`, `pi0w.local`, or a literal address.

## 4. Check Pi-side network stability once SSH works

After reconnecting, inspect the live NetworkManager state:

```bash
PI_HOST="${PI_HOST:-pi0w}"

ssh "$PI_HOST" '
  conn="$(nmcli --get-values GENERAL.CONNECTION device show wlan0 | head -n 1)"
  echo "CONNECTION=${conn}"
  nmcli device show wlan0
  echo "---"
  nmcli -g 802-11-wireless.powersave,ipv4.method,ipv4.gateway,ipv4.dns,ipv4.ignore-auto-dns \
    connection show "$conn"
  echo "---"
  cat /etc/resolv.conf
'
```

Look for these recurring failure patterns:

- `802-11-wireless.powersave: 0 (default)` or `enable` instead of an explicit
  disabled setting
- only the router IP listed as DNS, for example only `192.168.2.1`
- a healthy `wlan0` connection but flaky package installs or name resolution

If `iw` is installed, you can also inspect the live Wi-Fi powersave state:

```bash
ssh "$PI_HOST" 'iw dev wlan0 get power_save'
```

## 5. Apply the stable NetworkManager profile pattern

The most stable setup in this workspace has been:

- `NetworkManager` managing `wlan0`
- Wi-Fi powersave disabled
- explicit IPv4 DNS servers, with the router resolver only as a fallback

Apply that pattern to the active connection:

```bash
PI_HOST="${PI_HOST:-pi0w}"

ssh "$PI_HOST" '
  conn="$(nmcli --get-values GENERAL.CONNECTION device show wlan0 | head -n 1)"
  sudo -n nmcli connection modify "$conn" \
    802-11-wireless.powersave 2 \
    ipv4.dns "1.1.1.1,9.9.9.9,192.168.2.1" \
    ipv4.ignore-auto-dns yes
  sudo -n nmcli connection up "$conn"
'
```

Notes:

- `802-11-wireless.powersave 2` means disabled
- `connection up` may briefly interrupt SSH while Wi-Fi reconnects
- reconnect through the pinned link-local SSH alias afterwards

## 6. Re-validate after the profile change

From the workstation:

```bash
ssh pi0w '
  conn="$(nmcli --get-values GENERAL.CONNECTION device show wlan0 | head -n 1)"
  nmcli -g 802-11-wireless.powersave,ipv4.dns,ipv4.ignore-auto-dns connection show "$conn"
  cat /etc/resolv.conf
  systemctl is-active bluetooth_2_usb.service
'
ping -6 -c 1 "fe80::YOUR-PI-LINK-LOCAL%wlp38s0"
ping -c 1 pi0w.local || true
```

On the Pi:

```bash
sudo /opt/bluetooth_2_usb/scripts/smoke_test.sh --verbose
sudo /opt/bluetooth_2_usb/scripts/debug.sh --duration 10
```

If the Pi is still reachable only through the literal link-local address, keep
the SSH alias and treat that as the supported local-workspace path until the
underlying LAN naming behavior changes.

## Helper script

For a quick workstation-side diagnosis pass, use:

```bash
./scripts/check_pi_connectivity.sh --host pi0w --user user --link-local fe80::YOUR-PI-LINK-LOCAL --interface wlp38s0
```

That helper prints resolver results, ping/SSH probe output, and a ready-to-paste
SSH config block for the pinned link-local alias.
