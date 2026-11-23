# Smart Home Climate

[🇬🇧 English](#english) | [🇺🇦 Українська](#українська) | [🇷🇺 Русский](#русский) | [🇩🇪 Deutsch](#deutsch)

---

## English

Automated home climate and heating control system based on Bluetooth Low Energy (BLE) sensors (currently using Xiaomi sensors). The application monitors indoor climate, manages ventilation, controls a gas boiler via a relay, and tracks/forecasts gas consumption.

### Features
* **BLE Climate Monitoring:** Real-time temperature and humidity data collection from BLE sensors.
* **Ventilation & Microclimate Control:** Automated ventilation recommendations or actuator control based on temperature and humidity thresholds.
* **Gas Boiler Relay Control:** Smart on/off switching of the gas boiler via a relay module to maintain target room temperatures efficiently.
* **Gas Meter Tracking:** Logging and accounting of gas meter readings.
* **Consumption Calculation & Forecasting:** Analysis of historical gas usage and prediction of future consumption based on heating runtime and outdoor/indoor temperature trends.

### Hardware & Requirements
* **Sensors:** BLE Temperature & Humidity sensors (e.g., Xiaomi LYWSD03MMC).
* **Relay Module:**
* **Host Device:** Home PC with Bluetooth adapter.
* **Software:** Python 3.12

### Quick Start

   ```bash
   git clone https://github.com/Andreyinweb/smart_home_climate
   cd smart_home_climate
   bash run/run.sh
   ```

---

## Українська

Автоматизована система керування мікрокліматом та опаленням у будинку на базі датчиків Bluetooth Low Energy (BLE, наразі використовуються датчики Xiaomi). Програма відстежує клімат у приміщенні, керує провітрюванням, вмикає/вимикає газовий котел через реле, а також веде облік і прогнозує витрату газу.

### Основні можливості
- **BLE-моніторинг клімату:** Збір даних про температуру та вологість у реальному часі з BLE-датчиків.
- **Контроль провітрювання та мікроклімату:** Автоматичні рекомендації щодо провітрювання або керування приводами на основі порогових значень температури та вологості.
- **Керування реле газового котла:** Розумне вмикання та вимикання газового котла через модуль реле для ефективного підтримання цільової температури в кімнатах.
- **Облік показників газового лічильника:** Фіксація та облік показників лічильника газу.
- **Розрахунок і прогнозування витрати:** Аналіз історичного споживання газу та прогнозування майбутніх витрат на основі часу роботи опалення й тенденцій зовнішньої/внутрішньої температури.

### Обладнання та вимоги
- **Датчики:** BLE-датчики температури та вологості (наприклад, Xiaomi LYWSD03MMC).
- **Модуль реле:**
- **Хост-пристрій:** Домашній ПК із Bluetooth-адаптером.
- **ПЗ:** Python 3.12

### Швидкий старт

   ```bash
   git clone https://github.com/Andreyinweb/smart_home_climate
   cd smart_home_climate
   bash run/run.sh
   ```

---

## Русский

Система автоматического управления микроклиматом и отоплением в доме на базе датчиков Bluetooth Low Energy (BLE, сейчас используются датчики Xiaomi). Программа отслеживает температуру и влажность, управляет проветриванием, включает/выключает газовый котёл через реле, а также ведёт учёт показаний счётчика и прогнозирует расход газа.

### Основные возможности
* **Мониторинг климата по BLE:** Сбор данных о температуре и влажности с датчиков в реальном времени.
* **Контроль проветривания и влажности:** Анализ параметров воздуха и управление проветриванием при отклонении от заданных норм.
* **Управление газовым котлом:** Автоматическое замыкание/размыкание реле котла для поддержания комфортной температуры и экономии топлива.
* **Учёт показаний счётчика:** Фиксация и хранение показаний газового счётчика.
* **Расчёт и прогноз расхода газа:** Аналитика фактического потребления и прогнозирование расхода газа на основе времени работы котла и температурных показателей.

### Оборудование и требования
* **Датчики:** BLE-датчики температуры и влажности (например, Xiaomi LYWSD03MMC).
* **Реле котла:**
* **Сервер / хост:** ПК на Linux с Bluetooth-адаптером.
* **ПО:** Python 3.12

### Быстрый старт

   ```bash
   git clone https://github.com/Andreyinweb/smart_home_climate
   cd smart_home_climate
   bash run/run.sh
   ```
---

## Deutsch

Automatisiertes System zur Steuerung von Raumklima und Heizung auf Basis von Bluetooth Low Energy (BLE)-Sensoren (derzeit Xiaomi-Sensoren). Die Anwendung überwacht Temperatur und Luftfeuchtigkeit, steuert die Lüftung, schaltet einen Gasheizkessel über ein Relais und erfasst sowie prognostiziert den Gasverbrauch.

### Funktionen
* **BLE-Klimaüberwachung:** Echtzeit-Erfassung von Temperatur- und Luftfeuchtigkeitsdaten über BLE-Sensoren.
* **Lüftungs- und Feuchtigkeitssteuerung:** Überwachung der Luftqualität sowie Steuerung oder Empfehlungen zum Lüften anhand definierter Grenzwerte.

* **Steuerung des Gasheizkessels:** Intelligentes Ein- und Ausschalten des Kessels über ein Relaismodul zur effizienten Temperaturregelung.
* **Gaszähler-Erfassung:** Protokollierung und Verwaltung der Gaszählerstände.
* **Verbrauchsberechnung & Prognose:** Auswertung des bisherigen Gasverbrauchs und Vorhersage des zukünftigen Bedarfs basierend auf Kessellaufzeiten und Temperaturdaten.

### Hardware & Voraussetzungen
* **Sensoren:** BLE Temperatur- und Luftfeuchtigkeitssensoren (z. B. Xiaomi LYWSD03MMC).
* **Relaismodul:**
* **Host-System:** PC mit Bluetooth-Adapter.
* **Software:** Python 3.12

### Schnellstart

 ```bash
   git clone https://github.com/Andreyinweb/smart_home_climate
   cd smart_home_climate
   bash run/run.sh
   ```

---
