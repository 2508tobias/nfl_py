#!/usr/bin/env python3
"""
NFL Scoreboard for the SeenGreat 7.5" 800x480 monochrome e-paper HAT
(EPD_7Inch5 / wiringpi driver) on a Raspberry Pi Zero 2 W.

Pulls the current week's NFL scores from ESPN's public scoreboard
endpoint and redraws a grid scoreboard on the e-paper display on a
fixed interval, using partial refresh most cycles and a full refresh
periodically to clear ghosting.

--------------------------------------------------------------------
SETUP (gpiozero / lgpio driver variant - Trixie-friendly)

1. Put epd_7inch5.py (from your SeenGreat demo package) somewhere on
   disk and point DRIVER_LIB_PATH at that directory. You only need
   epd_7inch5.py itself - not epd_gui.py, gui_demo.py, or image.py;
   this script does its own PIL-based rendering and converts straight
   to the packed byte format the driver expects.

2. Install dependencies:
     sudo apt-get install python3-gpiozero python3-lgpio
     sudo apt-get install python3-pil python3-numpy python3-pip
     sudo pip3 install spidev requests --break-system-packages

3. Unlike the wiringpi driver, this one talks to GPIO through gpiozero
   (backed by lgpio), which normally does NOT need root - being in the
   `gpio` group (the default `pi`/your-user account already is) is
   enough. Try `python3 nfl_epaper.py` without sudo first; only add
   sudo/root back in if you hit a permissions error opening the GPIO
   chip.
--------------------------------------------------------------------
"""

import sys
import time
import logging
from datetime import datetime

import requests
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------

DRIVER_LIB_PATH = "/home/pi/nfl-epaper/driver"  # ADJUST ME: folder containing epd_7inch5.py

REFRESH_SECONDS = 60  # how often to pull new scores and redraw

# Partial refresh skips the full black-flash cycle - much less jarring once
# a minute. Ghosting builds up over many partial refreshes though, so we
# force a full refresh periodically to clean it up.
# Partial refresh skips the full black-flash cycle - much less jarring once
# a minute. Ghosting builds up over many partial refreshes though, so we
# force a full refresh periodically to clean it up.
#
# NOTE: this previously hung indefinitely on the observed hardware (the old
# chkstatus() had no timeout). epd_7inch5.py now raises TimeoutError instead
# of hanging forever, and the main loop below catches it and falls back to a
# full refresh for that cycle - so it's safe to try this again and actually
# see what happens instead of guessing.
USE_PARTIAL_REFRESH = True
FULL_REFRESH_EVERY_N_CYCLES = 30  # ~30 min at REFRESH_SECONDS=60

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
REQUEST_TIMEOUT = 10

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("nfl-epaper")

# ---------------------------------------------------------------------------
# DRIVER IMPORT
# ---------------------------------------------------------------------------

sys.path.append(DRIVER_LIB_PATH)
from epd_7inch5 import EPD_7Inch5, EPD_WIDTH, EPD_HEIGHT  # noqa: E402

WIDTH, HEIGHT = EPD_WIDTH, EPD_HEIGHT  # 800, 480
COLS, ROWS = 4, 4  # 16 slots covers a full NFL week
HEADER_H = 40
CELL_W = WIDTH // COLS
CELL_H = (HEIGHT - HEADER_H) // ROWS


def load_font(size):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    log.warning("No TTF font found, falling back to PIL's tiny default font")
    return ImageFont.load_default()


FONT_HEADER = load_font(22)
FONT_TEAM = load_font(26)
FONT_SCORE = load_font(30)
FONT_STATUS = load_font(16)


# ---------------------------------------------------------------------------
# DATA FETCH
# ---------------------------------------------------------------------------

