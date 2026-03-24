# Digilent-Integration für Universal-ESP32-Workbench

Version: 1.0  
Status: Implementierungsspezifikation  
Zielplattform: Raspberry Pi (Linux, ARM) mit Digilent Analog Discovery / kompatiblem WaveForms-Gerät  
Repository-Ziel: `Universal-ESP32-Workbench`

---

## 1. Zielsetzung

Die bestehende Universal-ESP32-Workbench stellt den Raspberry Pi als netzwerkfähigen Prüfadapter für ESP32-Systeme bereit. Die vorhandene Architektur bündelt serielle Kommunikation, WiFi-Tests, GPIO-Steuerung, OTA-Dateiverteilung, BLE-Proxy, UDP-Logging und Testautomatisierung über eine gemeinsame HTTP-Schnittstelle.

Diese Erweiterung ergänzt das System um einen **instrumentierten Mess- und Stimulus-Adapter** auf Basis eines Digilent-WaveForms-Geräts. Die Erweiterung ermöglicht:

- analoge Spannungsmessung am DUT
- digitale Logikanalyse
- Signalgenerierung für Stimulus-Tests
- schaltbare Hilfsspannungen und statische I/O
- agentenfreundliche, strukturierte Messausgaben für Claude Code oder vergleichbare Werkzeuge

Die Integration erfolgt bewusst **nicht** direkt im LLM- oder Skill-Layer, sondern als lokaler Service auf dem Raspberry Pi, der das Digilent-Gerät exklusiv verwaltet und über die vorhandene HTTP-Portal-Architektur zugänglich macht.

---

## 2. Architekturprinzipien

### 2.1 Grundprinzipien

1. **USB lokal, API remote**  
   Das Digilent-Gerät wird ausschließlich lokal am Pi über das WaveForms SDK angesprochen. Externe Tools greifen nur über HTTP auf den Pi zu.

2. **Ein Gerät, ein Besitzer**  
   Der Zugriff auf die DWF-Bibliothek ist exklusiv. Es darf zu jedem Zeitpunkt nur eine aktive Gerätesession existieren.

3. **Agentenfreundliche Datenmodelle**  
   Standardantworten liefern kompakte Kennwerte; Rohdaten werden nur optional und begrenzt übertragen.

4. **Deterministische Instrumentensteuerung**  
   Alle Messungen erfordern explizite Parameter. Implizite Defaults werden minimal gehalten und serverseitig dokumentiert.

5. **Sichere Signalgrenzen**  
   API und Service validieren Spannungsbereiche, Sample-Raten, Puffergrößen und Kanalbelegungen.

6. **Bestandsarchitektur respektieren**  
   Die Digilent-Erweiterung wird als zusätzlicher Dienstbereich in die vorhandene Pi-Workbench integriert, nicht als separates Nebensystem.

### 2.2 Nicht-Ziele

Nicht Teil dieser ersten Ausbaustufe sind:

- browserseitige Echtzeit-Oszilloskopdarstellung mit hoher Aktualisierungsrate
- harte Echtzeitanforderungen
- Multi-Client-Parallelzugriff auf ein und dasselbe Digilent-Gerät
- vollständige Ersatzfunktion für WaveForms-GUI
- automatisches Dekodieren aller Protokolle im ersten Release

---

## 3. Ist-Kontext des Zielprojekts

Die Universal-ESP32-Workbench beschreibt den Pi als zentrale HTTP-basierte Testplattform mit u. a. Remote-Serial, WiFi-Instrument, GPIO-Control, UDP-Logreceiver, OTA-Ablage, BLE-Proxy, Testautomation und Web-Portal. Das Repository enthält u. a. die Verzeichnisse `.claude/skills`, `docs`, `pi`, `pytest` und `test-firmware` und dokumentiert eine Skill-Installation über Symlinks in `.claude/skills/`. Diese Struktur wird für die Erweiterung beibehalten.

---

## 4. Technische Grundlage Digilent / WaveForms

Die Digilent-Integration basiert auf dem **WaveForms SDK / der DWF-Bibliothek**. In den öffentlich dokumentierten Python-Beispielen werden u. a. folgende Instrumentgruppen adressiert:

