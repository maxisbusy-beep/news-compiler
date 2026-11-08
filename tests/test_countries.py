import json

from pipeline import countries, write

from .test_checks_write import EGYPT, O


def test_model_country_kept_when_headlines_support_it():
    titles = ["Trump says Iran attack unlikely", "Trump tells CNN Iran strike unlikely if talks progress"]
    assert countries.resolve_country("United States", titles) == "USA"
    assert countries.resolve_country("Iran", titles) == "Iran"


def test_unsupported_model_country_replaced_by_text():
    titles = ["Train collision in Egypt's Giza kills 4", "Trains collide near Cairo", "Egypt train crash"]
    assert countries.resolve_country("India", titles) == "Egypt"
    assert countries.resolve_country(None, titles) == "Egypt"


def test_world_and_no_label():
    assert countries.resolve_country("World", ["AI stocks slide worldwide", "Markets fall on AI worries"]) == "World"
    assert countries.resolve_country(None, ["AI stocks slide", "Markets fall"]) == ""


def test_lowercase_us_is_not_the_country():
    assert countries.mentions(["Join us for the debate", "Tell us more"]).get("USA", 0) == 0
    assert countries.mentions(["US military fires on ship"])["USA"] == 1


def test_country_sets_region():
    assert countries.region_of("Egypt") == "middle_east"
    assert countries.region_of("Poland") == "europe"
    assert countries.region_of("") is None and countries.region_of("World") is None


def test_country_prefix_stripped_from_model_headline():
    assert write.strip_country_prefix("USA – Trump names Miller chief of staff") == "Trump names Miller chief of staff"
    assert write.strip_country_prefix("Israel: Herzog taps Eisenkot") == "Herzog taps Eisenkot"
    assert write.strip_country_prefix("Six killed in Krakow: police") == "Six killed in Krakow: police"


def test_generate_returns_country_and_region_from_it():
    llm = lambda p: json.dumps({"belongs": [0, 1, 2], "headline": "Egypt – Train collision in Egypt kills 4, injures 88",
                                "summary": "", "region": "asia", "country": "Egypt"})
    r = write.generate(EGYPT[:3], O, llm)
    assert r["country"] == "Egypt" and r["region"] == "middle_east"
    assert r["headline"] == "Train collision in Egypt kills 4, injures 88" and r["headline_source"] == "model"
