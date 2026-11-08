"""Cross-check a story's region against place names in its headlines.

The models mislabel regions now and then (Phase 5 benchmark: Egypt filed
under Asia, a Polish shooting under the Middle East). Place names in the
outlets' headlines are a better signal when they clearly agree.
"""
from __future__ import annotations

import re
from collections import Counter

PLACES = {
    "us": "United States|U\\.S\\.|US|USA|America|American|Americans|Washington|White House|Congress|Senate|"
          "Pentagon|Trump|New York|NYC|NYPD|California|Texas|Florida|Chicago|Los Angeles|Brooklyn|"
          "Alabama|Arizona|Georgia|Michigan|Ohio|Pennsylvania|Virginia|Carolina|Minnesota|Colorado|"
          "Louisiana|Oregon|Seattle|Boston|Atlanta|Miami|Houston|Dallas|Supreme Court|Democrats|Republicans|GOP",
    "europe": "Europe|European|EU|Brussels|Britain|British|UK|England|London|Scotland|Wales|Ireland|Dublin|"
              "France|French|Paris|Macron|Germany|German|Berlin|Merz|Munich|Italy|Italian|Rome|Spain|Spanish|"
              "Madrid|Portugal|Lisbon|Netherlands|Dutch|Amsterdam|Belgium|Poland|Polish|Krakow|Kraków|Warsaw|"
              "Ukraine|Ukrainian|Kyiv|Kiev|Zelensky|Russia|Russian|Moscow|Kremlin|Putin|Sweden|Swedish|"
              "Norway|Denmark|Finland|Austria|Vienna|Switzerland|Swiss|Greece|Greek|Athens|Hungary|Budapest|"
              "Czech|Prague|Romania|Bulgaria|Serbia|Croatia|Baltic|Lithuania|Latvia|Estonia|Vatican|Pope",
    "middle_east": "Middle East|Israel|Israeli|Israelis|Netanyahu|Jerusalem|Tel Aviv|Gaza|Hamas|West Bank|"
                   "Palestinian|Palestinians|Lebanon|Lebanese|Hezbollah|Beirut|Syria|Syrian|Damascus|Iran|"
                   "Iranian|Tehran|Iraq|Iraqi|Baghdad|Saudi|Riyadh|Aramco|Yemen|Houthi|Houthis|Qatar|Doha|"
                   "UAE|Dubai|Abu Dhabi|Kuwait|Oman|Bahrain|Jordan|Amman|Turkey|Turkish|Ankara|Istanbul|Erdogan|"
                   "Egypt|Egyptian|Cairo|Giza",
    "asia": "Asia|Asian|China|Chinese|Beijing|Shanghai|Hong Kong|Taiwan|Taipei|Japan|Japanese|Tokyo|"
            "Korea|Korean|Seoul|Pyongyang|India|Indian|Delhi|Mumbai|Modi|Bihar|Pakistan|Pakistani|Islamabad|"
            "Bangladesh|Dhaka|Afghanistan|Kabul|Sri Lanka|Nepal|Myanmar|Thailand|Thai|Bangkok|Vietnam|"
            "Hanoi|Philippines|Manila|Indonesia|Jakarta|Malaysia|Singapore|Cambodia|Kazakhstan",
    "africa": "Africa|African|Nigeria|Nigerian|Lagos|Kenya|Nairobi|Ethiopia|Sudan|Khartoum|Somalia|"
              "South Africa|Johannesburg|ANC|Congo|Ghana|Senegal|Mali|Niger|Libya|Libyan|Tripoli|Tunisia|"
              "Algeria|Morocco|Uganda|Tanzania|Rwanda|Zimbabwe|Mozambique|Cameroon|Sahel",
    "americas": "Canada|Canadian|Ottawa|Toronto|Mexico|Mexican|Brazil|Brazilian|Argentina|Milei|"
                "Buenos Aires|Chile|Colombia|Venezuela|Caracas|Peru|Cuba|Havana|Haiti|Paraguay|Uruguay|"
                "Ecuador|Bolivia|Guatemala|Honduras|Panama|Latin America",
    "oceania": "Australia|Australian|Sydney|Melbourne|Canberra|New Zealand|Wellington|Auckland|Fiji|"
               "Papua New Guinea|Pacific Islands",
}
_PATTERNS = {region: re.compile(rf"(?<![\w.])(?:{alts})(?![\w])") for region, alts in PLACES.items()}

# A region must have at least this share of all place mentions to override the model.
DOMINANCE = 0.6


def region_from_text(titles: list[str]) -> str | None:
    """Region whose place names clearly dominate the headlines, or None."""
    counts = Counter()
    for t in titles:
        for region, pat in _PATTERNS.items():
            if pat.search(t):
                counts[region] += 1  # one vote per headline per region
    if not counts:
        return None
    region, n = counts.most_common(1)[0]
    return region if n / sum(counts.values()) >= DOMINANCE and n >= 2 else None


def resolve_region(model_region: str | None, titles: list[str], outlet_majority: str) -> str:
    """Place names win when they clearly agree; then the model; then the outlets."""
    return region_from_text(titles) or model_region or outlet_majority