- Device: öffnen, Fehlerprüfung, schließen, Temperatur
- Oscilloscope: open, measure, trigger, record, close
- Waveform Generator: generate, close
- Power Supplies: switch, close
- Digital Multimeter: open, measure, close
- Logic Analyzer: open, trigger, record, close
- Pattern Generator: generate, close
- Static I/O: set_mode, get_state, set_state

Diese Fähigkeiten bilden die Basis der nachfolgenden HTTP-API und des Claude-Code-Skills.

---

## 5. Gesamtarchitektur

```text
Claude Code / externe Tests / Python-Clients
                 |
                 | HTTP/JSON
                 v
     Universal-ESP32-Workbench API auf dem Pi
                 |
                 +--> vorhandene Services
                 |    - RFC2217 Serial
                 |    - WiFi
                 |    - GPIO
                 |    - OTA
                 |    - BLE
                 |    - UDP Logs
                 |
                 +--> Digilent API Layer
                         |
                         +--> Digilent Service Facade
                                 |
                                 +--> Device Manager (Locking / Reconnect / Health)
                                 +--> Scope Engine
                                 +--> Logic Engine
                                 +--> Wavegen Engine
                                 +--> Supplies / StaticIO Engine
                                 +--> Result Formatter
                                         |
                                         v
                                   DWF / WaveForms SDK
                                         |
                                         v
                               Analog Discovery am USB des Pi
```

---

## 6. Projektstruktur im Repository

### 6.1 Zielstruktur

```text
Universal-ESP32-Workbench/
├── .claude/
│   └── skills/
│       └── digilent-workbench/
│           └── SKILL.md
├── api/
│   └── digilent-openapi.yaml
├── docs/
│   ├── digilent-extension-spec.md
│   ├── digilent-integration-guide.md
│   ├── digilent-wiring-safety.md
│   └── digilent-roadmap.md
├── pi/
│   ├── digilent/
│   │   ├── __init__.py
│   │   ├── api.py
│   │   ├── config.py
│   │   ├── device_manager.py
│   │   ├── dwf_adapter.py
│   │   ├── errors.py
│   │   ├── models.py
│   │   ├── scope_service.py
│   │   ├── logic_service.py
│   │   ├── wavegen_service.py
│   │   ├── supplies_service.py
│   │   ├── orchestration.py
│   │   └── utils.py
│   ├── tests/
│   │   └── test_digilent_api.py
│   └── ... bestehende Pi-Komponenten ...
└── pytest/
    └── test_digilent_remote.py
```

### 6.2 Modulverantwortung

- `dwf_adapter.py`  
  Dünne, typisierte Kapselung der DWF-API

- `device_manager.py`  
  Gerätesuche, Session-Lock, Open/Close, Reconnect, Status

- `scope_service.py`  
  Konfiguration, Triggering, Erfassung, Metrikberechnung

- `logic_service.py`  
  Digitale Aufzeichnung, Triggerung, Logikkennwerte

- `wavegen_service.py`  
  Signalquellenkonfiguration und Aktivierung

- `supplies_service.py`  
  Hilfsspannungen, statische I/O, Grundschutz

- `models.py`  
  Request-/Response-Schemas

- `api.py`  
  HTTP-Endpunkte und Fehlerabbildung

- `orchestration.py`  
  zusammengesetzte High-Level-Aktionen für Agenten

---

## 7. Betriebsmodell

### 7.1 Service-Modus

Die Digilent-Funktionen laufen im selben HTTP-Portal-Prozess oder in einem dedizierten, lokal gekoppelten Hilfsdienst. Empfohlen ist für die erste Stufe die Integration in denselben Python-Prozessraum wie das Pi-Portal, sofern dadurch keine Stabilitätsprobleme entstehen.

### 7.2 Exklusiver Zugriff

Der `device_manager` implementiert:

- Prozess-Lock über Datei-Lock oder Thread-Mutex
- eindeutigen Gerätestatus: `absent`, `idle`, `busy`, `recovering`, `error`
- definierte Open-/Close-Sequenz
- Schutz gegen konkurrierende Scope-/Logic-/Wavegen-Aufrufe

### 7.3 Fehlerzustände

Standardisierte Servicefehler:

