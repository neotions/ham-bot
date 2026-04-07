from datetime import datetime, timezone
import logging
import os
from pathlib import Path
import sqlite3
import xml.etree.ElementTree as ET

import discord
import requests
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv


load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN") or os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("Set DISCORD_BOT_TOKEN or DISCORD_TOKEN before starting the bot.")

LOG_LEVEL_NAME = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_NAME, logging.INFO)
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
LOGGER = logging.getLogger("ham-bot")

BOT_VERSION = "0.1"
DB_VERSION = "0.1"
SOLAR_XML_URL = "https://www.hamqsl.com/solarxml.php"
DEFAULT_SOURCE_URL = "https://www.hamqsl.com/solar.html"
DB_PATH = Path(os.getenv("HAM_BOT_DB_PATH", "ham_bot.sqlite3"))
SPEED_OF_LIGHT_M_S = 299_792_458.0

WAVELENGTH_UNITS = {
    "m": ("meters", 1.0),
    "cm": ("centimeters", 0.01),
    "ft": ("feet", 0.3048),
}

FREQUENCY_UNITS = {
    "Hz": ("Hz", 1.0),
    "kHz": ("kHz", 1_000.0),
    "MHz": ("MHz", 1_000_000.0),
    "GHz": ("GHz", 1_000_000_000.0),
}


def get_db_connection() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def initialize_database() -> None:
    with get_db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS solar_xml_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fetched_at_utc TEXT NOT NULL,
                upstream_updated TEXT,
                source_name TEXT,
                source_url TEXT NOT NULL,
                raw_xml TEXT NOT NULL,
                db_version TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
            (
                ("db_version", DB_VERSION),
                ("bot_version", BOT_VERSION),
            ),
        )


def store_solar_xml(raw_xml: str, upstream_updated: str, source_name: str, source_url: str) -> None:
    fetched_at_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO solar_xml_reports (
                fetched_at_utc,
                upstream_updated,
                source_name,
                source_url,
                raw_xml,
                db_version
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                fetched_at_utc,
                upstream_updated,
                source_name,
                source_url,
                raw_xml,
                DB_VERSION,
            ),
        )


def clean_text(value: str | None, default: str = "N/A") -> str:
    if value is None:
        return default
    cleaned = value.strip()
    return cleaned or default


def normalize_source_url(url: str | None) -> str:
    cleaned = clean_text(url, DEFAULT_SOURCE_URL)
    if cleaned.startswith("http://www.hamqsl.com/"):
        return cleaned.replace("http://", "https://", 1)
    return cleaned


def format_updated_timestamp(raw_value: str) -> str:
    """Normalize the upstream update timestamp when it matches a known format."""
    candidate = raw_value.strip()
    known_formats = (
        "%d %b %Y %H%M %Z",
        "%d %b %Y %H:%M %Z",
        "%b %d %Y %H:%M %Z",
        "%Y-%m-%d %H:%M:%S %Z",
    )
    for time_format in known_formats:
        try:
            parsed = datetime.strptime(candidate, time_format)
            return parsed.replace(tzinfo=timezone.utc).strftime("%b %d %Y %H:%M UTC")
        except ValueError:
            continue
    return candidate


def format_value(value: float) -> str:
    """Format numeric output without unnecessary trailing zeroes."""
    if value >= 100:
        rendered = f"{value:,.2f}"
    elif value >= 10:
        rendered = f"{value:,.3f}"
    else:
        rendered = f"{value:,.6f}"
    return rendered.rstrip("0").rstrip(".")


def build_conversion_embed(
    title: str,
    source_value: float,
    source_unit: str,
    result_value: float,
    result_unit: str,
    extra_lines: list[str],
) -> discord.Embed:
    embed = discord.Embed(title=title, color=0x1A73E8)
    embed.description = (
        f"**Input:** {format_value(source_value)} {source_unit}\n"
        f"**Result:** {format_value(result_value)} {result_unit}"
    )
    if extra_lines:
        embed.add_field(name="Also", value="\n".join(extra_lines), inline=False)
    embed.set_footer(text=f"ham-bot {BOT_VERSION}")
    return embed


