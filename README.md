# NFL Live Scoreboard — E-Paper Display Project

## Overview
A live-updating NFL scoreboard displayed on a SeenGreat 7.5" e-paper
display, driven by a Raspberry Pi. Shows current scores for the
week's games, similar in spirit to nflgamedata.com, refreshing about
once a minute.

## Hardware
- **Display:** SeenGreat 7.5" e-paper, 800x480, monochrome
- **Controller:** Raspberry Pi 5 (upgraded from a Raspberry Pi Zero W,
  which was too slow for this use case)
- **OS:** Raspberry Pi OS Trixie (full desktop version)

## Driver Files
SeenGreat provided two driver variants for the display, both exposing
an `EPD_7Inch5` class:

1. **wiringpi-based** — `gui_demo.py`, `epd_7inch5.py`, `epd_gui.py`
2. **gpiozero/lgpio-based** — same file structure, different GPIO backend

## Goals
- [ ] Pull current-week NFL scores (data source TBD — e.g. an NFL/ESPN
      API or scraping nflgamedata.com-style data)
- [ ] Render scores in a clean layout suited to a monochrome
      800x480 e-paper panel
- [ ] Refresh automatically approximately once per minute
- [ ] Run reliably as a background service on the Pi 5

## Open Questions
- Which data source/API to use for live scores
- Layout: all games at once vs. paginated/cycling view
- How to handle partial refreshes (e-paper displays are slow to
  fully redraw — worth investigating partial refresh support in the
  driver)
- Auto-start on boot (systemd service?)

## Notes
- Full display refreshes on e-paper are slow and can ghost; partial
  refresh (if supported by the driver) will likely be needed for a
  once-a-minute update cadence.
