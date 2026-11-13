# AERO-HUB hardware wiring

Pin-by-pin wiring for the sensor node you described: MQ-7, MQ-135, Sharp
GP2Y1010AU0F, a generic BMP280 (HW-611), an optional 16x2 I2C LCD, and a phone
providing GPS over Wi-Fi.

The Pi has **no analog inputs**, so you need one ADC. You have three options,
selected by `ADC_BACKEND`:

| Option | Backend | Notes |
|---|---|---|
| **Arduino Uno over USB** | `arduino` | No purchase if you own one; 5 V tolerant, no divider needed |
| **ADS1115 / ADS1015 over I²C** | `ads1115` / `ads1015` | Small, 16-bit; power at 3.3 V and divide 5 V inputs |
| **MCP3008 over SPI** | `mcp3008` | The original design; only if you already have one |

This guide leads with the Arduino because it matches the current build; the
ADS1115/MCP3008 sections are kept for reference. Detailed Arduino setup,
sketch and protocol: [`ARDUINO_ADC.md`](ARDUINO_ADC.md).

This applies to both modes: in **Mode 2** `raspberry_pi/raspberry_pi.py` reads
the sensors and POSTs them to the backend; in **Mode 1** the backend itself
reads them with `SENSOR_SOURCE=hardware`.

> **Pin numbering.** "Board pin" is the physical pin on the 40-pin header
> (1–40). "BCM" is the GPIO number used in software (`GPIO17` = BCM 17 = board
> pin 11). Do not mix the two.

Power is wired by you, as requested. Keep one **common ground** between the Pi,
the ADC and every sensor: the ADC measures voltages relative to it, so a missing
ground gives nonsense readings.

## Signal connections at a glance

| Signal | From | Arduino | ADS1115 | MCP3008 |
|---|---|---|---|---|
| MQ-7 analog | MQ-7 `AOUT` | `A0` (direct) | `A0` (via divider) | pin 1 (CH0 via divider) |
| MQ-135 analog | MQ-135 `AOUT` | `A1` (direct) | `A1` (via divider) | pin 2 (CH1 via divider) |
| Dust analog | GP2Y1010AU0F `Vo` | `A2` | `A2` | pin 3 (CH2) |
| Dust LED | GP2Y1010AU0F LED pin | `D7` | GPIO17, board pin 11 | GPIO17, board pin 11 |
| ADC bus | — | USB **or** GND + TX/RX | I²C pins 3/5 | SPI pins 23/21/19/24 |
| BMP280 | SDA/SCL | I²C pins 3/5 | I²C pins 3/5 | I²C pins 3/5 |
| LCD | SDA/SCL | I²C pins 3/5 | I²C pins 3/5 | I²C pins 3/5 |

## Option A — Arduino Uno (no extra chip)

Full instructions live in [`ARDUINO_ADC.md`](ARDUINO_ADC.md). Short version:

1. Flash [`arduino/air_sensors/air_sensors.ino`](../arduino/air_sensors/air_sensors.ino).
2. Wire `A0` ← MQ-7, `A1` ← MQ-135, `A2` ← dust `Vo`, `D7` → LED transistor.
3. Connect to the Pi over USB, **or** power the Uno separately and use the GPIO
   UART (`GND` + `TX`→pin 10 + `RX`←pin 8; see the doc for the 5 V→3.3 V divider
   on Arduino TX).
4. Add your user to `dialout`, then set:

```dotenv
ADC_BACKEND=arduino
ARDUINO_PORT=/dev/ttyACM0      # /dev/serial0 for the GPIO UART
ARDUINO_BAUD=115200
ARDUINO_BOOT_SECONDS=2.0       # 0 for the GPIO UART
ARDUINO_VREF=5.0
ARDUINO_ADC_MAX=1023
ARDUINO_DUST_LED=true
MQ_DIVIDER_RATIO=1
```

The Uno converts the analog voltages to 10-bit counts (0–1023) and sends them
over serial. It also pulses the dust LED itself, so the 280 µs sample timing is
not stretched by USB latency. The Uno's ADC accepts 0–5 V, so the MQ outputs
connect directly — no divider.

> **UART wiring is not 5 V-safe on its own.** Arduino `TX` is 5 V; divide it to
> ~3.3 V before the Pi's RX pin. `TX`/`RX` are also the Uno's USB-serial pins, so
> upload the sketch before connecting them.

## Option B — ADS1115 (I²C, if you buy one)

The ADS1115 gives you 4 single-ended channels with 16 bits of resolution. The
ADS1015 is the same pinout at 12 bits.

