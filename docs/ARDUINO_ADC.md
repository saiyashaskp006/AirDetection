# Using an Arduino Uno as the ADC

The Raspberry Pi has no analog inputs. Instead of buying an MCP3008 or ADS1115,
you can use an Arduino Uno you already own: it performs the analog-to-digital
conversion and sends the resulting **numbers** to the Pi over USB **or** over the
Pi's GPIO UART (TX/RX), so the Uno can have its own power supply.

> A single digital pin cannot carry a sensor value — it is only on or off. The
> Uno must send the converted value over serial. That is exactly what
> `ADC_BACKEND=arduino` does.

```
MQ-7 AOUT  ──────────► A0 ┐
MQ-135 AOUT ─────────► A1 ├─ Arduino Uno ──USB──► Raspberry Pi
Dust Vo    ──────────► A2 ┘        ▲
                                   │  (or GND + TX/RX, no USB)
Dust LED drive ──► D7 ── 1kΩ ── NPN base
```

The Uno's ADC is 5 V tolerant, so the MQ outputs connect **directly** — no
10 kΩ/20 kΩ divider is needed with this backend. Keep `MQ_DIVIDER_RATIO=1`.

## Wiring

| Signal | From | To |
|---|---|---|
| MQ-7 analog | MQ-7 `AOUT` | Arduino `A0` |
| MQ-135 analog | MQ-135 `AOUT` | Arduino `A1` |
| Dust analog | GP2Y1010AU0F `Vo` | Arduino `A2` |
| Dust LED control | LED transistor base (through 1 kΩ) | Arduino `D7` |
| Ground | every sensor GND | Arduino `GND` (common with the Pi) |
| Data (USB) | Arduino USB port | Raspberry Pi USB port |
| Data (UART) | Arduino `TX`/`RX` (pins 1/0) | Pi `RX`/`TX` (pins 10/8) + GND, see the UART section |
| BMP280 / LCD | SDA/SCL | Pi I²C pins 3/5, as before |

The dust LED circuit itself does not change — only its control wire moves from
Pi GPIO17 (board pin 11) to Arduino `D7`. If your driver is active-low (PNP or
direct wiring), set `ARDUINO_DUST_LED_ACTIVE_HIGH=false` in `.env`; the Pi sends
`L0` to the sketch at startup. Reflash the current sketch so it accepts that
command.

> **Power.** USB lets the Pi power the Uno, but two MQ heaters plus the dust LED
> can approach the port's current budget. If the Pi resets or the serial link
> drops, use a powered USB hub, or power the Uno separately and switch to the
> GPIO UART described below.

## 1. Flash the sketch

Open [`arduino/air_sensors/air_sensors.ino`](../arduino/air_sensors/air_sensors.ino)
in the Arduino IDE:

1. **Tools → Board → Arduino Uno**
2. **Tools → Port →** the port that appears when the Uno is plugged into your
   computer
3. Upload.

The sketch answers a simple line-based protocol at 115200 baud:

| Command | Reply | Meaning |
|---|---|---|
| `I` | `AEROHUB,1` | identity / handshake |
| `R0` … `R5` | `V,<0..1023>` | `analogRead(A0..A5)` raw count |
| `D` | `D,<0..1023>` | pulse the dust LED, sample `A2` |
| `L0` / `L1` | `L,0` / `L,1` | dust LED active-low / active-high |

## 2. Plug it into the Pi and find the port

```bash
ls /dev/ttyACM* /dev/ttyUSB*
```

- Official Uno / ATmega16U2: `/dev/ttyACM0`
- CH340 clones: `/dev/ttyUSB0`

Give your user access once, then log out and back in:

```bash
sudo usermod -aG dialout "$USER"
```

Install the serial package (already in `raspberry_pi/requirements.txt`):

```bash
pip install pyserial
```

## 3. Configure

In `raspberry_pi/.env` (and `backend/.env` for direct mode):

```dotenv
ADC_BACKEND=arduino
ARDUINO_PORT=/dev/ttyACM0     # or /dev/serial0 for the GPIO UART
ARDUINO_BAUD=115200
ARDUINO_BOOT_SECONDS=2.0      # 0 for the GPIO UART
ARDUINO_VREF=5.0
ARDUINO_ADC_MAX=1023
ARDUINO_DUST_LED=true
# true = NPN low-side/active-high, false = PNP high-side/active-low.
# The Pi sends this to the sketch with L0/L1 at startup.
ARDUINO_DUST_LED_ACTIVE_HIGH=true

MQ_DIVIDER_RATIO=1
DUST_DIVIDER_RATIO=1
```

`ARDUINO_DUST_LED=true` means the Uno drives the dust LED and takes the sample
itself, so the 280 µs timing is accurate. The Pi does not need GPIO for the dust
sensor in this mode. Set `ARDUINO_DUST_LED_ACTIVE_HIGH=false` for a PNP
high-side/active-low driver; reflash the current sketch so it accepts the L0/L1
polarity command. If the dust voltage stays near zero, check the LED polarity,
the 150 Ω LED resistor, and the transistor wiring.

If you leave the LED control wire on Pi GPIO17 instead, set
`ARDUINO_DUST_LED=false`: the Pi pulses the LED and reads `A2` over serial. That
works, but the pulse is stretched by USB latency, so dust values are less
accurate. In that mode the Pi also needs `gpiozero`.

