# DISCOVERY — team repo survey for T11 (Hall firmware) and CVT import

Date: 2026-10-15. Read-only survey; nothing in the team repo was modified (no checkout, no fetch, no build).
Team repo: `../MU-Eagle-RacingDAC` (note: **not** `../MU-EagleRacing-DAC`; that path does not exist).
Surveyed at `main` = `bd6e5dc` (2026-10-07), plus remote branches `hall-effect-sensor`, `screen_testing`, `3D-gyro-accel-test`.
Remote refs are as of clone time (no `FETCH_HEAD`; `.git/HEAD` mtime 2026-10-15 18:27). Anything pushed to GitHub after that is not reflected.

Labels: **[V]** verified this session (method given) · **[P]** prior knowledge, not re-checked · **[I]** inference.

## Answer for T11

**No existing Hall/RPM sketch exists. T11 takes the "else" branch: write `hall_logger` from scratch.** [V: `git grep` for hall|rpm|pulse|magnet|attachInterrupt|pulseIn|micros|SD.h|cvt over every branch; only hit is the MLX90632 temperature logger.]

But the T11 defaults in the spec (`cvt_primary D2`, `cvt_secondary D3`, `LOG_TO_SD 1`) do not match this hardware. **T11 should not start until the DAQ lead answers Q1–Q3 below.**

| Spec default | What the hardware says | Status |
|---|---|---|
| `cvt_primary` on D2 | Schematic routes `PRIMARY_CVT` to **GPIO23**. D2 (GPIO2) is already `BRAKE_SENSE` [V] and is an ESP32 boot-strapping pin [P] | conflict |
| `cvt_secondary` on D3 | Schematic routes `SECONDARY_CVT` to **GPIO25** [V]. GPIO3 is RX0, the USB serial port [V: pad name `RX0`] | conflict |
| `LOG_TO_SD 1` | No SD card or socket on the schematic or PCB [V: component list]. The existing logger uses on-chip **LittleFS** [V] | conflict |

"D2/D3" reads like Arduino Uno/Nano naming [I]. The board is an ESP32.

## Findings

### 1. MCU is an ESP32 DevKit V1, not an AVR Arduino
- Schematic symbol `ESP32-DEVKIT-V1:ESP32-DEVKIT-V1` (U6) [V].
- Every sketch is ESP32-only: `Wire.begin(21, 22)`, `LittleFS.begin(true)`, `WiFi.h` [V].
- Serial runs at 115200 in all sketches [V].

### 2. Hall channel → GPIO map (schematic design intent)
Source: pad nets in `EagleRacingKi-Cad.kicad_pcb`, U6 pin functions [V: parsed with a script]. This matches the schematic labels [V].

| Net label | ESP32 pin | NEST channel |
|---|---|---|
| `PRIMARY_CVT` | GPIO23 | `cvt_primary` |
| `SECONDARY_CVT` | GPIO25 | `cvt_secondary` |
| `FL_WHEEL_SPEED` | GPIO27 | (future) |
| `FR_WHEEL_SPEED` | GPIO32 | (future) |
| `2SP_GEARBOX` | GPIO26 | (future) |
| `BR_WHEEL_SPEED`, `BL_WHEEL_SPEED` | none: on the PCB at `38df2ec` only, not in the schematic | (future) |
| `BRAKE_SENSE` | GPIO2 | not Hall |

- None of these is an input-only pin (GPIO34–39), so internal pull-ups and pin-change interrupts are available on all of them [P].
- Also taken: GPIO16/17 (UART2 → `J2 UART TO SCREEN`), GPIO5/18/19 (MAX31855 SPI), GPIO21/22 (I²C) [V].

### 3. Sensor: GS100701, powered at 3V3, no pull-ups
- All five schematic Hall parts (U1–U5) are `GS100701 Hall Effect` on symbol `Sensor_Magnetic:A1101xUA`, footprint `TO-92S` (used as a 3-hole wire landing) [V].
- Pinout: pin 1 Vcc = **`/3V3`**, pin 2 GND, pin 3 Vout = signal net [V: PCB pads at `38df2ec`].
- There is no pull-up resistor on any Hall output in the schematic. R1/R2/C1/D1 belong to the brake-sense divider [V].
- GS100701 is a ZF geartooth sensor: supply about **4.5–24 V**, current-*sinking* output that needs a pull-up, about 15 kHz max, about 1.5 mm air gap. [Looked up via search-result summaries of distributor listings. The ZF/RS datasheet PDF was image-only and unreadable here, and two distributor pages returned 403/404. Treat as likely, not confirmed.]
- **Consequence [I]:** at 3V3 the sensor is probably below its minimum supply and may not switch. The firmware must enable `INPUT_PULLUP`, or the board needs external pull-ups to 3V3. Never pull up to 5V on an ESP32 pin [P].
- **Consequence [I]:** a geartooth sensor is designed for a ferrous target. The spec's "drill + magnet" bench test may not reflect how the sensor behaves on the car. Confirm what target is mounted on each CVT sheave.

### 4. Current PCB has no place to connect any Hall sensor
- At `main` (`bd6e5dc`, "+increased pcb length, mounting holes") the PCB has **no Hall footprints**. U1–U5, U10 and U11 were present at `adb7db9` and `38df2ec` and are gone at `bd6e5dc` [V: footprint diff across the three commits].
- The schematic still contains U1–U5 with a valid footprint and `on_board yes` [V]. The schematic and PCB are out of sync. The commit message doesn't mention the removal, so it was probably accidental [I].
- Traces for the Hall nets remain with nothing on the other end. `PRIMARY_CVT` has only 2 segments while the others have 9–10 [V], so its routing looks incomplete [I].
- Branch `hall-effect-sensor` is an ancestor of `main` (`585ebd4`, 2026-02-22, "Added ESP32"). **It contains no Hall work** [V: `git merge-base --is-ancestor`, empty `main..` log].