| ADS1115 pin | Connects to | Board pin |
|---|---|---:|
| `VDD` | 3.3 V | 1 |
| `GND` | GND | 6 |
| `SCL` | GPIO3 / SCL1 | 5 |
| `SDA` | GPIO2 / SDA1 | 3 |
| `ADDR` | GND for `0x48`; see below | 6 |
| `ALRT` | not connected | — |
| `A0` | MQ-7 `AOUT` through divider | — |
| `A1` | MQ-135 `AOUT` through divider | — |
| `A2` | dust `Vo` | — |
| `A3` | spare | — |

**Power the module from 3.3 V, not 5 V.** Most breakout boards pull SDA/SCL up
to `VDD`; with 5 V that would put 5 V on the Pi's I²C pins. At 3.3 V the I²C bus
is safe, and analog inputs must still stay below ~3.6 V, so the MQ divider is
still required.

Address selection with `ADDR`: GND → `0x48`, VDD → `0x49`, SDA → `0x4A`,
SCL → `0x4B`. Detect it with `i2cdetect -y 1`.

The ADS1115 shares the same I²C bus as the BMP280 (`0x76`/`0x77`) and the LCD
(`0x27`/`0x3F`), so all three can stay connected at once.

```dotenv
ADC_BACKEND=ads1115
ADS1X15_ADDRESS=0x48
ADS1X15_I2C_BUS=1
ADS1X15_FULL_SCALE_V=4.096
ADS1X15_DATA_RATE=860
```

`ADS1X15_FULL_SCALE_V` sets the ±range: `4.096` suits 0–3.3 V signals with good
resolution; use `6.144` for a wider range or `2.048` for more precision on
low-level signals. `ADS1X15_DATA_RATE` is samples per second; 860 is the fastest
ADS1115 rate and keeps the dust LED pulse short.

The driver talks to the chip directly over `smbus2` — no Blinka or Adafruit ADC
library needed:

```bash
pip install smbus2
```

## Option C — MCP3008 (only if you already have one)

| MCP3008 pin | Name | Board pin | Pi signal (BCM) |
|---:|---|---:|---|
| 16 | VDD | 1 or 17 | 3V3 |
| 15 | VREF | 1 or 17 | 3V3 |
| 14 | AGND | 6 | GND |
| 9 | DGND | 6 | GND |
| 13 | CLK | 23 | GPIO11 / SCLK |
| 12 | DOUT | 21 | GPIO9 / MISO |
| 11 | DIN | 19 | GPIO10 / MOSI |
| 10 | CS/SHDN | 24 | GPIO8 / CE0 |
| 1 | CH0 | — | ← MQ-7 `AOUT` through divider |
| 2 | CH1 | — | ← MQ-135 `AOUT` through divider |
| 3 | CH2 | — | ← dust `Vo` |
| 4–8 | CH3–CH7 | — | unused |

Run the MCP3008 from **3.3 V**, not 5 V: at 5 V its SPI input threshold rises to
about 3.5 V and the Pi's 3.3 V logic becomes marginal, and `VREF` would no longer
match the ADC range.

```dotenv
ADC_BACKEND=mcp3008
ADC_VREF=3.3
SPI_BUS=0
SPI_DEVICE=0
SPI_SPEED_HZ=1350000
```

## MQ-7 (CO) and MQ-135 (air quality)

Both modules expose the same four pins; only `AOUT` matters here.

| Module pin | Connects to |
|---|---|
| `VCC` | 5 V (your power wiring) |
| `GND` | common ground |
| `AOUT` | Arduino `A0`/`A1` directly, or a divider into ADS1115/MCP3008 |
| `DOUT` | leave unconnected |

**With the Arduino backend, connect `AOUT` straight to `A0`/`A1` and leave
`MQ_DIVIDER_RATIO=1`.** The Uno's ADC accepts 0–5 V.

If you use a 3.3 V ADC instead, `AOUT` can swing to 5 V while the ADC must stay
at or below ~3.3 V (the ADS1115 tolerates only `VDD + 0.3 V` = 3.6 V absolute
maximum). Fit a divider on each output:

```
AOUT ──[10k]──┬──> 3.3 V ADC input (ADS1115 Ax or MCP3008 CHx)
              │
            [20k]
              │
             GND
```

That maps 5.0 V to 3.33 V. Then set:

```dotenv
MQ_SUPPLY_VOLTAGE=5
MQ_DIVIDER_RATIO=1.5      # (10k + 20k) / 20k
MQ_LOAD_RESISTOR_KOHM=10  # check the RL value on your modules
```