- `DIGILENT_NOT_FOUND`
- `DIGILENT_BUSY`
- `DIGILENT_CONFIG_INVALID`
- `DIGILENT_CAPTURE_TIMEOUT`
- `DIGILENT_TRIGGER_TIMEOUT`
- `DIGILENT_RANGE_VIOLATION`
- `DIGILENT_TRANSPORT_ERROR`
- `DIGILENT_INTERNAL_ERROR`

---

## 8. Konfiguration

### 8.1 Konfigurationsdatei

Pfadempfehlung: `/etc/rfc2217/digilent.json`

### 8.2 Beispielinhalt

```json
{
  "enabled": true,
  "auto_open": false,
  "preferred_device": "auto",
  "max_scope_points": 20000,
  "max_logic_points": 100000,
  "default_timeout_ms": 3000,
  "allow_raw_waveforms": true,
  "allow_supplies": false,
  "safe_limits": {
    "max_scope_sample_rate_hz": 50000000,
    "max_logic_sample_rate_hz": 100000000,
    "max_wavegen_amplitude_v": 5.0,
    "max_supply_plus_v": 5.0,
    "min_supply_minus_v": -5.0
  },
  "labels": {
    "scope_ch1": "DUT_SIG_A",
    "scope_ch2": "DUT_SIG_B",
    "logic_dio0": "UART_TX",
    "logic_dio1": "UART_RX"
  }
}
```

### 8.3 Konfigurationsprinzipien

- serverseitige Obergrenzen sind zwingend
- Labels dienen Portal, Logs und Skill-Ausgaben
- `allow_supplies` ist standardmäßig `false`, um versehentliches Einspeisen zu verhindern

---

## 9. Datenmodell

### 9.1 Antwortdesign

Alle Antworten enthalten:

- `ok`
- `ts`
- `device`
- `request_id`
- `metrics` oder `result`
- optional `warnings`
- optional `waveform` bzw. `logic_samples`

### 9.2 Standard-Messkennwerte Scope

- `vmin`
- `vmax`
- `vpp`
- `vavg`
- `vrms`
- `freq_est_hz`
- `period_est_s`
- `duty_cycle_percent`
- `rise_time_s`
- `fall_time_s`

### 9.3 Standard-Messkennwerte Logic

- `high_ratio`
- `low_ratio`
- `edge_count`
- `freq_est_hz`
- `period_est_s`
- `duty_cycle_percent`

### 9.4 Rohdatenmodell Scope

```json
{
  "waveform": {
    "t_start_s": 0.0,
    "dt_s": 0.000001,
    "unit_x": "s",
    "unit_y": "V",
    "channels": [
      {
        "channel": 1,
        "y": [0.01, 0.03, 0.07]
      }
    ]
  }
}
```

### 9.5 Rohdatenmodell Logic

```json
{
  "logic_samples": {
    "sample_rate_hz": 10000000,
    "channels": [0, 1],
    "packed": false,
    "samples": {
      "0": [0, 0, 1, 1],
      "1": [1, 1, 1, 0]
    }
  }
}
```

---

## 10. HTTP-API

### 10.1 Übersicht Endpunkte

- `GET /api/digilent/status`
- `POST /api/digilent/device/open`
- `POST /api/digilent/device/close`
- `POST /api/digilent/scope/capture`
- `POST /api/digilent/scope/measure`
- `POST /api/digilent/logic/capture`
- `POST /api/digilent/wavegen/set`
- `POST /api/digilent/wavegen/stop`
- `POST /api/digilent/supplies/set`
- `POST /api/digilent/static-io/set`
- `POST /api/digilent/measure/basic`
- `POST /api/digilent/session/reset`

### 10.2 Status

#### `GET /api/digilent/status`

Antwort:

```json
{
  "ok": true,
  "device_present": true,
  "device_open": false,
  "device_name": "Analog Discovery 2",
  "state": "idle",
  "temperature_c": 39.4,
  "capabilities": {
    "scope": true,
    "logic": true,
    "wavegen": true,
    "supplies": true,
    "static_io": true
  }
}
```

### 10.3 Scope-Messung

#### `POST /api/digilent/scope/capture`

Request:

```json
{
  "channels": [1],
  "range_v": 5.0,
  "offset_v": 0.0,
  "sample_rate_hz": 1000000,
  "duration_ms": 10,
  "trigger": {
    "enabled": true,
    "source": "ch1",
    "edge": "rising",
    "level_v": 1.2,
    "timeout_ms": 1000
  },
  "return_waveform": false,
  "max_points": 5000
}
```

