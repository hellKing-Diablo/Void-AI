# Firmware

## OMI DevKit (`omi/`)
- **Platform**: nRF52840 (ARM Cortex-M4, Nordic)
- **RTOS**: Zephyr
- **Source**: `omi/firmware/omi/src/`
- **Hardware designs**: `omi/hardware/`

### Key Source Files (`omi/firmware/omi/src/`)
```
main.c           Entry point, BLE + peripheral init, boot LED sequence
mic.c            PDM microphone capture
battery.c        Battery monitoring
led.c            LED control
haptic.c         Haptic feedback
feedback.c       Audio/haptic feedback patterns
imu.c/imu.h      IMU (accelerometer/gyro)
sd_card.c        SD card storage
spi_flash.c      External SPI flash (WAL storage)
wifi.c/wifi.h    WiFi connectivity
rtc.c/rtc.h      Real-time clock
settings.c       Persistent settings
wdog_facade.c    Watchdog timer
```

### Audio Codec
- Opus encoder (`lib/opus-1.2.1/`) embedded in firmware
- Audio transmitted via BLE transport as Opus-encoded packets

### Build & Flash
- Zephyr-based build system
- Board definitions: `omi/firmware/boards/`
- Bootloader: MCUboot (`omi/firmware/bootloader/`)
- Build/flash scripts: `omi/firmware/scripts/`
- Guide: `omi/firmware/BUILD_AND_OTA_FLASH.md`
- OTA update script: `scripts/ota_update.py`

### Directories
```
omi/firmware/omi/        Main DevKit firmware
omi/firmware/devkit/     Alternative devkit variant
omi/firmware/boards/     Board definition files
omi/firmware/bootloader/ MCUboot config
omi/firmware/scripts/    Build and flash scripts
omi/firmware/test/       Firmware tests
omi/hardware/            Hardware designs, schematics
```

---

## OMI Glass (`omiGlass/`)
- **Platform**: Seeed XIAO ESP32-S3 Sense (with camera)
- **Framework**: Arduino
- **Entry**: `omiGlass/firmware/firmware.ino`
- **BLE**: NimBLE-Arduino library
- **Companion app**: `omiGlass/App.tsx` (React Native)
- **Hardware**: `omiGlass/hardware/`

### Setup
1. Arduino IDE → select XIAO_ESP32S3 board
2. Enable OPI PSRAM
3. Upload firmware

### Features
- Camera capture
- Audio streaming via BLE
- 6x battery life vs Meta Ray-Bans (claimed)

---

## Communication Protocol
- **Device → App**: BLE (Bluetooth Low Energy)
- **App → Backend**: WebSocket (`/v4/listen`)
- Audio encoded as Opus (DevKit) or raw PCM (Glass)
- App decodes and re-encodes as needed before sending to backend

## Formatting
C/C++ files formatted with: `clang-format -i <files>`
