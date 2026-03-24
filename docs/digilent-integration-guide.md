# Integrationsleitfaden

## Zweck

Dieser Leitfaden beschreibt, wie die Digilent-Erweiterung praktisch in das bestehende Repository `Universal-ESP32-Workbench` integriert wird.

## 1. Dateien einfügen

Folgende Dateien in das Repository übernehmen:

- `docs/digilent-extension-spec.md`
- `docs/digilent-integration-guide.md`
- `docs/digilent-wiring-safety.md`
- `docs/digilent-roadmap.md`
- `api/digilent-openapi.yaml`
- `.claude/skills/digilent-workbench/SKILL.md`

## 2. Python-Modul anlegen

Im Verzeichnis `pi/` einen neuen Paketbereich `digilent/` anlegen.

Mindestdateien:

```text
pi/digilent/
├── __init__.py
├── api.py
├── config.py
├── device_manager.py
├── dwf_adapter.py
├── errors.py
├── models.py
├── scope_service.py
├── logic_service.py
├── wavegen_service.py
├── supplies_service.py
└── orchestration.py
```

## 3. Anforderungen ergänzen

Die Python-Abhängigkeiten für den Pi-Dienst ergänzen:

- HTTP-Framework des bestehenden Portals weiterverwenden
- optional `pydantic` für Request-/Response-Modelle
- ggf. `numpy` für Kennwertberechnung und Downsampling

Die eigentliche DWF-Bibliothek stammt aus der Digilent/WaveForms-Installation und wird nicht als normales PyPI-Paket behandelt.

## 4. Konfiguration ergänzen

Neue Konfigurationsdatei anlegen:

```text
/etc/rfc2217/digilent.json
```

Serverstart soll die Datei lesen, Safe-Limits validieren und den Digilent-Service initialisieren.

## 5. API registrieren

Die Digilent-Endpunkte im bestehenden Pi-Portal registrieren.

Empfehlung:

- gemeinsamer Prefix `/api/digilent`
- Fehlerkonsistenz zur vorhandenen API
- strukturierte Logs mit `component=digilent`

## 6. Geräteschutz aktivieren

Unbedingt umsetzen:

- exklusiver Session-Lock
- Busy-Fehler bei konkurrierendem Zugriff
- Capture-Timeouts
- Schutz vor übergroßen Puffern
- Supplies standardmäßig deaktiviert

## 7. Tests hinzufügen

### Unit-Tests

- Kennwertberechnung
- Request-Validierung
- Fehlerabbildung
- Statuszustände

### Integrations-Tests

- Gerät vorhanden / nicht vorhanden
- Trigger-Capture erfolgreich
- Busy-Schutz greift
- High-Level-PWM-Messung liefert konsistente Werte

## 8. Portal-Erweiterung

Optional, aber sinnvoll:

- Digilent-Statuskarte im Web-Portal
- Anzeige von Gerätetyp und Zustand
- letzte Messung und Warnhinweise

## 9. Claude-Code-Verwendung

Nach Übernahme des Skills in `.claude/skills/` und Neustart von Claude Code kann der Skill direkt über die dokumentierten HTTP-Aufrufe arbeiten.

## 10. Empfohlene erste Inbetriebnahme

1. Digilent am Pi anschließen
2. WaveForms / DWF korrekt installieren
3. `GET /api/digilent/status` testen
4. Scope-Capture mit bekannter PWM testen
5. Logic-Capture auf UART-Leitung testen
6. erst danach optional Wavegen oder Supplies freischalten