def fetch_games():
    """Return a list of game dicts for the current NFL week, or [] on failure."""
    try:
        resp = requests.get(ESPN_SCOREBOARD_URL, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        log.error("Failed to fetch scoreboard: %s", exc)
        return []

    games = []
    for event in data.get("events", []):
        try:
            competition = event["competitions"][0]
            status = event["status"]
            state = status["type"]["state"]  # 'pre' | 'in' | 'post'
            detail = status["type"].get("shortDetail", "")

            competitors = competition["competitors"]
            home = next(c for c in competitors if c["homeAway"] == "home")
            away = next(c for c in competitors if c["homeAway"] == "away")

            games.append({
                "state": state,
                "detail": detail,
                "home_abbr": home["team"].get("abbreviation", "?"),
                "away_abbr": away["team"].get("abbreviation", "?"),
                "home_score": home.get("score", "0"),
                "away_score": away.get("score", "0"),
            })
        except (KeyError, StopIteration, IndexError) as exc:
            log.warning("Skipping malformed game entry: %s", exc)

    return games


# ---------------------------------------------------------------------------
# RENDERING (pure PIL - independent of the driver)
# ---------------------------------------------------------------------------

def draw_header(draw):
    now = datetime.now().strftime("%a %b %d  %I:%M %p")
    draw.text((10, 8), "NFL Scores", font=FONT_HEADER, fill=0)
    w = draw.textlength(now, font=FONT_STATUS)
    draw.text((WIDTH - w - 10, 14), now, font=FONT_STATUS, fill=0)
    draw.line((0, HEADER_H, WIDTH, HEADER_H), fill=0, width=2)


def draw_game_cell(draw, x, y, game):
    pad = 6
    live = game["state"] == "in"

    draw.rectangle((x + 2, y + 2, x + CELL_W - 2, y + CELL_H - 2),
                    outline=0, width=3 if live else 1)

    row_h = 32
    away_y = y + pad + 4
    home_y = away_y + row_h

    draw.text((x + pad, away_y), game["away_abbr"], font=FONT_TEAM, fill=0)
    draw.text((x + pad, home_y), game["home_abbr"], font=FONT_TEAM, fill=0)

    away_score = str(game["away_score"])
    home_score = str(game["home_score"])
    sw = max(draw.textlength(away_score, font=FONT_SCORE),
             draw.textlength(home_score, font=FONT_SCORE))
    draw.text((x + CELL_W - pad - sw, away_y - 2), away_score, font=FONT_SCORE, fill=0)
    draw.text((x + CELL_W - pad - sw, home_y - 2), home_score, font=FONT_SCORE, fill=0)

    status = "LIVE  " + game["detail"] if live else game["detail"]
    draw.text((x + pad, y + CELL_H - 22), status, font=FONT_STATUS, fill=0)


def render(games):
    image = Image.new("1", (WIDTH, HEIGHT), 255)  # 255 = white
    draw = ImageDraw.Draw(image)
    draw_header(draw)

    if not games:
        msg = "No games found for this week"
        w = draw.textlength(msg, font=FONT_TEAM)
        draw.text(((WIDTH - w) / 2, HEIGHT / 2), msg, font=FONT_TEAM, fill=0)
        return image

    max_slots = COLS * ROWS
    for i, game in enumerate(games[:max_slots]):
        col = i % COLS
        row = i // COLS
        x = col * CELL_W
        y = HEADER_H + row * CELL_H
        draw_game_cell(draw, x, y, game)

    return image


# ---------------------------------------------------------------------------
# PIL -> PACKED BYTES FOR THIS DRIVER
# ---------------------------------------------------------------------------

def pack_image(image):
    """
    Convert a PIL mode '1' image (0=black, 255=white) into the flat list
    of packed bytes this driver's write functions expect: MSB-first,
    row-major, bit=1 for a black pixel (matches EPD_7Inch5.set_pixel's
    own convention, and EPD_ARRAY = W*H/8 length).
    """
    if image.mode != "1":
        image = image.convert("1")
    arr = np.array(image, dtype=np.uint8)          # shape (H, W), values 0 or 255
    black_bits = (arr == 0).astype(np.uint8)        # 1 where black
    packed = np.packbits(black_bits, axis=1)        # MSB-first per row
    return packed.flatten().tolist()


# ---------------------------------------------------------------------------
# DISPLAY PUSH
# ---------------------------------------------------------------------------

# Tracks what's actually currently shown on the panel, in packed-byte form.
# EPD_Dis_Part() as shipped never writes the "old frame" data (cmd 0x10)
# before the "new frame" data (cmd 0x13) - the controller's internal old-
# frame reference was going stale, which is the likely cause of partial
# refreshes coming out gray/incomplete instead of clean black-and-white.
# We track it ourselves here and always feed the real previous frame in.
_last_displayed_bits = None


def full_refresh(epd, image):
    global _last_displayed_bits
    epd.init()
    bits = pack_image(image)
    epd.whitescreen_all(bits)
    _last_displayed_bits = bits


def dis_part_with_old_data(epd, x_start, y_start, old_bits, new_bits, part_column, part_line):
    """
    Same register sequence as the vendor's EPD_Dis_Part(), but also writes
    the real previous-frame data (cmd 0x10) before the new frame (cmd 0x13).
    The shipped EPD_Dis_Part() skips the old-data write entirely.
    """
    x_end = x_start + part_line - 1
    y_end = y_start + part_column - 1

    epd.write_cmd(0x50)
    epd.write_data(0xA9)
    epd.write_data(0x07)

    epd.write_cmd(0x91)   # enter partial mode
    epd.write_cmd(0x90)   # resolution/window setting
    epd.write_data(x_start // 256)
    epd.write_data(x_start % 256)
    epd.write_data(x_end // 256)
    epd.write_data(x_end % 256 - 1)
    epd.write_data(y_start // 256)
    epd.write_data(y_start % 256)
    epd.write_data(y_end // 256)
    epd.write_data(y_end % 256 - 1)
    epd.write_data(0x01)

    epd.write_cmd(0x10)   # old data - the actual previous frame, not skipped
    for b in old_bits:
        epd.write_data(b)

    epd.write_cmd(0x13)   # new data
    for b in new_bits:
        epd.write_data(b)

    epd.update()


def partial_refresh(epd, image):
    global _last_displayed_bits
    new_bits = pack_image(image)
    # Fall back to treating the new frame as its own "old" reference if we
    # somehow don't have a tracked previous frame yet (shouldn't normally
    # happen - full_refresh() always runs first and sets this).
    old_bits = _last_displayed_bits if _last_displayed_bits is not None else new_bits

    dis_part_with_old_data(epd, 0, 0, old_bits, new_bits, EPD_HEIGHT, EPD_WIDTH)
    epd.write_cmd(0x92)  # exit partial mode, mirroring the vendor demo's pattern

    _last_displayed_bits = new_bits


# ---------------------------------------------------------------------------
# MAIN LOOP
# ---------------------------------------------------------------------------

def main():
    epd = EPD_7Inch5()
    log.info("Initializing display...")
    epd.init()
    epd.whitescreen_white()

    cycle = 0
    partial_session_active = False

    try:
        while True:
            cycle += 1
            games = fetch_games()
            log.info("Fetched %d games", len(games))
            image = render(games)

            do_full = (
                cycle == 1
                or not USE_PARTIAL_REFRESH
                or cycle % FULL_REFRESH_EVERY_N_CYCLES == 0
            )

            try:
                if do_full:
                    full_refresh(epd, image)
                    partial_session_active = False
                else:
                    if not partial_session_active:
                        epd.init_part()  # once per session, before the first partial write
                        partial_session_active = True
                    partial_refresh(epd, image)
            except TimeoutError as exc:
                log.error("Display refresh timed out (%s) - forcing full refresh", exc)
                partial_session_active = False
                try:
                    full_refresh(epd, image)
                except TimeoutError as exc2:
                    log.error("Full-refresh fallback also timed out (%s) - "
                              "skipping this cycle", exc2)

            # No deepsleep() between cycles on purpose: partial refresh relies
            # on staying initialized. Waking from deep sleep forces a full
            # re-init/flash, which would defeat the point.
            time.sleep(REFRESH_SECONDS)
    except KeyboardInterrupt:
        log.info("Interrupted, putting display to sleep")
    finally:
        try:
            epd.init()
            epd.deepsleep()
        except Exception:
            pass
        try:
            epd.clean_gpio()  # releases the gpiozero pin objects cleanly
        except Exception:
            pass


if __name__ == "__main__":
    main()