If you already built a different divider, compute
`MQ_DIVIDER_RATIO = (Rtop + Rbottom) / Rbottom`. With no divider, leave it at 1
but only trust readings that stay under 3.3 V.

Dust has its own ratio, `DUST_DIVIDER_RATIO`, because your Sharp board is
already conditioned. Leave it at `1` unless you added a divider after it.

## Sharp GP2Y1010AU0F dust sensor

You already have the capacitor/resistor circuit, and only two signal wires leave
the board:

| Sensor signal | Connects to |
|---|---|
| Analog output `Vo` | Arduino `A2` (or ADS1115 `A2`, or MCP3008 CH2/pin 3) |
| LED drive | Arduino `D7` (or Pi GPIO17, board pin 11) |

With `ADC_BACKEND=arduino` and `ARDUINO_DUST_LED=true`, the Uno pulses the LED
for 280 µs and samples `A2` itself, then sends the result over serial. That is
the most accurate option because USB latency never stretches the pulse.

Otherwise the Pi pulses the LED, waits 0.28 ms, reads the ADC, then waits
~9.7 ms.

> **ADS1115 timing note.** A single conversion takes about 1.2 ms at 860 SPS and
> the driver waits ~1.5 ms for it, so the LED stays on for roughly 1.8 ms instead
> of 0.28 ms. The reading is still usable but not datasheet-exact; treat dust
> values as approximate. The MCP3008 and Arduino honour the original timing
> much more closely.

Two possible LED circuits, selected by `DUST_LED_ACTIVE_HIGH` (the Arduino
sketch has its own `DUST_LED_ACTIVE_HIGH` constant at the top):

- **Transistor (recommended).** Arduino `D7`/GPIO17 → 1 kΩ → NPN base,
  emitter → GND, collector → LED cathode, LED anode → 150 Ω → 5 V. Set
  `DUST_LED_ACTIVE_HIGH=true` (sketch: `true`).
- **Direct sink.** 5 V → 150 Ω → LED anode, LED cathode → GPIO17. Set
  `DUST_LED_ACTIVE_HIGH=false` (default). This sinks ~20 mA, above the 16 mA
  recommended maximum.

If dust reads a constant value, try flipping `DUST_LED_ACTIVE_HIGH`; if the
polarity is wrong the LED never emits and the output stays flat.

## BMP280 / HW-611

| Module pin | Board pin | Signal |
|---|---:|---|
| `VCC` / `VIN` | 1 | 3V3 |
| `GND` | 6 | GND |
| `SCL` | 5 | GPIO3 / SCL1 |
| `SDA` | 3 | GPIO2 / SDA1 |

HW-611 boards answer on **0x76 or 0x77** depending on the `SDO` pin. Detect it:

```bash
i2cdetect -y 1     # look for 76 or 77
```

Then set the address you see:

```dotenv
BMP280_I2C_ADDRESS=0x76
```

The code tries the modern `adafruit_bmp280` driver first and falls back to the
legacy `Adafruit_BMP` package. Install one of them (see below).

## 16x2 I2C LCD (optional)

A standard 16x2 display with a PCF8574 backpack uses the same I²C bus as the
BMP280:

| LCD backpack | Board pin | Signal |
|---|---:|---|
| `VCC` | 1 | 3V3 |
| `GND` | 6 | GND |
| `SDA` | 3 | GPIO2 / SDA1 |
| `SCL` | 5 | GPIO3 / SCL1 |

Find the backpack address with `i2cdetect -y 1` — usually `0x27`, sometimes
`0x3F`. Install the driver and enable the display:

```bash
pip install RPLCD smbus2
```

```dotenv
LCD_ENABLED=true
LCD_I2C_BUS=1
LCD_I2C_ADDRESS=0x27
LCD_COLUMNS=16
LCD_ROWS=2
LCD_PAGE_SECONDS=4
```

The display rotates through four pages every `LCD_PAGE_SECONDS`:

| Page | Line 1 | Line 2 |
|---|---|---|
| 1 | `Temp 24.5C` | `Pres 1013hPa` |
| 2 | `CO   12.3ppm` | `AQ   340ppm` |
| 3 | `Dust 35.2ug/m3` | `Vo   0.82V` |
| 4 | `12.9716N` | `77.5946E 9s` |

Pages with no data are skipped, and `n/a` is shown for a missing value. When the
GPS is enabled but has no fix, the last page says `GPS waiting`.

