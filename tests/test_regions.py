from pipeline import regions


def test_place_names_override_wrong_model_region():
    egypt = ["Train collision in Egypt's Giza kills 4", "Trains collide near Cairo, killing 4",
             "Egypt train crash leaves several dead"]
    assert regions.resolve_region("asia", egypt, "us") == "middle_east"
    krakow = ["Gunman kills 6 in Krakow", "Poland mourns victims of Krakow shooting", "Six dead in Polish city"]
    assert regions.resolve_region("middle_east", krakow, "europe") == "europe"


def test_model_region_kept_when_places_are_mixed_or_absent():
    mixed = ["Trump and Netanyahu meet in Washington", "Israel and US sign deal", "Washington hosts Israeli PM"]
    assert regions.region_from_text(mixed) is None
    assert regions.resolve_region("middle_east", mixed, "us") == "middle_east"
    assert regions.resolve_region("global", ["Stocks fall on AI worries", "AI stocks slide"], "us") == "global"


def test_outlet_majority_is_last_resort():
    assert regions.resolve_region(None, ["Stocks fall", "Markets slide"], "europe") == "europe"


def test_us_abbreviation_not_matched_inside_words():
    assert regions.region_from_text(["Focus on bonuses", "Campus news today"]) is None