Response:

```json
{
  "ok": true,
  "device": "Analog Discovery 2",
  "metrics": {
    "ch1": {
      "vmin": 0.02,
      "vmax": 3.31,
      "vpp": 3.29,
      "vavg": 1.64,
      "vrms": 1.91,
      "freq_est_hz": 999.8,
      "duty_cycle_percent": 49.9
    }
  }
}
```

### 10.4 Schnelle Scope-Messung ohne Rohdaten

#### `POST /api/digilent/scope/measure`

Dient für schnelle Kennwerterzeugung ohne vollständige Kurvenrückgabe.

### 10.5 Logic-Capture

#### `POST /api/digilent/logic/capture`

Request:

```json
{
  "channels": [0, 1, 2],
  "sample_rate_hz": 10000000,
  "samples": 20000,
  "trigger": {
    "enabled": true,
    "channel": 0,
    "edge": "rising",
    "timeout_ms": 1000
  },
  "return_samples": false
}
```

### 10.6 Wavegen

#### `POST /api/digilent/wavegen/set`

```json
{
  "channel": 1,
  "waveform": "square",
  "frequency_hz": 1000,
  "amplitude_v": 3.3,
  "offset_v": 1.65,
  "symmetry_percent": 50,
  "enable": true
}
```

### 10.7 Supplies

#### `POST /api/digilent/supplies/set`

```json
{
  "vplus_v": 3.3,
  "vminus_v": 0.0,
  "enable_vplus": false,
  "enable_vminus": false,
  "confirm_unsafe": false
}
```

Sicherheitsregel: Aktivierung nur wenn `allow_supplies=true` und die Anforderung innerhalb definierter Grenzwerte liegt.

### 10.8 Static I/O

#### `POST /api/digilent/static-io/set`

```json
{
  "pins": [
    {"index": 0, "mode": "output", "value": 1},
    {"index": 1, "mode": "input"}
  ]
}
```

### 10.9 High-Level-Messaktion

#### `POST /api/digilent/measure/basic`

Ermöglicht agentenorientierte Vorlagen.

Beispiel:

```json
{
  "action": "measure_esp32_pwm",
  "params": {
    "channel": 1,
    "expected_freq_hz": 1000,
    "tolerance_percent": 5,
    "sample_rate_hz": 2000000,
    "duration_ms": 20
  }
}
```

Beispielantwort:

```json
{
  "ok": true,
  "action": "measure_esp32_pwm",
  "within_tolerance": true,
  "result": {
    "measured_freq_hz": 998.7,
    "duty_cycle_percent": 49.8,
    "vpp": 3.28
  }
}
```

---

## 11. Request-Validierung

### 11.1 Scope

Zu prüfen sind mindestens:

- erlaubte Kanalnummern
- `range_v > 0`
- `sample_rate_hz` innerhalb Safe-Limits
- `duration_ms > 0`
- `max_points <= max_scope_points`
- Triggerquelle passt zu aktivem Kanal

### 11.2 Logic

- Kanäle im gültigen Bereich
- keine Duplikate
- `samples <= max_logic_points`
- Triggerkanal in Anforderung enthalten

### 11.3 Wavegen

- erlaubte Wellenform: `sine`, `square`, `triangle`, `dc`
- Amplitude und Offset innerhalb Gerätegrenzen
- optional Schutzregel für direkt an ESP32 angeschlossene Pins

### 11.4 Supplies

- standardmäßig deaktiviert
- explizite Freigabe in Konfiguration erforderlich
- bei Aktivierung muss Antwort Warnhinweis zurückgeben

---

## 12. Metrikberechnung

### 12.1 Scope-Kennwerte

Kennwerte werden serverseitig aus den Samples berechnet:

- `vmin`, `vmax`, `vpp`: direkte Extremwertbildung
- `vavg`: arithmetischer Mittelwert
- `vrms`: quadratischer Mittelwert
- `freq_est_hz`: Nullpunkt- oder Schwellenübergangsdetektion mit Mittelung
- `duty_cycle_percent`: Zeitanteil oberhalb Schwellwert
- `rise_time_s`, `fall_time_s`: 10-90-% bzw. 90-10-%-Auswertung

### 12.2 Logic-Kennwerte