`ARDUINO_VREF` is the Uno's actual 5 V rail. USB power is usually 4.75–5.1 V;
measure the 5 V pin with a multimeter if CO/dust values look systematically off.

## Using the GPIO UART instead of USB (recommended for your power budget)

If you do not want the Uno drawing current from the Pi's USB rail, power the Uno
from its own 5 V supply and carry data over the 40-pin header UART. You need
three wires and no USB cable:

| Arduino | Raspberry Pi | Note |
|---|---|---|
| `GND` | `GND`, board pin 6 | **required** common ground |
| `TX` (pin 1, 5 V logic) | `GPIO15` / RXD, board pin 10 | must be divided to 3.3 V |
| `RX` (pin 0) | `GPIO14` / TXD, board pin 8 | direct usually works; a level shifter is safer |
| `5V` / `VIN` | own 5 V supply | do not power from the Pi |

Cross the lines: Arduino **TX → Pi RX**, Arduino **RX ← Pi TX**.

Arduino TX is 5 V and the Pi's GPIOs are **not** 5 V tolerant. Add a divider:

```
Arduino TX (pin 1) ──[1 kΩ]──┬── Pi GPIO15 / RX (pin 10)
                             │
                           [2 kΩ]
                             │
                            GND
```

That gives 5 × 2/(1+2) = **3.33 V**. Pi TX (3.3 V) into the Uno's RX is
normally read as HIGH (the Uno threshold is ~3.0 V); use a 3.3→5 V level
shifter if you want full margin.

Enable the UART (and turn off the serial login console, or its text will
interleave with the protocol):

```bash
sudo raspi-config
# Interface Options -> Serial Port
#   "login shell over serial?"        -> No
#   "serial port hardware enabled?"   -> Yes
sudo reboot
ls -l /dev/serial0
```

On a Pi 3/4 you can additionally add `dtoverlay=disable-bt` to
`/boot/firmware/config.txt` so `/dev/serial0` is the better PL011 UART
(`ttyAMA0`) instead of the mini-UART. A Pi 5 already has an independent GPIO
UART.

Then point the client at it:

```dotenv
ARDUINO_PORT=/dev/serial0
ARDUINO_BOOT_SECONDS=0
```

Opening a GPIO UART does not reset the Uno, so the 2 s USB boot delay is not
needed. The sketch is unchanged — it still answers on the hardware UART
(pins 0/1).

> **Upload first, wire second.** Pins 0/1 are shared with the Uno's USB-serial
> chip. Flash the sketch over USB before connecting the TX/RX wires.

> **Power note.** The MQ heaters draw ~150 mA each. Power the Uno and the sensor
> 5 V rail from a supply that can deliver at least 1 A, and keep the grounds
> common. If you prefer to stay on USB, a **powered USB hub** between the Pi and
> the Uno removes the load from the Pi's PSU while keeping `/dev/ttyACM0`.

## 4. Verify

From the repository root:

```bash
cd raspberry_pi
python3 - <<'EOF'
from adc import create_adc

adc = create_adc()
print("backend:", adc.label)
for channel in range(3):
    print(f"A{channel}: {adc.voltage(channel):.3f} V")
print(f"dust (Arduino-timed): {adc.dust_voltage():.3f} V")
adc.close()
EOF
```

Or talk to it by hand:

```bash
python3 -m serial.tools.miniterm /dev/ttyACM0 115200   # USB
# python3 -m serial.tools.miniterm /dev/serial0 115200  # GPIO UART
# type I, R0, R1, D  (Ctrl+] to quit)
```

## Timing

The Uno holds the dust LED on for 280 µs, starts `analogRead`, then turns the
LED off — the sample point matches the GP2Y1010AU0F datasheet much better than
a reading that travels over USB first. The whole exchange takes about 10 ms
because the sketch enforces the required gap between LED pulses.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `No AERO-HUB reply on /dev/ttyACM0` | sketch not uploaded, wrong port, or missing `dialout` group |
| `Permission denied: '/dev/ttyACM0'` | `sudo usermod -aG dialout "$USER"`, then log out/in |
| Port disappears when the Pi boots | Uno powered from a port that is not enabled; use a powered hub |
| `The 'pyserial' package is required` | `pip install pyserial` |
| Values always 1023 | input above the Uno's 5 V reference; check the sensor supply |
| Values always 0 | sensor not powered, missing common ground, wrong analog pin |
| Dust always 0 | LED control wire still on Pi GPIO17 instead of Arduino D7, or inverted `ARDUINO_DUST_LED_ACTIVE_HIGH` (try `L0`/`L1` in the serial test) |
| Readings noisy | USB-powered sensors; add a 100 µF capacitor across the 5 V rail and keep the grounds common |
| `ERR,channel` replies | channel outside A0–A5; check `MQ7_ADC_CHANNEL` / `MQ135_ADC_CHANNEL` / `DUST_ADC_CHANNEL` |
| `/dev/serial0` missing | UART not enabled in `raspi-config`; reboot after enabling |
| Garbage or login text on the UART | serial login console still enabled (must be **No**), or baud mismatch |
| No reply on `/dev/serial0` but USB works | TX/RX not crossed, missing common ground, or Pi RX missing the divider |
| Pi reboots or UART drops under load | Uno/sensors drawing from the Pi 5 V rail; use a separate supply or powered hub |
| ATmega gets hot / sketch uploads fail after wiring | pins 0/1 are shared with USB serial; disconnect the UART wires while uploading |
