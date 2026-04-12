Bitte führe ein kritisches Review des aktuellen Branch-Stands durch und teste die drei unten beschriebenen HID-Profile gegen den neuen Stand. Fokus: echte Bugs, Regressionen, unstabile Annahmen, fehlende Tests, und alles, was Windows-E2E oder Pi-Hotplug negativ beeinflussen kann.

Kontext

- Repo: `bluetooth_2_usb`
- Branch: `feat/streamline-install-diagnostics`
- Ziel: Review des aktuellen Arbeitsstands plus Linux-/Pi-seitige Validierung der jüngsten Änderungen
- Wichtige Windows-Ergebnisse vom Host:
  - `compat` mit `BOOT_MOUSE + KEYBOARD + CONSUMER_CONTROL` ist aktuell grün für `keyboard`, `mouse`, `consumer`, `combo`
  - `extended` mit `KEYBOARD + MOUSE + CONSUMER_CONTROL` ist aktuell nur teilweise grün: `keyboard` grün, `mouse`/`consumer`/`combo` rot
  - `boot_keyboard`-Variante mit `BOOT_KEYBOARD + MOUSE + CONSUMER_CONTROL` ist aktuell rot: `keyboard` Timeout, `consumer` Timeout, `combo` Timeout, `mouse` bekam ein unerwartetes echtes Event
  - Pi-Injektion war in diesen Läufen jeweils grün; die Unterschiede zeigen sich hostseitig bzw. im Profil-/Gadget-Verhalten

Core Findings

1. Es gab einen echten Pi-seitigen Gadget-Fehler:
   - `/dev/hidg1` war zeitweise eine normale Datei statt Character Device
   - dadurch konnte Keyboard-Relay im Log "grün" aussehen, ohne dass am Host echte HID-Ereignisse ankamen
2. Wir haben `compat` wieder auf den bekannten Windows-freundlichen Mix zurückgeführt:
   - `BOOT_MOUSE + KEYBOARD + CONSUMER_CONTROL`
3. Wir haben Schutz gegen stale `hidg`-Nodes eingebaut:
   - vor `usb_hid.enable(...)` werden erwartete `/dev/hidg*`-Pfade geprüft
   - nicht-character stale Nodes werden entfernt
   - nach `enable` wird validiert, dass die `hidg`-Nodes gesund sind
   - bei Fehler wird einmal retryt
4. Wir haben Hotplug-Retries im Relay ergänzt:
   - kurzlebige Testgeräte bei Inject/Auto-Discover können kurz vor der Filterung oder vor stabiler Initialisierung wieder verschwinden
   - deshalb gibt es jetzt Retries im Hotplug-Add-Pfad
5. Die Windows-Erkennungslogik wurde wieder vereinfacht:
   - der zwischenzeitliche Node-/Parent-/Candidate-Set-Ansatz wurde wieder entfernt
   - Windows Raw Input matched jetzt wieder nur über einfache VID/PID(/MI)-Tokens
   - `consumer` bleibt auf Windows weiter beim HIDAPI-Pfad
6. Der Inject-Nachlauf wurde erhöht:
   - `POST_INJECT_DELAY_MS` wurde angehoben, damit Hotplug-/Auto-Discover-Pfade mehr Zeit bekommen

Code Changes To Review Critically

1. `src/bluetooth_2_usb/relay.py`
   - `compat` verwendet jetzt `BOOT_MOUSE + KEYBOARD + CONSUMER_CONTROL`
   - `_prune_stale_hidg_nodes()`
   - `_validate_hidg_nodes()`
   - Retry im Gadget-Enable-Pfad
   - Hotplug-Add-Retry-Logik im `RelayController`
2. `src/bluetooth_2_usb/test_harness_capture.py`
   - Windows nutzt für nicht-Consumer-Szenarien den separaten Raw-Input-Pfad
   - der komplizierte Candidate-Set-/Node-Gruppierungs-Pfad wurde wieder entfernt
3. `src/bluetooth_2_usb/test_harness_capture_windows.py`
   - Windows Raw Input Backend
   - aktuell einfache Token-basierte Erkennung
4. `src/bluetooth_2_usb/test_harness_common.py`
   - `POST_INJECT_DELAY_MS` erhöht
5. `tests/test_relay.py`
   - neue Tests für `compat`-Profil, stale-node-Bereinigung und Validation
6. `tests/test_test_harness.py`
   - Tests auf die vereinfachte Windows-Erkennung umgestellt

Was ich von dir möchte

1. Bitte mache zuerst ein kritisches Code Review:
   - mögliche Regressionen
   - fragliche Retry-/Timing-Annahmen
   - Cleanup-/Validation-Risiken im Gadget-Pfad
   - Race Conditions
   - zu aggressive oder zu schwache Fehlerbehandlung
   - fehlende oder falsch platzierte Tests
2. Bitte teste danach Linux-/Pi-seitig diese drei Profile explizit:
   - `compat`: `BOOT_MOUSE + KEYBOARD + CONSUMER_CONTROL`
   - `extended`: `KEYBOARD + MOUSE + CONSUMER_CONTROL`
   - `boot_keyboard`: `BOOT_KEYBOARD + MOUSE + CONSUMER_CONTROL`
3. Bitte verifiziere für jedes Profil mindestens:
   - welche `usb_hid`-Geräte tatsächlich aktiviert werden
   - welche `/dev/hidg*`-Nodes entstehen
   - ob alle erwarteten `hidg`-Nodes Character Devices sind
   - ob Relay/Inject sauber bis zu den Gadget-Writes kommen
   - ob Hotplug/Auto-Discover für die temporären Testgeräte stabil ist
4. Bitte achte besonders auf die Frage:
   - Warum ist `extended` aktuell auf Windows nicht voll grün, obwohl `compat` es ist?
   - Gibt es in unserem neuen Pi-/Relay-/Gadget-Verhalten einen offensichtlichen Grund?
5. Bitte gib das Review so zurück:
   - Findings zuerst, nach Schwere sortiert
   - dann offene Fragen / Unsicherheiten
   - dann eine kurze Testmatrix für die drei Profile
   - wenn keine Findings: explizit sagen, dass du keine gefunden hast, aber Rest-Risiken nennen

Hinweise

- Bitte nicht davon ausgehen, dass sichtbare Desktop-Reaktionen allein ausreichen; der belastbare Beleg ist der Host-Capture-Output.
- Bitte achte darauf, dass wir zuletzt die Windows-Erkennung bewusst wieder auf einfache VID/PID(/MI)-Tokens reduziert haben.
- Wenn du einen besseren minimalen Fix für `extended` oder für die Hotplug-Stabilität siehst, nenne ihn klar.