- Flankenzählung pro Kanal
- Frequenz aus Flankenabstand
- Duty Cycle aus High-/Low-Dauer

### 12.3 Downsampling

Bei `return_waveform=true` und großen Puffern:

- Rückgabe auf `max_points` begrenzen
- bevorzugt Min/Max-Bucket-Downsampling statt naiver Decimation

---

## 13. Gerätemanagement

### 13.1 Zustandsmaschine

```text
absent -> idle -> busy -> idle
   |       |       |      |
   |       |       v      v
   |       |    error   recovering
   +------> recovering ---->
```

### 13.2 Öffnen

- Gerät suchen
- DWF-Handle erzeugen
- Fähigkeiten lesen
- optional Temperatur lesen
- Zustand auf `idle`

### 13.3 Fehlerbehandlung

Bei DWF-Fehlern:

1. Fehlercode lesen
2. Kontext loggen
3. Session bereinigen
4. Zustand auf `error` oder `recovering`
5. bei transienten Fehlern einmaliger Reopen-Versuch

---

## 14. Logging und Observability

Jeder API-Aufruf erzeugt strukturierte Logs mit:

- Zeitstempel
- Client-IP oder Session-ID
- Request-ID
- Endpunktname
- Zielkanäle
- Parametern in gekürzter Form
- Ergebnisstatus
- Laufzeit in ms
- DWF-Fehlercode, falls vorhanden

Empfohlene Logfelder:

```json
{
  "component": "digilent",
  "op": "scope_capture",
  "request_id": "req-123",
  "duration_ms": 142,
  "status": "ok"
}
```

---

## 15. Sicherheit und elektrische Randbedingungen

### 15.1 Grundregeln

- gemeinsame Masse zwischen Pi, Digilent und DUT sicherstellen
- keine Spannungen außerhalb der zulässigen Digilent-Eingangsbereiche anlegen
- keine Hilfsspannungen aktivieren, solange Verdrahtung nicht eindeutig dokumentiert ist
- Supplies standardmäßig gesperrt lassen
- Wavegen-Amplituden für direkte ESP32-Pins konservativ begrenzen

### 15.2 Empfohlene Praxis für ESP32

- rein beobachtende Messungen bevorzugen
- für PWM-Messungen nur Scope-Eingang und Masse anschließen
- für Logikanalyse nur passende Pegel und gemeinsame Masse
- Boot-/Reset-Sequenzen weiterhin primär über Pi-GPIO steuern

### 15.3 API-Schutzmechanismen

- `confirm_unsafe` für potentiell riskante Aktionen
- globale Konfigurationsfreigaben
- Audit-Logeintrag bei Supplies-/Wavegen-Aktivierung

---

## 16. Claude-Code-Integration

### 16.1 Ziel

Claude Code soll das Digilent-Gerät nicht direkt über native Bibliotheken steuern, sondern ausschließlich über die HTTP-API der Workbench.

### 16.2 Designregeln für den Skill

- nur dokumentierte Endpunkte verwenden
- immer `status` prüfen, bevor Messungen ausgelöst werden
- Rohdaten nur anfordern, wenn sie explizit benötigt werden
- bei Fehlern reproduzierbare Diagnose ausgeben
- keine automatisch riskanten Supplies-Aktionen durchführen

### 16.3 Bevorzugte High-Level-Aktionen

- PWM messen
- Spannungslevel prüfen
- UART-Leitung als digitale Aktivität verifizieren
- Trigger-basierte Captures ausführen
- Testschritt dokumentieren

---

## 17. Implementierungsphasen

### Phase 1 – Minimal Viable Integration

- Device Manager
- `GET /status`
- `POST /scope/capture`
- `POST /logic/capture`
- Kennwertberechnung
- Basistests

### Phase 2 – Stimulus

- `wavegen/set`
- `wavegen/stop`
- `static-io/set`
- optionale Supplies-Freischaltung

### Phase 3 – Agentenorientierte Aktionen

- `measure/basic`
- Claude-Code-Skill
- Fehlertexte und Guardrails

### Phase 4 – Komfort und Portal

- Web-Portal-Karten für Digilent-Status
- Verdrahtungslabels im UI
- Result-History / CSV-Export

---

## 18. Teststrategie

### 18.1 Unit-Tests

Mock-basierte Tests für:

