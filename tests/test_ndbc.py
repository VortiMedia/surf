"""Offline tests for the NDBC source, against verbatim 44097 (Block Island) output
captured 2026-09-03. The live tests are marked `network` and assert quirks, not values."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
import pytest

from surf.sources import Http
from surf.ndbc import (
    MISSING,
    NdbcObservations,
    NdbcParseError,
    parse_spec,
    parse_txt,
    realtime_url,
)

SPEC = """\
#YY  MM DD hh mm WVHT  SwH  SwP  WWH  WWP SwD WWD  STEEPNESS  APD MWD
#yr  mo dy hr mn    m    m  sec    m  sec  -  degT     -      sec degT
2026 09 03 07 00  1.2  0.2 10.0  1.2  6.2  SE  SE      STEEP  4.6 137
2026 09 03 06 30  1.2  0.2 10.0  1.1  6.5  SE  SE      STEEP  4.5 134
2026 09 03 06 00  1.1   MM   MM  1.1  5.1 SSE ESE VERY_STEEP  4.4 115
"""

TXT = """\
#YY  MM DD hh mm WDIR WSPD GST  WVHT   DPD   APD MWD   PRES  ATMP  WTMP  DEWP  VIS PTDY  TIDE
#yr  mo dy hr mn degT m/s  m/s     m   sec   sec degT   hPa  degC  degC  degC  nmi  hPa    ft
2026 09 03 07 00 225  5.0  6.0   1.2     6   4.6 137     MM  22.5  23.0    MM   MM   MM    MM
2026 09 03 06 30  MM   MM   MM   1.2     6   4.5 134     MM  21.9  23.0    MM   MM   MM    MM
"""

OBSERVED_AT = datetime(2026, 9, 3, 7, 0, tzinfo=timezone.utc)


def clock(offset_minutes: int = 20):
    return lambda: OBSERVED_AT + timedelta(minutes=offset_minutes)


def fake_http(**files: str | int) -> Http:
    """An Http whose transport serves the given extensions; an int value is the
    status code to fail with."""

    def handler(request: httpx.Request) -> httpx.Response:
        ext = request.url.path.rsplit(".", 1)[-1]
        body = files.get(ext)
        if body is None:
            return httpx.Response(404, text="not found")
        if isinstance(body, int):
            return httpx.Response(body, text="error")
        return httpx.Response(200, text=body)

    return Http(client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_spec_line_round_trips_into_partitions():
    row = parse_spec(SPEC, "44097")[0]
    assert row.field.total_height_m == 1.2
    assert row.steepness == "STEEP"

    swell, windwave = row.field.partitions
    assert (swell.kind, swell.height_m, swell.period_s, swell.direction_deg) == (
        "swell", 0.2, 10.0, 135.0,
    )
    assert (windwave.kind, windwave.height_m, windwave.period_s, windwave.direction_deg) == (
        "windwave", 1.2, 6.2, 135.0,
    )


def test_primary_is_the_swell_not_the_bigger_windwave():
    """A 1.2m windwave outweighs a 0.2m swell in height, but the swell is the train
    that makes a wave."""
    row = parse_spec(SPEC, "44097")[0]
    assert row.field.primary.kind == "swell"


def test_missing_values_drop_the_partition_rather_than_guess():
    """Row 3 has SwH/SwP as MM; a half-known train would carry a wrong energy."""
    row = parse_spec(SPEC, "44097")[2]
    assert [p.kind for p in row.field.partitions] == ["windwave"]
    assert row.steepness == "VERY_STEEP"


def test_cardinal_and_numeric_directions_both_parse():
    """.spec reports compass points, .txt degrees."""
    spec = parse_spec(SPEC)[2].field
    assert spec.partitions[0].direction_deg == pytest.approx(112.5)  # ESE
    assert parse_txt(TXT)[0].partitions[0].direction_deg == 137.0


def test_txt_emits_a_total_partition_and_wind():
    field = parse_txt(TXT, "44097")[0]
    assert [p.kind for p in field.partitions] == ["total"]
    assert field.total_height_m == 1.2 and field.total_period_s == 6.0
    assert field.wind.speed_mps == 5.0 and field.wind.direction_deg == 225.0
    assert field.model == "ndbc/44097"


def test_mm_wind_becomes_no_wind_not_zero_wind():
    assert parse_txt(TXT)[1].wind is None


def test_month_column_is_not_confused_with_the_missing_token():
    """The month column is literally named MM, same as the missing-value string."""
    assert parse_txt(TXT)[0].time == OBSERVED_AT
    assert MISSING == "MM"


def test_rows_come_back_newest_first():
    times = [r.field.time for r in parse_spec(SPEC)]
    assert times == sorted(times, reverse=True)


def test_a_non_ndbc_body_raises_rather_than_parsing_to_silence():
    with pytest.raises(NdbcParseError):
        parse_spec("<html>404</html>")


def test_swden_is_refused_because_it_does_not_exist():
    with pytest.raises(ValueError, match="data_spec"):
        realtime_url("44097", "swden")
    assert realtime_url("44025", ".spec").endswith("/44025.spec")


def test_latest_merges_spec_partitions_with_txt_wind():
    obs = NdbcObservations(fake_http(spec=SPEC, txt=TXT), clock=clock())
    r = obs.latest("44097")
    assert r.status == "ok" and r.ok
    assert r.source == "ndbc/44097"
    assert [p.kind for p in r.value.partitions] == ["swell", "windwave"]
    assert r.value.wind.direction_deg == 225.0
    assert "steepness=STEEP" in r.note
    assert r.dropped == ()


def test_a_dead_txt_degrades_the_reading_instead_of_killing_it():
    """Losing wind must not lose the swell split."""
    obs = NdbcObservations(fake_http(spec=SPEC, txt=500), clock=clock())
    r = obs.latest("44097")
    assert r.status == "degraded" and r.ok
    assert len(r.value.partitions) == 2
    assert r.value.wind is None
    assert any(d.startswith("txt") for d in r.dropped)


def test_a_dead_spec_still_yields_a_total_and_says_the_split_is_gone():
    obs = NdbcObservations(fake_http(txt=TXT, spec=404), clock=clock())
    r = obs.latest("44097")
    assert r.status == "degraded" and r.ok
    assert [p.kind for p in r.value.partitions] == ["total"]
    assert "not separated" in r.note


def test_both_files_dead_fails_without_raising():
    obs = NdbcObservations(fake_http(), clock=clock())
    r = obs.latest("44097")
    assert r.status == "failed" and r.value is None and not r.ok
    assert len(r.dropped) == 2


def test_a_stale_report_is_degraded_and_says_how_old():
    """Observations only beat models while they are current."""
    obs = NdbcObservations(fake_http(spec=SPEC, txt=TXT), clock=clock(60 * 9))
    r = obs.latest("44097")
    assert r.status == "degraded"
    assert "stale by" in r.note and "age=540min" in r.note


def test_wind_from_a_distant_report_is_dropped_not_merged():
    stale_txt = TXT.replace("2026 09 03 07 00", "2026 09 03 02 00")
    obs = NdbcObservations(fake_http(spec=SPEC, txt=stale_txt), clock=clock())
    r = obs.latest("44097")
    assert r.value.wind is None
    assert any("wind" in d for d in r.dropped)


def test_the_breaker_turns_further_calls_into_skipped_not_failed():
    obs = NdbcObservations(fake_http(), clock=clock())
    for _ in range(3):
        obs.latest("44097")
    r = obs.latest("44025")
    assert r.status == "skipped" and r.value is None
    assert obs.preflight().status == "skipped"


def test_preflight_passes_on_a_parseable_probe():
    obs = NdbcObservations(fake_http(spec=SPEC, txt=TXT), clock=clock())
    r = obs.preflight()
    assert r.status == "ok" and r.value is True


def test_preflight_fails_on_a_200_that_is_not_a_buoy_file():
    obs = NdbcObservations(fake_http(spec="<html>maintenance</html>"), clock=clock())
    r = obs.preflight()
    assert r.status == "failed" and r.value is False


def test_reading_label_names_the_buoy_and_what_was_lost():
    obs = NdbcObservations(fake_http(spec=SPEC, txt=500), clock=clock())
    label = obs.latest("44097").label()
    assert label.startswith("ndbc/44097:degraded")
    assert "dropped=" in label


@pytest.mark.network
@pytest.mark.parametrize("buoy", ["44097", "44025", "44008"])
def test_live_spec_still_carries_the_split(buoy):
    obs = NdbcObservations()
    r = obs.latest(buoy)
    assert r.ok and r.value.partitions


@pytest.mark.network
def test_live_swden_is_still_a_404():
    """This file does not exist; if it ever appears, the spectral upgrade path opens."""
    r = httpx.get("https://www.ndbc.noaa.gov/data/realtime2/44097.swden", timeout=20)
    assert r.status_code == 404


SPEC_NO_SPLIT = """\
#YY  MM DD hh mm WVHT  SwH  SwP  WWH  WWP SwD WWD  STEEPNESS  APD MWD
#yr  mo dy hr mn    m    m  sec    m  sec  -  degT     -      sec degT
2026 09 03 07 00  1.2   MM   MM   MM   MM  MM  MM      STEEP  5.5  97
"""


def test_a_spec_with_no_split_falls_back_to_a_labelled_total():
    """44025 serves a .spec whose partitions are all MM; an empty wave field would
    read as flat."""
    obs = NdbcObservations(fake_http(spec=SPEC_NO_SPLIT, txt=TXT), clock=clock())
    r = obs.latest("44025")
    assert r.status == "degraded" and r.ok
    assert [p.kind for p in r.value.partitions] == ["total"]
    assert r.value.partitions[0].direction_deg == 97.0
    assert any("split" in d for d in r.dropped)
    assert "steepness=STEEP" in r.note
