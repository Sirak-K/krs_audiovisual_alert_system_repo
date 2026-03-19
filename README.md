# Codex Response Audiovisual Alert System

Detta ar den dedikerade projektmappen for Codex-notifieringar.

Filer:
- `notify.py`: huvudscript for ljud, toast, loggning, debounce och self-test.
- `settings.json`: lokal konfiguration for titel, ljudfil, fallback, debounce och toast.
- `launch_notify.cmd`: launcher som foredrar en explicit `python.exe` om en vanlig installation finns, och annars faller tillbaka till WindowsApps-aliaset.

Anvandning:
- Manuellt self-test: `launch_notify.cmd --self-test`
- Loggfil: `logs/notify_events.jsonl`
- Debounce-state: `state/notify_state.json`

Nuvarande design:
- Toast och ljud triggas parallellt sa langt systemet tillater.
- Toast ar best-effort och blockerar inte agenten.
- Ljud spelar forst WAV, sedan fallback enligt `settings.json`.
- Alla relevanta resultat loggas tyst till fil for felsokning.
