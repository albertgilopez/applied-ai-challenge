# KX-100 RF Power Meter: Programming Manual

Kestrel Microwave KX-100, firmware 1.02. Thermocouple sensor head, single channel, SCPI over a
message-based session. This manual covers remote control, the specifications needed for an
uncertainty budget, and the limits of the instrument.

## 1. Session

- One command per write. Commands are case-insensitive; short forms (capitals in the long form)
  and long forms are both accepted, for example `SENS:FREQ` or `SENSe:FREQuency`.
- The termination character is `\n`. A write may end with it; responses end with it and the
  session removes it before returning the response.
- A query (header ending in `?`) leaves one response pending. Read it before the next write:
  writing first discards the response and queues error -410.
- Reading with no response pending times out and queues error -420.
- Numeric responses use `+`/`-` signs and scientific notation where shown below.

## 2. Command reference

| Command | Parameter | *RST default | Description |
|---|---|---|---|
| `*IDN?` | none | n/a | Returns `maker,model,serial,firmware`. |
| `*RST` | none | n/a | Restores the defaults in this table and loads the reset reading -100.00 dBm into the measurement buffer. Does not clear the error queue. |
| `*CLS` | none | n/a | Clears the error queue. |
| `*OPC?` | none | n/a | Returns `1` when all pending operations, including a measurement, are complete. |
| `SYST:ERR?` | none | n/a | Returns the oldest queued error as `code,"text"`, or `0,"No error"`. |
| `SENS:FREQ <freq>` | 10 MHz to 18 GHz | 50 MHz | Signal frequency. Selects the calibration factor applied to the reading. |
| `SENS:FREQ?` | none | n/a | Returns the frequency in Hz, for example `+2.400000000E+09`. |
| `SENS:AVER:COUN <n>` | integer 1 to 1024 | 1 | Number of readings averaged into one measurement. |
| `SENS:AVER:COUN?` | none | n/a | Returns the averaging count, for example `+16`. |
| `CONF:POW:RANG <AUTO\|LOW\|HIGH>` | AUTO, LOW, HIGH | AUTO | Measurement range. |
| `CONF:POW:RANG?` | none | n/a | Returns `AUTO`, `LOW` or `HIGH`. |
| `INIT` | none | n/a | Starts one measurement with the current settings. |
| `FETC?` | none | n/a | Returns the measurement buffer in dBm with two decimals, for example `-23.47`. |

Frequency parameters accept a plain number in Hz (`2400000000`, `2.4e9`) or a suffix: `HZ`,
`KHZ`, `MHZ`, `GHZ` (`2.4 GHZ`). Values outside the band are refused with -222 and the previous
setting is kept.

Frequency range: 10 MHz to 18 GHz

**`FETC?` does not measure.** It returns the result of the last completed `INIT`. After power-on
or `*RST` it returns the reset reading -100.00 dBm. After a setting is changed it keeps returning
the previous measurement, taken with the previous settings, until the next `INIT`.

### Ranges

- LOW: -60 dBm to -10 dBm. An input above -10 dBm on LOW over-ranges: `FETC?` returns
  `+9.90E+37` and error 201 is queued.
- HIGH: -30 dBm to +20 dBm. Below -30 dBm its zero offset dominates the reading.
- AUTO: LOW for inputs below -20 dBm, HIGH otherwise.

## 3. Required measurement sequence

1. `*CLS` (optionally `*RST` first).
2. `SENS:FREQ <signal frequency>`. The meter cannot detect the signal frequency; if it is not
   set, the calibration factor of the wrong frequency is applied and the reading is biased.
3. `SENS:AVER:COUN <n>`. Noise falls as one over the square root of the count.
4. `CONF:POW:RANG AUTO` unless a fixed range is required.
5. `INIT`.
6. `*OPC?` and wait for `1`.
7. `FETC?` and parse the value in dBm.
8. `SYST:ERR?` until it returns `0,"No error"`. Any other code means a setting was refused or the
   measurement is not valid; do not use the reading.

## 4. Sensor calibration factor

Applied internally at the frequency set with `SENS:FREQ`, interpolated linearly between points.
Listed for reference; the driver does not apply it.