def get_band_conditions() -> discord.Embed:
    """Fetch the current HF band conditions and build a Discord embed."""
    response = requests.get(SOLAR_XML_URL, timeout=10)
    response.raise_for_status()

    raw_xml = response.text
    root = ET.fromstring(raw_xml)
    data = root.find("solardata")
    if data is None:
        raise ValueError("Solar data feed did not include a solardata element.")

    sfi = clean_text(data.findtext("solarflux"))
    sunspots = clean_text(data.findtext("sunspots"))
    aindex = clean_text(data.findtext("aindex"))
    kindex = clean_text(data.findtext("kindex"))
    xray = clean_text(data.findtext("xray"))
    wind = clean_text(data.findtext("solarwind"))
    geomag = clean_text(data.findtext("geomagfield"))
    signal = clean_text(data.findtext("signalnoise"))
    updated_raw = clean_text(data.findtext("updated"))
    updated = format_updated_timestamp(updated_raw)

    source = data.find("source")
    source_name = clean_text(source.text if source is not None else None, "hamqsl")
    source_url = normalize_source_url(source.get("url") if source is not None else None)

    bands_day: dict[str, str] = {}
    bands_night: dict[str, str] = {}
    band_order: list[str] = []
    for band in data.findall("calculatedconditions/band"):
        name = band.get("name")
        if not name:
            continue

        condition = clean_text(band.text)
        time_of_day = clean_text(band.get("time"), "").lower()
        if name not in band_order:
            band_order.append(name)

        if time_of_day == "day":
            bands_day[name] = condition
        elif time_of_day == "night":
            bands_night[name] = condition

    def marker(condition: str) -> str:
        return {"Good": "G", "Fair": "F", "Poor": "P"}.get(condition, "?")

    store_solar_xml(
        raw_xml=raw_xml,
        upstream_updated=updated_raw,
        source_name=source_name,
        source_url=source_url,
    )

    embed = discord.Embed(
        title="HF Band Conditions",
        url=source_url,
        description=f"Data from [{source_name}]({source_url})\nUpdated: {updated}",
        color=0x1A73E8,
    )

    band_lines = []
    for band in band_order:
        day_condition = bands_day.get(band, "N/A")
        night_condition = bands_night.get(band, "N/A")
        band_lines.append(
            f"**{band}**\n"
            f"Day: {marker(day_condition)} {day_condition}\n"
            f"Night: {marker(night_condition)} {night_condition}"
        )

    embed.add_field(
        name="Band Conditions",
        value="\n\n".join(band_lines) if band_lines else "No data",
        inline=False,
    )
    embed.add_field(
        name="Solar Data",
        value=(
            f"Solar Flux: **{sfi}**\n"
            f"Sunspots: **{sunspots}**\n"
            f"Geomag: **{geomag}**\n\n"
            f"A-Index: **{aindex}**\n"
            f"K-Index: **{kindex}**\n"
            f"X-Ray: **{xray}**\n\n"
            f"Solar Wind: **{wind} km/s**\n"
            f"Noise: **{signal}**"
        ),
        inline=False,
    )
    embed.set_footer(text=f"ham-bot {BOT_VERSION} | db {DB_VERSION} | XML archived in {DB_PATH.name}")
    return embed


class HamBot(commands.Bot):
    def __init__(self) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=discord.Intents.default(),
        )

    async def setup_hook(self) -> None:
        initialize_database()
        LOGGER.info("Initialized SQLite database at %s.", DB_PATH.resolve())
        synced = await self.tree.sync()
        LOGGER.info("Synced %s global command(s).", len(synced))

    async def on_ready(self) -> None:
        LOGGER.info("Logged in as %s (%s).", self.user, self.user.id if self.user else "unknown")


bot = HamBot()


@bot.tree.command(
    name="bandconditions",
    description="Show current HF band conditions",
)
async def band_conditions(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)

    try:
        embed = get_band_conditions()
    except Exception as exc:
        LOGGER.exception("Failed to fetch band conditions.")
        await interaction.followup.send(f"Failed to fetch band conditions: {exc}")
        return

    await interaction.followup.send(embed=embed)


@bot.tree.command(
    name="wavelength_to_frequency",
    description="Convert a wavelength to frequency",
)
@app_commands.describe(
    wavelength="Wavelength value to convert",
    unit="Unit for the wavelength input",
)
@app_commands.choices(
    unit=[
        app_commands.Choice(name="Meters", value="m"),
        app_commands.Choice(name="Centimeters", value="cm"),
        app_commands.Choice(name="Feet", value="ft"),
    ]
)
async def wavelength_to_frequency(
    interaction: discord.Interaction,
    wavelength: float,
    unit: str,
) -> None:
    if wavelength <= 0:
        await interaction.response.send_message("Wavelength must be greater than 0.", ephemeral=True)
        return

    _, wavelength_scale = WAVELENGTH_UNITS[unit]
    wavelength_m = wavelength * wavelength_scale
    frequency_hz = SPEED_OF_LIGHT_M_S / wavelength_m

    embed = build_conversion_embed(
        title="Wavelength to Frequency",
        source_value=wavelength,
        source_unit=unit,
        result_value=frequency_hz / 1_000_000.0,
        result_unit="MHz",
        extra_lines=[
            f"{format_value(frequency_hz / 1_000.0)} kHz",
            f"{format_value(frequency_hz)} Hz",
            f"Wavelength in meters: {format_value(wavelength_m)} m",
        ],
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(
    name="frequency_to_wavelength",
    description="Convert a frequency to wavelength",
)
@app_commands.describe(
    frequency="Frequency value to convert",
    unit="Unit for the frequency input",
)
@app_commands.choices(
    unit=[
        app_commands.Choice(name="Hz", value="Hz"),
        app_commands.Choice(name="kHz", value="kHz"),
        app_commands.Choice(name="MHz", value="MHz"),
        app_commands.Choice(name="GHz", value="GHz"),
    ]
)
async def frequency_to_wavelength(
    interaction: discord.Interaction,
    frequency: float,
    unit: str,
) -> None:
    if frequency <= 0:
        await interaction.response.send_message("Frequency must be greater than 0.", ephemeral=True)
        return

    _, frequency_scale = FREQUENCY_UNITS[unit]
    frequency_hz = frequency * frequency_scale
    wavelength_m = SPEED_OF_LIGHT_M_S / frequency_hz

    embed = build_conversion_embed(
        title="Frequency to Wavelength",
        source_value=frequency,
        source_unit=unit,
        result_value=wavelength_m,
        result_unit="m",
        extra_lines=[
            f"{format_value(wavelength_m * 100.0)} cm",
            f"{format_value(wavelength_m / 0.3048)} ft",
            f"Frequency in MHz: {format_value(frequency_hz / 1_000_000.0)} MHz",
        ],
    )
    await interaction.response.send_message(embed=embed)


if __name__ == "__main__":
    bot.run(TOKEN)
