/*
 * AERO-HUB Arduino Uno sensor bridge
 * ----------------------------------
 * The Raspberry Pi has no analog inputs. This sketch turns an Arduino Uno
 * (or Nano) into a 10-bit ADC and answers requests over USB serial.
 *
 * It also drives the Sharp GP2Y1010AU0F dust-sensor LED itself, so the
 * 280 us sample delay stays precise instead of being stretched by USB/serial
 * latency.
 *
 * Wiring
 * ------
 *   Arduino A0  <- MQ-7   AOUT   (direct; the Uno ADC is 5 V tolerant)
 *   Arduino A1  <- MQ-135 AOUT   (direct)
 *   Arduino A2  <- Sharp dust Vo
 *   Arduino D7  -> 1 kOhm -> NPN base  (dust LED transistor, same board)
 *   Arduino GND <-> Pi GND and sensor GND
 *   Arduino USB -> Raspberry Pi USB
 *
 * No USB? Power the Uno separately and use the Pi GPIO UART instead:
 *   Arduino GND      -> Pi GND (pin 6)
 *   Arduino TX (1)   -> 1k/2k divider -> Pi RX/GPIO15 (pin 10)
 *   Arduino RX (0)   <- Pi TX/GPIO14 (pin 8)
 * Upload the sketch over USB before connecting pins 0/1.
 *
 * Protocol (115200 baud, newline terminated, ASCII)
 * -------------------------------------------------
 *   I        ->  AEROHUB,1          firmware identity / handshake
 *   R0..R5   ->  V,<0..1023>        analogRead(A0..A5)
 *   D        ->  D,<0..1023>        pulse the dust LED, then sample A2
 *   L0 / L1  ->  L,0 / L,1          LED drive polarity (0=active-low, 1=active-high)
 *
 * Anything else returns ERR,command.
 *
 * Flash with the Arduino IDE: Tools -> Board -> Arduino Uno,
 * Tools -> Port -> the port that appeared when you plugged it into the Pi.
 */

const uint8_t DUST_LED_PIN = 7;
const uint8_t DUST_SENSE_PIN = A2;
// true  = transistor/active-high drive (base pulled HIGH turns the LED on)
// false = active-low drive (PNP high-side or direct wiring)
// The Pi can change this at startup with the L0/L1 command, so
// ARDUINO_DUST_LED_ACTIVE_HIGH in .env matches the actual wiring.
bool dustLedActiveHigh = true;

const unsigned long SERIAL_BAUD = 115200;
const uint8_t MAX_CHANNEL = 5;  // A0..A5 on an Uno/Nano

char buffer[16];
uint8_t length = 0;

void dustLed(bool on) {
  bool level = dustLedActiveHigh ? on : !on;
  digitalWrite(DUST_LED_PIN, level ? HIGH : LOW);
}

void setup() {
  pinMode(DUST_LED_PIN, OUTPUT);
  dustLed(false);
  Serial.begin(SERIAL_BAUD);
  Serial.println(F("AEROHUB,1"));
}

void loop() {
  while (Serial.available() > 0) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (length > 0) {
        buffer[length] = '\0';
        handleCommand();
        length = 0;
      }
    } else if (length < sizeof(buffer) - 1) {
      buffer[length++] = c;
    }
  }
}

void handleCommand() {
  char command = buffer[0];

  if (command == 'I') {
    Serial.println(F("AEROHUB,1"));
    return;
  }

  if (command == 'R') {
    int channel = atoi(buffer + 1);
    if (channel < 0 || channel > MAX_CHANNEL) {
      Serial.println(F("ERR,channel"));
      return;
    }
    int raw = analogRead(A0 + channel);
    Serial.print(F("V,"));
    Serial.println(raw);
    return;
  }

  if (command == 'L') {
    int mode = atoi(buffer + 1);
    dustLedActiveHigh = (mode != 0);
    dustLed(false);
    Serial.print(F("L,"));
    Serial.println(dustLedActiveHigh ? 1 : 0);
    return;
  }

  if (command == 'D') {
    dustLed(true);
    delayMicroseconds(280);           // datasheet sample point
    int raw = analogRead(DUST_SENSE_PIN);
    delayMicroseconds(40);
    dustLed(false);
    delay(10);                        // 10 ms between LED pulses
    Serial.print(F("D,"));
    Serial.println(raw);
    return;
  }

  Serial.println(F("ERR,command"));
}
