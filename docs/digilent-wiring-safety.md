# Verdrahtung und Sicherheit

## 1. Grundsatz

Die Digilent-Erweiterung ist als Mess- und Stimulus-Werkzeug für ESP32-Hardware gedacht. Fehlerhafte Verdrahtung kann sowohl das Digilent-Gerät als auch den DUT beschädigen.

## 2. Mindestregeln

- immer gemeinsame Masse verbinden
- Messkanäle nur innerhalb zulässiger Spannungsgrenzen betreiben
- Hilfsspannungen standardmäßig ausgeschaltet lassen
- direkte Einspeisung in ESP32-Pins vermeiden, sofern nicht ausdrücklich geplant
- beim Umschalten von Boot-/Reset-Pins weiterhin bevorzugt Pi-GPIO verwenden

## 3. Empfohlene Standardverdrahtung

### Nur beobachten

- Digilent GND -> DUT GND
- Scope CH1 -> zu beobachtendes Signal
- Scope CH2 -> optional zweites Signal
- Logic DIO0..n -> digitale DUT-Leitungen

### Boot-Sequenz-Messung

- Pi GPIO17 -> DUT EN/RST
- Pi GPIO18 -> DUT GPIO0 oder GPIO9
- Digilent Scope CH1 -> Resetleitung oder Zielsignal
- gemeinsame Masse aller Systeme

### PWM-Messung

- Digilent GND -> DUT GND
- Scope CH1 -> PWM-Pin
- keine aktiven Stimulusquellen erforderlich

## 4. Risikoquellen

- doppelte Spannungsversorgung eines Boards
- zu hohe Wavegen-Amplitude
- falsch aktivierte Supplies
- fehlende Masseverbindung
- DIO/Scope auf unbekannte Pegelbereiche

## 5. API-Schutzmaßnahmen

Die Software muss folgende Schutzmaßnahmen durchsetzen:

- serverseitige Spannungsgrenzen
- Freigabeschalter für Supplies
- Warnhinweise bei Stimulus-Funktionen
- Audit-Logging für riskante Operationen

## 6. Empfehlung für Release 1

- Supplies deaktiviert lassen
- nur Scope und Logic aktiv nutzen
- Wavegen nur für klar dokumentierte Testfälle freigeben
