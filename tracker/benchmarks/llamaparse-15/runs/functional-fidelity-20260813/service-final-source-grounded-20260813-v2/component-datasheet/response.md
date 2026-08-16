Raspberry Pi Pico Datasheet

# Chapter 1. About Raspberry Pi Pico

Raspberry Pi Pico is a microcontroller board based on the Raspberry Pi RP2040 microcontroller chip.

Figure 1. The Raspberry Pi Pico Rev3 board.

ees ©
e
TP4 oo
Wace GP28_A2
TPi VSYS
® VBUS
GP26_A0
ADC_VREF
3v3
3V3_EN
GP21
GP22
GP16
GP17
GND
GP18
GP19
GP20
RUN
ba - Bye 4
nn
on
™® SWOI0
@) GND
TP6
TPS
Nw
S°sS
™® SWCLK
Sow
ao
GPO
GP4
GP3
Qa
GP2
GND
GP1
GP6
GND
a
GP5
a
GP9
GP8
GP7
~o
ny oro
w
w
@ Raspberry Pi Pico © 2020
BOOTSEL
3 eo
a
go
c=
n=
me
it
if
o> 6 8 © &
oe GOGO OR 88 8 2 8 ® ©

Raspberry Pi Pico has been designed to be a low cost yet flexible development platform for RP2040, with the following key features:

<ul data-outline-group="outline-group-be0a9676920eca8a0718" data-outline-policy="p03-outline-structure-v1">
  <li data-outline-item="outline-item-36365dbd769506684a2d" data-source-marker="•">RP2040 microcontroller with 2MB Flash</li>
  <li data-outline-item="outline-item-c4daf38ff74cecc9f2f0" data-source-marker="•">Micro-USB B port for power and data (and for reprogramming the Flash)</li>
  <li data-outline-item="outline-item-3c4f2e7e73685020d18b" data-source-marker="•">40 pin 21 × 51 'DIP' style 1mm thick PCB with 0.1" through-hole pins also with edge castellations
  <ul>
    <li data-outline-item="outline-item-81ad78001c2a2d691842" data-source-marker="◦">Exposes 26 multi-function 3.3V General Purpose I/O (GPIO)</li>
    <li data-outline-item="outline-item-f4fefab1c4072826b2e8" data-source-marker="◦">23 GPIO are digital-only and 3 are ADC capable</li>
    <li data-outline-item="outline-item-613a9f3795bf2d221b7f" data-source-marker="◦">Can be surface mounted as a module</li>
  </ul>
  </li>
  <li data-outline-item="outline-item-804388173a0aeddc9219" data-source-marker="•">3-pin ARM Serial Wire Debug (SWD) port</li>
  <li data-outline-item="outline-item-7dd6834b3d386efbe8db" data-source-marker="•">Simple yet highly flexible power supply architecture
  <ul>
    <li data-outline-item="outline-item-5c908f56c6d8f318391b" data-source-marker="◦">Various options for easily powering the unit from micro-USB, external supplies or batteries</li>
  </ul>
  </li>
  <li data-outline-item="outline-item-acfb0dd394f8310738fd" data-source-marker="•">High quality, low cost, high availability</li>
  <li data-outline-item="outline-item-45c09c9f0c29ea36720c" data-source-marker="•">Comprehensive SDK, software examples and documentation</li>
</ul>

For full details of the RP2040 microcontroller please see the RP2040 Datasheet , however the headline features are:

<ul data-outline-group="outline-group-b1771d4866c7bc30a604" data-outline-policy="p03-outline-structure-v1">
  <li data-outline-item="outline-item-909d6bf1966f59daaca3" data-source-marker="•">Dual-core cortex M0+ at up to 133MHz
  <ul>
    <li data-outline-item="outline-item-7a1cf9d964c24d179d88" data-source-marker="◦">On-chip PLL allows variable core frequency</li>
  </ul>
  </li>
  <li data-outline-item="outline-item-1b6d2e3b2891008ad24f" data-source-marker="•">264kB multi-bank high performance SRAM</li>
  <li data-outline-item="outline-item-574a593d4fa42898e9ec" data-source-marker="•">External Quad-SPI Flash with eXecute In Place (XIP) and 16kB on-chip cache</li>
  <li data-outline-item="outline-item-e708634b621cdca74b13" data-source-marker="•">High performance full-crossbar bus fabric</li>
</ul>

Chapter 1. About Raspberry Pi Pico

3

Raspberry Pi Pico Datasheet

Figure 4. The pin numbering of the Raspberry Pi Pico Rev3 board.

©@q 40

Rh WP oo on —

Ke)

Oo Od 40

Pt

229

39

b O} (Od 38

(C4

5S @y Gd 36

(OTP5

@4

6 PO

ox

DO TPi-6 ARE ON Gd 34

TP1-6 ARE ON

xo) REVERSE SIDE x 33

8 po}

fx

5D oat

10 }O

31

x

11 pO

b O) ©@q 30

©4 30

b O) ©@q 29

(Od 28

13 DO)

b O} (Og 28

5D oi 21

©q 27

©@4 26

15 pO

bO) Cd 26

16 pO

b ©) ©Cq 25

b ©) Cd 24

(C4 23

18 po)

Xe) (Od 23

19 )O

©4 22

Baa

20 PO

#  NOTE

The physical pin numbering is shown in Figure 4, for the pin allocation see Figure 2 or the full Raspberry Pi Pico schematics in Appendix B.

A few RP2040 GPIO pins are used for internal board functions, these are:

- **GPIO29:** IP Used in ADC mode (ADC3) to measure VSYS/3
- **GPIO25:** OP Connected to user LED
- **GPIO24:** IP VBUS sense - high if VBUS is present, else low
- **GPIO23:** OP Controls the on-board SMPS Power Save pin (Section 4.4)

Apart from GPIO and ground pins, there are 7 other pins on the main 40-pin interface:

- **PIN40:** VBUS
- **PIN39:** VSYS
- **PIN37:** 3V3_EN
- **PIN36:** 3V3
- **PIN35:** ADC_VREF
- **PIN33:** AGND
- **PIN30:** RUN

VBUS is the micro-USB input voltage, connected to micro-USB port pin 1. This is nominally 5V (or 0V if the USB is not connected or not powered).

VSYS is the main system input voltage, which can vary in the allowed range 1.8V to 5.5V, and is used by the on-board SMPS to generate the 3.3V for the RP2040 and its GPIO.

3V3_EN connects to the on-board SMPS enable pin, and is pulled high (to VSYS) via a 100k Ω resistor. To disable the 3.3V (which also de-powers the RP2040), short this pin low.

2.1. Raspberry Pi Pico pinout

7

Raspberry Pi Pico Datasheet

## 2.3. Recommended operating conditions

Operating conditions for the Raspberry Pi Pico are largely a function of the operating conditions specified by its components.

- **Operating Temp Max:** 85°C (including self-heating)
- **Operating Temp Min:** -20°C
- **VBUS:** 5V ± 10%.
- **VSYS Min:** 1.8V
- **VSYS Max:** 5.5V

Note that VBUS and VSYS current will depend on use-case, some examples are given in the next section.

Recommended maximum ambient temperature of operation is 70°C.

2.3. Recommended operating conditions

11
