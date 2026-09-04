from surf.bands import BandObservation, derive_band_floors


def test_band_is_the_measured_minimum_for_a_supported_setup_type() -> None:
    bands = derive_band_floors(
        (
            BandObservation("beach", 1.4, 4),
            BandObservation("beach", 2.2, 5),
            BandObservation("beach", 1.1, 4),
            BandObservation("beach", 3.0, 3),
        )
    )
    band = bands["beach"]
    assert band.minimum_m == 1.1
    assert band.sample_count == 3
    assert band.basis == "measurement"
    assert "minimum" in band.render() and "no upper cap" in band.render()


def test_sparse_point_and_reef_bands_are_labelled_conventions() -> None:
    bands = derive_band_floors((BandObservation("point", 2.0, 5),))
    assert bands["point"].basis == "convention"
    assert bands["point"].sample_count == 1
    assert "depth-limited" in bands["point"].detail
    assert bands["reef"].basis == "convention"


def test_unknown_type_without_sessions_or_convention_has_no_band() -> None:
    bands = derive_band_floors((BandObservation("rivermouth", 0.8, 3),))
    assert "rivermouth" not in bands


def test_sparse_observed_beach_is_a_labelled_convention() -> None:
    band = derive_band_floors((BandObservation("beach", 1.2, 4),))["beach"]
    assert band.basis == "convention"
    assert "depth-limited" in band.detail
    assert "source=" in band.render()