## Phone GPS over Wi-Fi

The Pi reads NMEA sentences directly from the phone, so **gpsd is not needed**.
Two directions are supported:

| `GPS_MODE` | Who listens | Works with |
|---|---|---|
| `tcp` (default) | the phone | gpsdRelay "TCP server", Share GPS "NMEA / TCP / Listen" |
| `udp` | the Pi | GPSd Forwarder (the app from the KM4ACK video), gpsdRelay UDP |

Apps:

- **gpsdRelay** (F-Droid, free, open source, actively maintained) —
  https://f-droid.org/packages/io.github.project_kaat.gpsdrelay/
- **GPSd Forwarder** (F-Droid, the app in the KM4ACK video) —
  https://f-droid.org/packages/io.github.tiagoshibata.gpsdclient/
- **Share GPS** (Google Play, optional premium for multiple connections) —
  https://play.google.com/store/apps/details?id=com.jillybunch.shareGPS
- **GPS 2 IP** (iPhone) — https://apps.apple.com/us/app/gps-2-ip/id408625926

### gpsdRelay, TCP mode (recommended)

1. Install gpsdRelay, grant background location access, wait for a 3D fix.
2. Add a **TCP server** on a port, e.g. `10110`, and press play.
3. Put the phone and the Pi on the same Wi-Fi network.
4. Read the phone's Wi-Fi IP (Android: Settings → Network → Wi-Fi → details).
5. Test from the Pi:

   ```bash
   nc -v 192.168.1.50 10110
   ```

   You should see lines starting with `$GNGGA` / `$GNRMC`.

6. Configure:

   ```dotenv
   GPS_ENABLED=true
   GPS_MODE=tcp
   GPS_HOST=192.168.1.50
   GPS_PORT=10110
   ```

### GPSd Forwarder, UDP mode

This is the approach in the video, minus gpsd.

1. In the app, enter the **Pi's IP** and a port, e.g. `29998`, then start.
2. Configure the Pi to listen:

   ```dotenv
   GPS_ENABLED=true
   GPS_MODE=udp
   GPS_PORT=29998
   ```

3. NMEA datagrams arrive on that UDP port and are parsed in-process.

### Notes

- The two devices must be able to reach each other. A phone hotspot, a shared
  router, or the Pi as its own access point all work; no internet is required.
- Phone IPs change. Reserve a DHCP lease, or use the hotspot's fixed gateway
  address, otherwise `GPS_HOST` needs editing after every reconnect.
- Android may throttle background location. Use an app with a foreground
  service (gpsdRelay) and disable battery optimisation for it.
- The fix is considered valid for `GPS_MAX_AGE_SECONDS` (default 30). After
  that, readings keep uploading from the last configured coordinates instead
  of stale GPS data.
- `location_name` is required by the API whenever coordinates are present. The
  code sends `AEROSENSE_SITE_NAME` if set, otherwise `GPS_LOCATION_NAME`
  (default `Mobile GPS`).
- GPS altitude is only used when the BMP280 did not supply one.

## Enable the interfaces

**Arduino backend:** for USB, no Pi interface needs enabling — plug it in and
add your user to `dialout` once (log out/in afterwards):

```bash
sudo usermod -aG dialout "$USER"
ls /dev/ttyACM0            # or /dev/ttyUSB0 for CH340 clones
```sudo usermod -aG dialout "$USER"
ls /dev/ttyACM0 

For the GPIO UART (Uno on its own power supply), enable the serial hardware and
disable the serial login console:

```bash
sudo raspi-config
# Interface Options -> Serial Port
#   login shell over serial?      -> No
#   serial port hardware enabled? -> Yes
sudo reboot
ls -l /dev/serial0
```

**I²C** is still needed for the BMP280 and the optional LCD. Enable **SPI**
only if you are using the MCP3008:

```bash
sudo raspi-config          # Interface Options -> I2C -> Yes
                           # Interface Options -> SPI -> Yes   (MCP3008 only)
sudo reboot
i2cdetect -y 1             # ADS1115 at 0x48, BMP280 at 0x76/0x77, LCD at 0x27/0x3F
ls /dev/spidev0.0          # only needed for ADC_BACKEND=mcp3008
```

Install everything the Pi needs (uses the pinned list in the repository):

```bash
cd raspberry_pi
pip install -r requirements.txt
```