| Frequency | 10 MHz | 50 MHz | 100 MHz | 1 GHz | 2 GHz | 4 GHz | 6 GHz | 8 GHz | 10 GHz | 12 GHz | 14 GHz | 16 GHz | 18 GHz |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CF (%) | 98.6 | 100.0 | 99.8 | 99.1 | 98.4 | 97.5 | 96.7 | 95.8 | 94.9 | 93.7 | 92.6 | 91.4 | 90.1 |

## 5. Specifications for an uncertainty budget

Each contribution is given with its basis, its probability distribution and the divisor that turns
it into a standard uncertainty (GUM, first order). Contributions in nW or dB are converted to
% of reading before combining (section 7). Contributions are independent; combine standard
uncertainties by root-sum-square.

| Contribution | Value | Basis | Distribution | Divisor |
|---|---|---|---|---|
| Instrument accuracy | ±0.50 | % of reading | rectangular | √3 |
| Linearity | ±0.30 | % of reading | rectangular | √3 |
| Zero offset, LOW range | ±0.5 | nW | rectangular | √3 |
| Zero offset, HIGH range | ±50 | nW | rectangular | √3 |
| Calibration factor, 10 MHz to 8 GHz | ±1.6 | % of reading, expanded (k = 2) | normal | 2 |
| Calibration factor, above 8 GHz to 18 GHz | ±2.2 | % of reading, expanded (k = 2) | normal | 2 |
| Noise, averaging count N | 2.0 / √N | % of reading, one standard deviation | normal | 1 |
| Mismatch | ±200·Γs·Γm | % of reading (Γs, Γm: reflection coefficient magnitudes) | U-shaped | √2 |
| Display resolution | ±0.005 | dB (half of the 0.01 dB step) | rectangular | √3 |

Reflection coefficient magnitude of the sensor input, Γm:

| Frequency | Γm |
|---|---|
| 10 MHz to 8 GHz | 0.10 |
| above 8 GHz to 18 GHz | 0.15 |

Γs is the reflection coefficient magnitude of the source under test; take it from the source's own
data. The mismatch limit ±200·Γs·Γm % is the first-order form of ±(1 - (1 ± Γs·Γm)^2) × 100 %.

The combined standard uncertainty is u_c = sqrt(sum of (value_i / divisor_i)^2), all terms in % of
reading. The expanded uncertainty for about 95 % coverage is U = 2·u_c.

## 6. Limits

The KX-100 cannot measure outside these limits, and no setting or averaging count extends them.

- Measurement resolution: 0.01 dB
- Frequency range: 10 MHz to 18 GHz
- Power range: -60 dBm to +20 dBm

A reading finer than the resolution is not available from the instrument, and a signal outside the
frequency range cannot be measured with a calibrated result.

## 7. Conversions

- dBm to watts: P_W = 10^(P_dBm / 10) / 1000
- watts to dBm: P_dBm = 10·log10(1000·P_W)
- An absolute contribution a (in W) at a reading P_W is 100·a / P_W % of reading.
- A contribution in dB, d, is (10^(d / 10) - 1)·100 % of reading; 0.005 dB is 0.115 %.
- A relative uncertainty u (in %) is 10·log10(1 + u / 100) dB.

## 8. Error codes

| Code | Text | Cause |
|---|---|---|
| 0 | No error | The queue is empty. |
| -104 | Data type error | A parameter is not a number where one is required, or not an integer. |
| -108 | Parameter not allowed | A parameter was given to a command that takes none. |
| -109 | Missing parameter | A setting command was sent without its value. |
| -113 | Undefined header | The command is not in this manual. |
| -131 | Invalid suffix | A unit suffix other than HZ, KHZ, MHZ, GHZ. |
| -222 | Data out of range | A value outside its range; the setting is unchanged. |
| -224 | Illegal parameter value | A range other than AUTO, LOW, HIGH. |
| -350 | Queue overflow | More than 10 errors; the newest one is replaced by this code. |
| -410 | Query INTERRUPTED | A command was written before the previous response was read. |
| -420 | Query UNTERMINATED | A read was attempted with no response pending. |
| 201 | Measurement over range | The input exceeded the selected range. |

The queue holds 10 errors and is read oldest first.
