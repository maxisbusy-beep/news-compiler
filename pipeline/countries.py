"""Country label shown before each headline ("USA – ...").

The model proposes a country; it is kept only if place names in the story's
headlines support it. Otherwise the country whose place names clearly
dominate the headlines is used; failing that, no label.
"""
from __future__ import annotations

import re
from collections import Counter

# Short display name -> (region, alternatives matched as whole words, case-sensitive)
COUNTRIES = {
    "USA": ("us", r"United States|U\.S\.|US|USA|America|American|Americans|Washington|White House|Congress|Senate|"
                  r"Pentagon|Trump|New York|NYC|NYPD|California|Texas|Florida|Chicago|Los Angeles|Brooklyn|"
                  r"Alabama|Arizona|Michigan|Ohio|Pennsylvania|Virginia|North Carolina|South Carolina|Minnesota|"
                  r"Colorado|Louisiana|Oregon|Seattle|Boston|Atlanta|Miami|Houston|Dallas|Supreme Court|"
                  r"Democrats|Republicans|GOP|Hegseth|Jeffries|Vance|Rubio|FBI|ICE"),
    "Canada": ("americas", r"Canada|Canadian|Canadians|Ottawa|Toronto|Montreal|Vancouver|Carney|Poilievre"),
    "Mexico": ("americas", r"Mexico|Mexican|Mexicans|Sheinbaum"),
    "Brazil": ("americas", r"Brazil|Brazilian|Brasília|Brasilia|Rio de Janeiro|São Paulo|Sao Paulo|Lula|Belém|Belem"),
    "Argentina": ("americas", r"Argentina|Argentine|Argentinian|Buenos Aires|Milei"),
    "Chile": ("americas", r"Chile|Chilean|Santiago de Chile"),
    "Colombia": ("americas", r"Colombia|Colombian|Bogotá|Bogota|Petro"),
    "Venezuela": ("americas", r"Venezuela|Venezuelan|Caracas|Maduro"),
    "Peru": ("americas", r"Peru|Peruvian|Lima"),
    "Cuba": ("americas", r"Cuba|Cuban|Havana"),
    "Haiti": ("americas", r"Haiti|Haitian|Port-au-Prince"),
    "Paraguay": ("americas", r"Paraguay|Paraguayan|Asunción|Asuncion|Peña|Pena"),
    "Uruguay": ("americas", r"Uruguay|Uruguayan|Montevideo"),
    "Ecuador": ("americas", r"Ecuador|Ecuadorian|Quito"),
    "Bolivia": ("americas", r"Bolivia|Bolivian|La Paz"),
    "UK": ("europe", r"UK|U\.K\.|Britain|British|England|English|London|Scotland|Scottish|Wales|Welsh|"
                     r"Northern Ireland|Starmer|Westminster|Downing Street|King Charles|Manchester|Birmingham"),
    "Ireland": ("europe", r"Ireland|Irish|Dublin"),
    "France": ("europe", r"France|French|Paris|Macron|Marseille|Lyon"),
    "Germany": ("europe", r"Germany|German|Germans|Berlin|Merz|Munich|Hamburg|Frankfurt|Bundestag|Bundeswehr"),
    "Italy": ("europe", r"Italy|Italian|Italians|Rome|Milan|Meloni|Tajani|Naples"),
    "Spain": ("europe", r"Spain|Spanish|Madrid|Barcelona|Sánchez|Sanchez"),
    "Portugal": ("europe", r"Portugal|Portuguese|Lisbon"),
    "Netherlands": ("europe", r"Netherlands|Dutch|Amsterdam|The Hague|Rotterdam"),
    "Belgium": ("europe", r"Belgium|Belgian"),
    "Switzerland": ("europe", r"Switzerland|Swiss|Geneva|Zurich|Bern"),
    "Austria": ("europe", r"Austria|Austrian|Vienna"),
    "Poland": ("europe", r"Poland|Polish|Poles|Warsaw|Krakow|Kraków|Tusk|Nawrocki"),
    "Czechia": ("europe", r"Czech|Czechia|Prague"),
    "Hungary": ("europe", r"Hungary|Hungarian|Budapest|Orbán|Orban"),
    "Romania": ("europe", r"Romania|Romanian|Bucharest"),
    "Greece": ("europe", r"Greece|Greek|Athens"),
    "Sweden": ("europe", r"Sweden|Swedish|Stockholm"),
    "Norway": ("europe", r"Norway|Norwegian|Oslo"),
    "Denmark": ("europe", r"Denmark|Danish|Copenhagen|Greenland"),
    "Finland": ("europe", r"Finland|Finnish|Helsinki"),
    "Ukraine": ("europe", r"Ukraine|Ukrainian|Ukrainians|Kyiv|Kiev|Zelensky|Zelenskyy|Odesa|Odessa|Kharkiv|Zaporizhzhia|Dnipro|Lviv"),
    "Russia": ("europe", r"Russia|Russian|Russians|Moscow|Kremlin|Putin|St Petersburg|Bryansk|Belgorod"),
    "Serbia": ("europe", r"Serbia|Serbian|Belgrade"),
    "Vatican": ("europe", r"Vatican|Holy See"),
    "Israel": ("middle_east", r"Israel|Israeli|Israelis|Netanyahu|Jerusalem|Tel Aviv|Knesset|Herzog|Eisenkot|IDF"),
    "Gaza": ("middle_east", r"Gaza|Gazans|Rafah|Khan Younis"),
    "West Bank": ("middle_east", r"West Bank|Ramallah|Jenin|Hebron|Nablus"),
    "Lebanon": ("middle_east", r"Lebanon|Lebanese|Beirut|Hezbollah"),
    "Syria": ("middle_east", r"Syria|Syrian|Syrians|Damascus|Aleppo|Sharaa"),
    "Iran": ("middle_east", r"Iran|Iranian|Iranians|Tehran|Khamenei|Pezeshkian"),
    "Iraq": ("middle_east", r"Iraq|Iraqi|Iraqis|Baghdad|Kurdistan"),
    "Saudi Arabia": ("middle_east", r"Saudi|Saudis|Saudi Arabia|Riyadh|Jeddah|Aramco|Mecca"),
    "Yemen": ("middle_east", r"Yemen|Yemeni|Houthi|Houthis|Sanaa|Sana'a|Aden"),
    "Qatar": ("middle_east", r"Qatar|Qatari|Doha"),
    "UAE": ("middle_east", r"UAE|Emirates|Emirati|Dubai|Abu Dhabi"),
    "Jordan": ("middle_east", r"Jordan|Jordanian|Amman"),
    "Turkey": ("middle_east", r"Turkey|Türkiye|Turkiye|Turkish|Ankara|Istanbul|Erdogan|Erdoğan"),
    "Egypt": ("middle_east", r"Egypt|Egyptian|Egyptians|Cairo|Giza|Sisi|el-Sissi|Alexandria"),
    "China": ("asia", r"China|Chinese|Beijing|Shanghai|Xi Jinping|Xi|Shenzhen|Xinjiang|Tibet"),
    "Hong Kong": ("asia", r"Hong Kong"),
    "Taiwan": ("asia", r"Taiwan|Taiwanese|Taipei"),
    "Japan": ("asia", r"Japan|Japanese|Tokyo|Osaka|Takaichi"),
    "South Korea": ("asia", r"South Korea|South Korean|Seoul|Lee Jae-myung"),
    "North Korea": ("asia", r"North Korea|North Korean|Pyongyang|Kim Jong Un"),
    "India": ("asia", r"India|Indian|Indians|New Delhi|Delhi|Mumbai|Modi|Bihar|Kolkata|Bengaluru|Chennai|Kerala|Ayodhya"),
    "Pakistan": ("asia", r"Pakistan|Pakistani|Islamabad|Karachi|Lahore"),
    "Bangladesh": ("asia", r"Bangladesh|Bangladeshi|Dhaka"),
    "Afghanistan": ("asia", r"Afghanistan|Afghan|Kabul|Taliban"),
    "Sri Lanka": ("asia", r"Sri Lanka|Sri Lankan|Colombo"),
    "Nepal": ("asia", r"Nepal|Nepali|Kathmandu"),
    "Myanmar": ("asia", r"Myanmar|Burma|Burmese|Yangon"),
    "Thailand": ("asia", r"Thailand|Thai|Bangkok"),
    "Vietnam": ("asia", r"Vietnam|Vietnamese|Hanoi"),
    "Philippines": ("asia", r"Philippines|Philippine|Filipino|Manila|Marcos"),
    "Indonesia": ("asia", r"Indonesia|Indonesian|Jakarta|Prabowo"),
    "Malaysia": ("asia", r"Malaysia|Malaysian|Kuala Lumpur|Anwar"),
    "Singapore": ("asia", r"Singapore|Singaporean"),
    "Cambodia": ("asia", r"Cambodia|Cambodian|Phnom Penh"),
    "Nigeria": ("africa", r"Nigeria|Nigerian|Lagos|Abuja|Tinubu"),
    "Kenya": ("africa", r"Kenya|Kenyan|Nairobi|Ruto"),
    "Ethiopia": ("africa", r"Ethiopia|Ethiopian|Addis Ababa"),
    "Sudan": ("africa", r"Sudan|Sudanese|Khartoum|Darfur|El Fasher|RSF"),
    "Somalia": ("africa", r"Somalia|Somali|Mogadishu"),
    "South Africa": ("africa", r"South Africa|South African|Johannesburg|Cape Town|Pretoria|ANC|Ramaphosa"),
    "DR Congo": ("africa", r"Congo|Congolese|Kinshasa|Goma"),
    "Senegal": ("africa", r"Senegal|Senegalese|Dakar|Kebemer"),
    "Mali": ("africa", r"Mali|Malian|Bamako"),
    "Libya": ("africa", r"Libya|Libyan|Tripoli|Benghazi"),
    "Morocco": ("africa", r"Morocco|Moroccan|Rabat|Casablanca"),
    "Algeria": ("africa", r"Algeria|Algerian|Algiers"),
    "Tunisia": ("africa", r"Tunisia|Tunisian|Tunis"),
    "Ghana": ("africa", r"Ghana|Ghanaian|Accra"),
    "Australia": ("oceania", r"Australia|Australian|Australians|Sydney|Melbourne|Canberra|Brisbane|Perth|Albanese"),
    "New Zealand": ("oceania", r"New Zealand|Kiwis|Wellington|Auckland|Luxon"),
}
WORLD = "World"
_PATTERNS = {c: re.compile(rf"(?<![\w.]){'(?:' + alts + ')'}(?![\w])") for c, (_, alts) in COUNTRIES.items()}
_ALIASES = {c.lower(): c for c in COUNTRIES} | {
    "united states": "USA", "us": "USA", "u.s.": "USA", "america": "USA", "united kingdom": "UK",
    "britain": "UK", "great britain": "UK", "england": "UK", "palestine": "Gaza", "palestinian territories": "Gaza",
    "türkiye": "Turkey", "turkiye": "Turkey", "korea": "South Korea", "republic of korea": "South Korea",
    "democratic republic of the congo": "DR Congo", "congo": "DR Congo", "czech republic": "Czechia",
    "united arab emirates": "UAE", "holy see": "Vatican", "global": WORLD, "world": WORLD, "international": WORLD,
}

DOMINANCE = 0.5  # share of country mentions a country needs to be picked from text alone


def normalize(name: str | None) -> str | None:
    if not name:
        return None
    return _ALIASES.get(name.strip().lower())


def mentions(titles: list[str]) -> Counter:
    """One vote per headline per country."""
    c = Counter()
    for t in titles:
        for country, pat in _PATTERNS.items():
            if pat.search(t):
                c[country] += 1
    return c


def country_from_text(titles: list[str]) -> str | None:
    c = mentions(titles)
    if not c:
        return None
    top, n = c.most_common(1)[0]
    return top if n >= 2 and n / sum(c.values()) >= DOMINANCE else None


def resolve_country(model_country: str | None, titles: list[str]) -> str:
    """Model's country if the headlines support it, else the text's clear
    winner, else "World" when the model said so, else no label ("")."""
    c = normalize(model_country)
    if c and c != WORLD and mentions(titles).get(c, 0) >= 1:
        return c
    text = country_from_text(titles)
    if text:
        return text
    return WORLD if c == WORLD else ""


def region_of(country: str) -> str | None:
    return COUNTRIES.get(country, (None,))[0]