### 5. ESP32 footprint does not match the DevKit symbol (hardware, outside NEST scope)
- U6 is placed with `RF_Module:ESP32-WROOM-32`, an SMD module footprint with 1.27 mm pad pitch [V]. Its pad numbers carry DevKit-V1 pin names (pad 1 = 3V3, pad 2 = GND) [V].
- A DevKit V1 (2.54 mm headers) cannot mount on this footprint. On a bare WROOM-32, pad 1 is GND and pad 2 is 3V3 [P], so supply would be reversed if a module were soldered there [I].
- Effect on NEST: the GPIO numbers in §2 are **design intent from the symbol**. Their physical pads on this PCB are unverified. For the T11 bench test (DevKit on a breadboard) the GPIO numbers are what matter.

### 6. Logging precedent and storage budget
- `Temperature_Sensor_Code.ino` is the only logger. It appends CSV to LittleFS `/cvt_temp.csv` with header `Time_ms,ObjectTempC,AmbientTempC`, opens and closes the file on every write, logs at 1 Hz, and dumps the file over serial when it receives `r` [V]. This is a reasonable skeleton for `hall_logger` (LittleFS + serial dump) [I].
- The repo has no partition table, so the board is presumably on the Arduino-ESP32 default: about **1.44 MB** for the filesystem on 4 MB flash [P].
- Size of 2 channels × 5 h (NF-06) [V: computed; line lengths are examples because LINE_FORMAT v1 is not written yet]:

  | Line example | 1 Hz/ch | 5 Hz/ch | 10 Hz/ch |
  |---|---|---|---|
  | `14400000,1,1234567,12345` (25 B) | 0.90 MB ✓ | 4.5 MB ✗ | 9.0 MB ✗ |
  | `14400000,cvt_secondary,1234567,12345` (37 B) | 1.33 MB ✓ (tight) | 6.7 MB ✗ | 13.3 MB ✗ |

  Without an SD card, on-board flash only covers about 1 Hz per channel for a full race [I].

### 7. Telemetry path that already exists (relevant to F-14/F-15 only)
- `screen_testing` branch: the sensor ESP32 joins a Wi-Fi AP hosted by a CrowPanel display ESP32 and sends JSON over a WebSocket on port 81 at 10 Hz (IMU data only) [V]. Wi-Fi credentials are hard-coded in the sketch; they are not copied here.
- The current PCB instead routes UART2 to `J2 UART TO SCREEN` [V].
- Neither path is used in Phase 1 (NF-01 offline). Note them for Phase 3 ingest.

### 8. Not in the team repo (must come from the DAQ lead, goes into NEST config)
- `pulses_per_rev` for each CVT channel: number of magnets or teeth on each sheave [V: absent].
- Tire circumference for future wheel-speed distance [V: absent].
- Expected CVT ratio band and the secondary-rpm floor (`cvt_ratio_band`, `cvt_min_secondary_rpm`) [V: absent]. Per spec, leave unset, which means no flags.

## Questions for DAQ lead (blocking T11)

1. **Pins:** use the schematic's GPIO23 (`cvt_primary`) and GPIO25 (`cvt_secondary`) instead of the spec's D2/D3? (Recommended: yes.)
2. **Storage:** is there an SD module planned that isn't in the schematic? If not, does `LOG_TO_SD` become LittleFS, and is about 1 Hz per channel acceptable? Or does the board need a larger flash partition or an SD socket?
3. **Sensor supply:** GS100701 appears to need ≥4.5 V. Should Vcc move to the `5V+` rail with the output pulled up to 3V3 (internal or external), or are the sensors being swapped for a 3V3-rated part?
4. **Target:** is each CVT sheave read with magnets or ferrous teeth, and how many per revolution?
5. **PCB:** was removing the Hall footprints in `bd6e5dc` intentional? Is the ESP32-WROOM-32 footprint under U6 intended?

## TODOs proposed for NEST (not applied; SPEC.md is regenerated from the RFC)

- RFC/spec T11: replace `D2`/`D3`/`LOG_TO_SD 1` with the answers to Q1–Q2.
- `protocol/LINE_FORMAT.md`: decide whether `ch` is a name (`cvt_primary`) or an index. This affects the storage budget in §6. Also decide whether a header line is allowed (the existing logger writes one).
- Config: `pulses_per_rev` has no default. Import should refuse, or warn loudly, when it is unset rather than assume 1.

## Method (reproducible, read-only)

```
git -C ../MU-Eagle-RacingDAC log --all --date=short
git -C ../MU-Eagle-RacingDAC merge-base --is-ancestor origin/hall-effect-sensor main
git -C ../MU-Eagle-RacingDAC grep -iE 'hall|rpm|pulse|magnet|attachInterrupt|SD\.h' <each ref>
git -C ../MU-Eagle-RacingDAC show <commit>:EagleRacingKi-Cad/EagleRacingKi-Cad.kicad_pcb   # parsed pad→net per footprint
```
No `kicad-cli` is installed. Nets were taken from pad `(net …)` entries in the PCB file and from schematic labels, not from an ERC/netlist export.