- Request-Validierung
- Metrikberechnung
- Zustandsmaschine
- Fehlerabbildung

### 18.2 Integrations-Tests am Pi

- Gerät erkannt / nicht erkannt
- Scope-Capture mit definierter Signalquelle
- Logic-Capture mit Pattern Generator oder DUT-Pin
- konkurrierende Zugriffe werden abgewiesen

### 18.3 End-to-End-Tests mit ESP32

- PWM-Ausgabe des ESP32 messen
- UART-Toggle erkennen
- Reset-/Boot-Sequenz via Pi-GPIO, Bestätigung via Digilent
- WiFi-/BLE-Test bleibt parallel funktionsfähig

---

## 19. Akzeptanzkriterien

Die Integration gilt als erfolgreich, wenn:

1. der Pi ein angeschlossenes Digilent-Gerät zuverlässig erkennt
2. ein HTTP-Client Scope- und Logic-Messungen auslösen kann
3. Standardantworten kompakte Kennwerte liefern
4. Rohdaten optional und begrenzt verfügbar sind
5. parallele konkurrierende Zugriffe sauber blockiert werden
6. Claude Code über einen Skill die Basisfunktionen kontrolliert nutzen kann
7. riskante Funktionen serverseitig abgesichert sind

---

## 20. Implementierungsleitlinien für Python

### 20.1 Stil

- Python 3.11+
- Typannotationen durchgängig
- dataclasses oder Pydantic-Modelle
- zentralisierte Fehlerklassen
- keine DWF-Aufrufe außerhalb des Adapter-Layers

### 20.2 Adapterprinzip

`dwf_adapter.py` enthält nur dünne Hardware-Primitiven, z. B.:

- `open_device()`
- `close_device()`
- `read_temperature()`
- `scope_capture_raw(...)`
- `logic_capture_raw(...)`
- `wavegen_apply(...)`
- `supplies_apply(...)`
- `static_io_apply(...)`

Fachlogik gehört in Service-Module.

---

## 21. Beispiel einer Service-Fassade

```python
class DigilentFacade:
    def get_status(self) -> dict: ...
    def scope_capture(self, req: ScopeCaptureRequest) -> ScopeCaptureResponse: ...
    def logic_capture(self, req: LogicCaptureRequest) -> LogicCaptureResponse: ...
    def wavegen_set(self, req: WavegenRequest) -> GenericResponse: ...
    def supplies_set(self, req: SuppliesRequest) -> GenericResponse: ...
    def measure_basic(self, req: BasicMeasureRequest) -> BasicMeasureResponse: ...
```

---

## 22. Rückwärtskompatibilität

Die Erweiterung darf bestehende Workbench-Services nicht beeinträchtigen. Insbesondere:

- keine Änderung bestehender RFC2217-Endpunkte
- keine Änderung bestehender WiFi-/BLE-/GPIO-Schnittstellen
- Digilent ist optional; bei Abwesenheit bleibt die Workbench vollständig funktionsfähig

---

## 23. Bekannte Risiken

- Unterschiede zwischen Analog Discovery 2, 3 und anderen WaveForms-kompatiblen Geräten
- mögliche ARM-/Bibliotheksbesonderheiten am Raspberry Pi
- USB-Stabilität bei Lastwechseln
- große Rohdatenmengen bei ungebremster API-Nutzung
- Fehlbedienung der Supplies ohne ausreichende Schutzlogik

---

## 24. Empfehlung für die erste Realisierung

Für die erste produktive Version wird empfohlen:

- Scope und Logic zuerst fertigzustellen
- Supplies standardmäßig deaktiviert zu lassen
- High-Level-Messaktionen nur für typische ESP32-Anwendungsfälle anzubieten
- Skill und OpenAPI parallel zur API zu pflegen
- alle Rohdatenantworten explizit begrenzen

---

## 25. Ergebnis

Mit dieser Erweiterung entwickelt sich die Universal-ESP32-Workbench von einer Remote-Testplattform für Kommunikation und Steuerung zu einem **vollwertigen, netzwerkbasierten Messplatz mit physikalischer Signalbeobachtung**. Die Kombination aus vorhandener Pi-Infrastruktur und Digilent-WaveForms-Gerät ist architektonisch konsistent, agentenfreundlich und für automatisierte ESP32-Validierung besonders geeignet.
