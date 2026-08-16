Raspberry Pi Pico Datasheet

# Chapter 1. About Raspberry Pi Pico

Raspberry Pi Pico is a microcontroller board based on the Raspberry Pi RP2040 microcontroller chip.

Figure 1. The Raspberry Pi Pico Rev3 board.

The Raspberry Pi Pico Rev3 board showing top and bottom views with pinout labels.

Raspberry Pi Pico has been designed to be a low cost yet flexible development platform for RP2040, with the following key features:

* RP2040 microcontroller with 2MB Flash

* Micro-USB B port for power and data (and for reprogramming the Flash)

* 40 pin 21×51 'DIP' style 1mm thick PCB with 0.1" through-hole pins also with edge castellations

    - Exposes 26 multi-function 3.3V General Purpose I/O (GPIO)

    - 23 GPIO are digital-only and 3 are ADC capable

    - Can be surface mounted as a module

* 3-pin ARM Serial Wire Debug (SWD) port

* Simple yet highly flexible power supply architecture

    - Various options for easily powering the unit from micro-USB, external supplies or batteries

* High quality, low cost, high availability

* Comprehensive SDK, software examples and documentation

For full details of the RP2040 microcontroller please see the RP2040 Datasheet, however the headline features are:

* Dual-core cortex M0+ at up to 133MHz

    - On-chip PLL allows variable core frequency

* 264kB multi-bank high performance SRAM

* External Quad-SPI Flash with eXecute In Place (XIP) and 16kB on-chip cache

* High performance full-crossbar bus fabric

Chapter 1. About Raspberry Pi Pico

<page_number>3</page_number>

Raspberry Pi Pico Datasheet

Figure 4. The pin numbering of the Raspberry Pi Pico Rev3 board.

The pin numbering of the Raspberry Pi Pico Rev3 board engineering drawing

> Note icon **NOTE**
>
> 

> The physical pin numbering is shown in Figure 4, for the pin allocation see Figure 2 or the full Raspberry Pi Pico schematics in Appendix B.

A few RP2040 GPIO pins are used for internal board functions, these are:

*   **GPIO29**: IP Used in ADC mode (ADC3) to measure VSYS/3
*   **GPIO25**: OP Connected to user LED
*   **GPIO24**: IP VBUS sense - high if VBUS is present, else low
*   **GPIO23**: OP Controls the on-board SMPS Power Save pin (Section 4.4)

Apart from GPIO and ground pins, there are 7 other pins on the main 40-pin interface:

*   **PIN40**: VBUS
*   **PIN39**: VSYS
*   **PIN37**: 3V3_EN
*   **PIN36**: 3V3
*   **PIN35**: ADC_VREF
*   **PIN33**: AGND
*   **PIN30**: RUN

VBUS is the micro-USB input voltage, connected to micro-USB port pin 1. This is nominally 5V (or 0V if the USB is not connected or not powered).

VSYS is the main system input voltage, which can vary in the allowed range 1.8V to 5.5V, and is used by the on-board SMPS to generate the 3.3V for the RP2040 and its GPIO.

3V3_EN connects to the on-board SMPS enable pin, and is pulled high (to VSYS) via a 100kΩ resistor. To disable the 3.3V (which also de-powers the RP2040), short this pin low.

2.1. Raspberry Pi Pico pinout

<page_number>7</page_number>

Raspberry Pi Pico Datasheet

## 2.3. Recommended operating conditions

Operating conditions for the Raspberry Pi Pico are largely a function of the operating conditions specified by its components.

<table>
    <tr>
        <td>**Operating Temp Max**</td>
        <td>85°C (including self-heating)</td>
    </tr>
    <tr>
        <td>**Operating Temp Min**</td>
        <td>-20°C</td>
    </tr>
    <tr>
        <td>**VBUS**</td>
        <td>5V ± 10%.</td>
    </tr>
    <tr>
        <td>**VSYS Min**</td>
        <td>1.8V</td>
    </tr>
    <tr>
        <td>**VSYS Max**</td>
        <td>5.5V</td>
    </tr>
</table>

Note that VBUS and VSYS current will depend on use-case, some examples are given in the next section.

Recommended maximum ambient temperature of operation is 70°C.

2.3. Recommended operating conditions

<page_number>11</page_number>