That installs `pyserial` (Arduino), `smbus2` (ADS1115 + LCD), `gpiozero`
(dust LED when the Pi drives it), `spidev` (MCP3008),
`adafruit-circuitpython-bmp280` + `adafruit-blinka` (BMP280), and
`python-dotenv`/`requests` for the client. Uncomment `RPLCD` in
`requirements.txt` if you enable the LCD.

## Verify the wiring

For the **Arduino**, full instructions are in
[`ARDUINO_ADC.md`](ARDUINO_ADC.md); the short check is:

```bash
cd raspberry_pi
python3 - <<'EOF'
from adc import create_adc

adc = create_adc()
print("ADC:", adc.label)
for channel in range(3):
    print(f"A{channel}={adc.voltage(channel):.3f}V")
print(f"dust={adc.dust_voltage():.3f}V")
adc.close()
EOF
```

For the **ADS1115** (run from `raspberry_pi/` so the local driver is importable):

```bash
cd raspberry_pi
python3 - <<'EOF'
import time
from adc import create_adc

adc = create_adc()
print("ADC:", adc.label)
for _ in range(5):
    print("  ".join(f"A{ch}={adc.voltage(ch):.3f}V" for ch in range(3)))
    time.sleep(0.5)
adc.close()
EOF
```

For the **MCP3008**:

```bash
python3 - <<'EOF'
import spidev, time
spi = spidev.SpiDev(); spi.open(0, 0); spi.max_speed_hz = 1_350_000
for _ in range(5):
    for ch in range(3):
        r = spi.xfer2([1, (8 + ch) << 4, 0])
        print(ch, ((r[1] & 3) << 8) + r[2], end="  ")
    print(); time.sleep(0.5)
EOF
```

- Channel stuck at `0` → sensor not powered or divider miswired.
- MCP3008 channel pinned at `1023`, or ADS1115 stuck at its full-scale limit →
  input above the ADC's range; fix the divider.
- Dust channel flat while dust varies → LED polarity or driver.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| ADC channels read 0 | Sensor or ADC unpowered, divider miswired, missing common ground |
| MCP3008 channels pinned at `1023` | Analog input above `ADC_VREF`; missing divider |
| ADS1115 channels pinned near full scale | Input above `VDD + 0.3 V` (~3.6 V at 3.3 V supply); missing divider |
| `ADS1115` absent from `i2cdetect` | I²C disabled, module unpowered, SDA/SCL swapped, `ADDR` strap selects another address |
| `addr 0x48` shown as `UU` | Another driver claimed the address; disable it or re-strap `ADDR` |
| `RuntimeError: The 'smbus2' package is required` | `pip install -r raspberry_pi/requirements.txt` |
| `RuntimeError: ADC is disabled (ADC_BACKEND=none)` | Set `ADC_BACKEND=arduino` (or `ads1115`/`mcp3008`) in `.env` |
| `Unknown ADC_BACKEND=...` | Accepted values are `arduino`, `mcp3008`, `ads1115`, `ads1015`, `none` |
| `ImportError: No module named spidev` | You are on `ADC_BACKEND=mcp3008` without SPI packages; switch to `arduino` |
| `No AERO-HUB reply on /dev/ttyACM0` | Sketch not flashed, wrong port (`ttyUSB0` for clones), or user not in `dialout` |
| `Permission denied: '/dev/ttyACM0'` | `sudo usermod -aG dialout "$USER"`, then log out and back in |
| `The 'pyserial' package is required` | `pip install -r raspberry_pi/requirements.txt` |
| Arduino values always `1023` | Input above the Uno's 5 V reference; check the sensor supply |
| Arduino values always `0` | Sensor unpowered, missing common ground, wrong analog pin |
| Values jump around | Missing common ground, weak supply, long unshielded wires |
| BMP280 missing from `i2cdetect` | I²C disabled, wrong address, SDA/SCL swapped |
| LCD blank but visible at `0x27` | `LCD_ENABLED` false, wrong address, backlight jumper |
| LCD shows blocks | I²C bus contention or wrong address |
| `GPS disabled: GPS_HOST is required` | `GPS_MODE=tcp` without `GPS_HOST` |
| GPS page stays `GPS waiting` | app not streaming, wrong IP/port, phone and Pi on different networks |
| GPS fix but no map marker | `location_name` blank and no `GPS_LOCATION_NAME` |
| CO/AQ `n/a` | calibration values (`MQ7_*`, `MQ135_*`) are intentionally blank |
| Dust `n/a` | `DUST_ZERO_VOLTAGE` / `DUST_UG_M3_PER_V` not calibrated |

Estimated concentrations are only reported after calibration; the backend omits
them rather than publishing false zeroes.
