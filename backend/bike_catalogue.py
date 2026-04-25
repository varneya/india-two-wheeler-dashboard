"""
Curated catalogue of motorcycles & scooters sold in India.

This is the SOURCE OF TRUTH used to validate auto-discovered models.
Only bikes that match an entry here are persisted; everything else is
rejected as a false positive.

Each entry:
  canonical    — the bike's display model name (without brand prefix)
  aliases      — alternate names / URL-slug fragments that should map
                 to this canonical bike (lowercased substrings)
  bikewale     — explicit BikeWale slug for review scraping (optional;
                 if omitted we'll auto-construct & verify it)
  keywords     — regex keywords for the per-bike extractor (defaults to
                 [canonical, first-word(canonical)])
  status       — "current" or "discontinued"

Update this file when new models launch. The dashboard will pick up
changes on the next backend restart.

Sources cross-checked:
  - OEM India websites (yamaha-motor-india.com, honda2wheelersindia.com,
    heromotocorp.com, bajajauto.com, tvsmotor.com, royalenfield.com,
    suzukimotorcycle.co.in, ktm.com/in, aprilia.com/in_IN,
    kawasaki-india.com, bmw-motorrad.in, triumphmotorcycles.in)
  - BikeWale brand pages
"""

from __future__ import annotations

# Brand metadata — display name + the URL prefix used in RushLane links.
BRANDS: dict[str, dict] = {
    "yamaha":          {"display": "Yamaha"},
    "honda":           {"display": "Honda"},
    "hero":            {"display": "Hero"},
    "bajaj":           {"display": "Bajaj"},
    "tvs":             {"display": "TVS"},
    "royal-enfield":   {"display": "Royal Enfield"},
    "suzuki":          {"display": "Suzuki"},
    "ktm":             {"display": "KTM"},
    "aprilia":         {"display": "Aprilia"},
    "kawasaki":        {"display": "Kawasaki"},
    "harley-davidson": {"display": "Harley-Davidson"},
    "triumph":         {"display": "Triumph"},
    "ducati":          {"display": "Ducati"},
    "bmw":             {"display": "BMW"},
    "husqvarna":       {"display": "Husqvarna"},
}


# -----------------------------------------------------------------------------
# Per-brand model lists
# -----------------------------------------------------------------------------

CATALOGUE: dict[str, list[dict]] = {
    "yamaha": [
        {"canonical": "FZ",         "aliases": ["fz", "fzs", "fz-s", "fz s"],            "bikewale": "yamaha-bikes/fz",          "keywords": ["FZ"]},
        {"canonical": "R15",        "aliases": ["r15", "r-15", "yzf-r15", "yzf r15"],    "bikewale": "yamaha-bikes/r15-v4",      "keywords": ["R15", "R 15"]},
        {"canonical": "MT-15",      "aliases": ["mt15", "mt-15", "mt 15"],               "bikewale": "yamaha-bikes/mt-15",       "keywords": ["MT-15", "MT 15", "MT15"]},
        {"canonical": "XSR 155",    "aliases": ["xsr155", "xsr"],                        "bikewale": "yamaha-bikes/xsr-155",     "keywords": ["XSR 155", "XSR"]},
        {"canonical": "Rayzr",      "aliases": ["rayzr", "ray-zr", "ray zr"],            "bikewale": "yamaha-bikes/rayzr",       "keywords": ["Rayzr", "RayZR", "Ray ZR"]},
        {"canonical": "Fascino",    "aliases": ["fascino", "fascino-125"],               "bikewale": "yamaha-bikes/fascino-125", "keywords": ["Fascino"]},
        {"canonical": "Aerox 155",  "aliases": ["aerox", "aerox-155"],                   "bikewale": "yamaha-bikes/aerox-155",   "keywords": ["Aerox"]},
        {"canonical": "R3",         "aliases": ["r3", "yzf-r3"],                         "bikewale": "yamaha-bikes/yzf-r3",      "keywords": ["R3"]},
        {"canonical": "MT-03",      "aliases": ["mt03", "mt-03", "mt 03"],               "bikewale": "yamaha-bikes/mt-03",       "keywords": ["MT-03", "MT 03"]},
    ],

    "honda": [
        {"canonical": "Activa",     "aliases": ["activa", "activa-6g", "activa 6g", "activa-125"], "bikewale": "honda-bikes/activa", "keywords": ["Activa"]},
        {"canonical": "Shine",      "aliases": ["shine", "sp-shine", "shine-100", "shine-125"],    "bikewale": "honda-bikes/shine",  "keywords": ["Shine"]},
        {"canonical": "Dio",        "aliases": ["dio", "dio-125"],                                   "bikewale": "honda-bikes/dio",    "keywords": ["Dio"]},
        {"canonical": "Unicorn",    "aliases": ["unicorn"],                                          "bikewale": "honda-bikes/unicorn","keywords": ["Unicorn"]},
        {"canonical": "SP 125",     "aliases": ["sp125", "sp-125", "sp 125"],                        "bikewale": "honda-bikes/sp-125", "keywords": ["SP 125", "SP-125"]},
        {"canonical": "Hornet 2.0", "aliases": ["hornet", "cb-hornet", "hornet-2-0"],                "bikewale": "honda-bikes/hornet-2-0", "keywords": ["Hornet"]},
        {"canonical": "CB350",      "aliases": ["cb350", "cb-350", "highness", "rs"],                "bikewale": "honda-bikes/cb350",  "keywords": ["CB350", "CB 350"]},
        {"canonical": "CB300F",     "aliases": ["cb300f", "cb-300", "cb300"],                        "bikewale": "honda-bikes/cb300f", "keywords": ["CB300", "CB 300"]},
        {"canonical": "CB200X",     "aliases": ["cb200", "cb200x", "cb-200"],                        "bikewale": "honda-bikes/cb200x", "keywords": ["CB200"]},
        {"canonical": "Grazia",     "aliases": ["grazia"],                                           "bikewale": "honda-bikes/grazia", "keywords": ["Grazia"]},
        {"canonical": "NX500",      "aliases": ["nx500", "nx-500"],                                  "bikewale": "honda-bikes/nx500",  "keywords": ["NX500"]},
        {"canonical": "NX200",      "aliases": ["nx200", "nx-200"],                                  "bikewale": "honda-bikes/nx200",  "keywords": ["NX200"]},
    ],

    "hero": [
        {"canonical": "Splendor",   "aliases": ["splendor", "splendor-plus", "splendor-ismart"],     "bikewale": "hero-bikes/splendor-plus","keywords": ["Splendor"]},
        {"canonical": "Passion",    "aliases": ["passion", "passion-pro", "passion-plus"],           "bikewale": "hero-bikes/passion-pro",   "keywords": ["Passion"]},
        {"canonical": "Glamour",    "aliases": ["glamour"],                                          "bikewale": "hero-bikes/glamour",       "keywords": ["Glamour"]},
        {"canonical": "HF Deluxe",  "aliases": ["hf", "hf-deluxe", "hf deluxe"],                     "bikewale": "hero-bikes/hf-deluxe",     "keywords": ["HF Deluxe", "HF"]},
        {"canonical": "Xpulse 200", "aliases": ["xpulse", "xpulse-200", "xpulse-4v"],                "bikewale": "hero-bikes/xpulse-200-4v", "keywords": ["Xpulse"]},
        {"canonical": "Xtreme",     "aliases": ["xtreme", "xtreme-160r", "xtreme-200s", "xtreme-440"], "bikewale": "hero-bikes/xtreme-160r-4v","keywords": ["Xtreme"]},
        {"canonical": "Destini",    "aliases": ["destini", "destini-125"],                           "bikewale": "hero-bikes/destini-125",   "keywords": ["Destini"]},
        {"canonical": "Vida",       "aliases": ["vida", "vida-v1"],                                  "bikewale": "hero-bikes/vida-v1",       "keywords": ["Vida"]},
        {"canonical": "Xoom",       "aliases": ["xoom", "xoom-110", "xoom-125"],                     "bikewale": "hero-bikes/xoom-110",      "keywords": ["Xoom"]},
        {"canonical": "Maestro",    "aliases": ["maestro"],                                          "bikewale": "hero-bikes/maestro-edge",  "keywords": ["Maestro"]},
        {"canonical": "Karizma",    "aliases": ["karizma", "karizma-xmr"],                           "bikewale": "hero-bikes/karizma-xmr",   "keywords": ["Karizma"]},
        {"canonical": "Mavrick 440","aliases": ["mavrick", "mavrick-440"],                           "bikewale": "hero-bikes/mavrick-440",   "keywords": ["Mavrick"]},
    ],

    "bajaj": [
        {"canonical": "Pulsar",     "aliases": ["pulsar", "pulsar-150", "pulsar-220", "pulsar-ns200", "pulsar-rs200", "pulsar-n160", "pulsar-n250", "pulsar-n125"], "bikewale": "bajaj-bikes/pulsar-n150", "keywords": ["Pulsar"]},
        {"canonical": "Platina",    "aliases": ["platina", "platina-100", "platina-110"],            "bikewale": "bajaj-bikes/platina-110",  "keywords": ["Platina"]},
        {"canonical": "Avenger",    "aliases": ["avenger", "avenger-220", "avenger-160", "avenger-cruise"], "bikewale": "bajaj-bikes/avenger-cruise-220","keywords": ["Avenger"]},
        {"canonical": "Dominar",    "aliases": ["dominar", "dominar-400", "dominar-250"],            "bikewale": "bajaj-bikes/dominar-400",  "keywords": ["Dominar"]},
        {"canonical": "CT",         "aliases": ["ct", "ct-100", "ct-110", "ct-125"],                 "bikewale": "bajaj-bikes/ct-125x",      "keywords": ["CT 100", "CT 110", "CT 125"]},
        {"canonical": "Chetak",     "aliases": ["chetak", "chetak-2901", "chetak-3202"],             "bikewale": "bajaj-bikes/chetak",       "keywords": ["Chetak"]},
        {"canonical": "Freedom 125","aliases": ["freedom", "freedom-125"],                           "bikewale": "bajaj-bikes/freedom-125",  "keywords": ["Freedom"]},
    ],

    "tvs": [
        {"canonical": "Apache",     "aliases": ["apache", "apache-rtr", "apache-rr"],                "bikewale": "tvs-bikes/apache-rtr-160-4v","keywords": ["Apache"]},
        {"canonical": "Jupiter",    "aliases": ["jupiter", "jupiter-125"],                           "bikewale": "tvs-bikes/jupiter",         "keywords": ["Jupiter"]},
        {"canonical": "NTorq",      "aliases": ["ntorq", "n-torq"],                                  "bikewale": "tvs-bikes/ntorq-125",        "keywords": ["NTorq", "Ntorq"]},
        {"canonical": "Raider",     "aliases": ["raider", "raider-125"],                             "bikewale": "tvs-bikes/raider-125",       "keywords": ["Raider"]},
        {"canonical": "Ronin",      "aliases": ["ronin"],                                            "bikewale": "tvs-bikes/ronin",            "keywords": ["Ronin"]},
        {"canonical": "iQube",      "aliases": ["iqube", "i-qube"],                                  "bikewale": "tvs-bikes/iqube-electric",   "keywords": ["iQube", "Iqube"]},
        {"canonical": "XL100",      "aliases": ["xl", "xl100", "xl-100"],                            "bikewale": "tvs-bikes/xl100",            "keywords": ["XL100", "XL 100"]},
        {"canonical": "Star City",  "aliases": ["star", "star-city", "star-plus"],                   "bikewale": "tvs-bikes/star-city-plus",   "keywords": ["Star City"]},
        {"canonical": "Radeon",     "aliases": ["radeon"],                                           "bikewale": "tvs-bikes/radeon",           "keywords": ["Radeon"]},
        {"canonical": "Sport",      "aliases": ["sport", "tvs-sport"],                               "bikewale": "tvs-bikes/sport",            "keywords": ["Sport"]},
    ],

    "royal-enfield": [
        {"canonical": "Classic",         "aliases": ["classic", "classic-350"],                     "bikewale": "royal-enfield-bikes/classic-350","keywords": ["Classic 350", "Classic"]},
        {"canonical": "Bullet",          "aliases": ["bullet", "bullet-350"],                       "bikewale": "royal-enfield-bikes/bullet-350","keywords": ["Bullet"]},
        {"canonical": "Meteor",          "aliases": ["meteor", "meteor-350"],                       "bikewale": "royal-enfield-bikes/meteor-350","keywords": ["Meteor"]},
        {"canonical": "Himalayan",       "aliases": ["himalayan", "himalayan-450"],                 "bikewale": "royal-enfield-bikes/himalayan-450","keywords": ["Himalayan"]},
        {"canonical": "Hunter",          "aliases": ["hunter", "hunter-350"],                       "bikewale": "royal-enfield-bikes/hunter-350","keywords": ["Hunter"]},
        {"canonical": "Interceptor 650", "aliases": ["interceptor", "interceptor-650"],             "bikewale": "royal-enfield-bikes/interceptor-650","keywords": ["Interceptor"]},
        {"canonical": "Continental GT",  "aliases": ["continental", "continental-gt", "gt-650"],    "bikewale": "royal-enfield-bikes/continental-gt-650","keywords": ["Continental GT", "Continental"]},
        {"canonical": "Super Meteor 650","aliases": ["super-meteor", "super-meteor-650"],           "bikewale": "royal-enfield-bikes/super-meteor-650","keywords": ["Super Meteor"]},
        {"canonical": "Shotgun 650",     "aliases": ["shotgun", "shotgun-650"],                     "bikewale": "royal-enfield-bikes/shotgun-650","keywords": ["Shotgun"]},
        {"canonical": "Guerrilla 450",   "aliases": ["guerrilla", "guerrilla-450"],                 "bikewale": "royal-enfield-bikes/guerrilla-450","keywords": ["Guerrilla"]},
    ],

    "suzuki": [
        {"canonical": "Access 125",  "aliases": ["access", "access-125"],                            "bikewale": "suzuki-bikes/access-125", "keywords": ["Access"]},
        {"canonical": "Burgman",     "aliases": ["burgman", "burgman-street"],                       "bikewale": "suzuki-bikes/burgman-street","keywords": ["Burgman"]},
        {"canonical": "Gixxer",      "aliases": ["gixxer", "gixxer-sf", "gixxer-150", "gixxer-250"], "bikewale": "suzuki-bikes/gixxer",      "keywords": ["Gixxer"]},
        {"canonical": "V-Strom",     "aliases": ["v-strom", "vstrom", "v-strom-250", "v-strom-800"], "bikewale": "suzuki-bikes/v-strom-sx",  "keywords": ["V-Strom", "Vstrom"]},
        {"canonical": "Hayabusa",    "aliases": ["hayabusa"],                                        "bikewale": "suzuki-bikes/hayabusa",    "keywords": ["Hayabusa"]},
        {"canonical": "Avenis",      "aliases": ["avenis", "avenis-125"],                            "bikewale": "suzuki-bikes/avenis-125",  "keywords": ["Avenis"]},
        {"canonical": "Intruder",    "aliases": ["intruder", "intruder-150"],                        "bikewale": "suzuki-bikes/intruder-150","keywords": ["Intruder"]},
    ],

    "ktm": [
        {"canonical": "Duke 125",    "aliases": ["duke-125", "duke 125", "125-duke"],                "bikewale": "ktm-bikes/125-duke",         "keywords": ["Duke 125", "125 Duke"]},
        {"canonical": "Duke 200",    "aliases": ["duke-200", "duke 200", "200-duke"],                "bikewale": "ktm-bikes/200-duke",         "keywords": ["Duke 200", "200 Duke"]},
        {"canonical": "Duke 250",    "aliases": ["duke-250", "duke 250", "250-duke"],                "bikewale": "ktm-bikes/250-duke",         "keywords": ["Duke 250", "250 Duke"]},
        {"canonical": "Duke 390",    "aliases": ["duke-390", "duke 390", "390-duke"],                "bikewale": "ktm-bikes/390-duke",         "keywords": ["Duke 390", "390 Duke"]},
        {"canonical": "RC 125",      "aliases": ["rc-125", "rc 125"],                                "bikewale": "ktm-bikes/rc-125",           "keywords": ["RC 125"]},
        {"canonical": "RC 200",      "aliases": ["rc-200", "rc 200"],                                "bikewale": "ktm-bikes/rc-200",           "keywords": ["RC 200"]},
        {"canonical": "RC 390",      "aliases": ["rc-390", "rc 390"],                                "bikewale": "ktm-bikes/rc-390",           "keywords": ["RC 390"]},
        {"canonical": "250 Adventure","aliases": ["adventure-250", "250-adventure", "adv-250"],      "bikewale": "ktm-bikes/250-adventure",    "keywords": ["250 Adventure", "ADV 250"]},
        {"canonical": "390 Adventure","aliases": ["adventure-390", "390-adventure", "adv-390", "adventure"], "bikewale": "ktm-bikes/390-adventure", "keywords": ["390 Adventure", "Adventure"]},
    ],

    "aprilia": [
        {"canonical": "SR 125",      "aliases": ["sr-125", "sr125"],                                 "bikewale": "aprilia-bikes/sr-125",       "keywords": ["SR 125"]},
        {"canonical": "SR 160",      "aliases": ["sr-160", "sr160"],                                 "bikewale": "aprilia-bikes/sr-160",       "keywords": ["SR 160"]},
        {"canonical": "SXR",         "aliases": ["sxr", "sxr-125", "sxr-160"],                       "bikewale": "aprilia-bikes/sxr-160",      "keywords": ["SXR"]},
        {"canonical": "RS 457",      "aliases": ["rs-457", "rs457"],                                 "bikewale": "aprilia-bikes/rs-457",       "keywords": ["RS 457"]},
        {"canonical": "Tuono 660",   "aliases": ["tuono", "tuono-660"],                              "bikewale": "aprilia-bikes/tuono-660",    "keywords": ["Tuono"]},
        {"canonical": "Storm 125",   "aliases": ["storm", "storm-125"],                              "bikewale": "aprilia-bikes/storm-125",    "keywords": ["Storm 125"]},
    ],

    "kawasaki": [
        {"canonical": "Ninja",       "aliases": ["ninja", "ninja-300", "ninja-400", "ninja-650", "ninja-zx"], "bikewale": "kawasaki-bikes/ninja-650","keywords": ["Ninja"]},
        {"canonical": "Z650",        "aliases": ["z650", "z-650"],                                   "bikewale": "kawasaki-bikes/z650",        "keywords": ["Z650"]},
        {"canonical": "Z900",        "aliases": ["z900", "z-900"],                                   "bikewale": "kawasaki-bikes/z900",        "keywords": ["Z900"]},
        {"canonical": "Vulcan",      "aliases": ["vulcan"],                                          "bikewale": "kawasaki-bikes/vulcan-s",    "keywords": ["Vulcan"]},
        {"canonical": "Versys",      "aliases": ["versys"],                                          "bikewale": "kawasaki-bikes/versys-650",  "keywords": ["Versys"]},
        {"canonical": "Eliminator",  "aliases": ["eliminator"],                                      "bikewale": "kawasaki-bikes/eliminator",  "keywords": ["Eliminator"]},
    ],

    "harley-davidson": [
        {"canonical": "X440",        "aliases": ["x440", "x-440"],                                   "bikewale": "harley-davidson-bikes/x440", "keywords": ["X440"]},
        {"canonical": "Pan America", "aliases": ["pan-america", "pan america"],                      "bikewale": "harley-davidson-bikes/pan-america-1250","keywords": ["Pan America"]},
        {"canonical": "Sportster S", "aliases": ["sportster"],                                       "bikewale": "harley-davidson-bikes/sportster-s","keywords": ["Sportster"]},
    ],

    "triumph": [
        {"canonical": "Speed 400",   "aliases": ["speed-400", "speed 400"],                          "bikewale": "triumph-bikes/speed-400",    "keywords": ["Speed 400"]},
        {"canonical": "Scrambler 400","aliases": ["scrambler", "scrambler-400"],                     "bikewale": "triumph-bikes/scrambler-400-x","keywords": ["Scrambler 400", "Scrambler"]},
        {"canonical": "Tiger",       "aliases": ["tiger", "tiger-900", "tiger-1200"],                "bikewale": "triumph-bikes/tiger-900",    "keywords": ["Tiger"]},
        {"canonical": "Bonneville",  "aliases": ["bonneville", "bonneville-t100", "bonneville-t120"],"bikewale": "triumph-bikes/bonneville-t120","keywords": ["Bonneville"]},
        {"canonical": "Street Triple","aliases": ["street-triple", "street triple"],                  "bikewale": "triumph-bikes/street-triple-r","keywords": ["Street Triple"]},
    ],

    "ducati": [
        {"canonical": "Scrambler",   "aliases": ["scrambler"],                                       "bikewale": "ducati-bikes/scrambler-icon","keywords": ["Scrambler"]},
        {"canonical": "Monster",     "aliases": ["monster", "monster-821", "monster-937"],           "bikewale": "ducati-bikes/monster",       "keywords": ["Monster"]},
        {"canonical": "Panigale",    "aliases": ["panigale", "panigale-v2", "panigale-v4"],          "bikewale": "ducati-bikes/panigale-v4",   "keywords": ["Panigale"]},
        {"canonical": "Multistrada", "aliases": ["multistrada"],                                     "bikewale": "ducati-bikes/multistrada-v4","keywords": ["Multistrada"]},
        {"canonical": "DesertX",     "aliases": ["desertx", "desert-x"],                             "bikewale": "ducati-bikes/desertx",       "keywords": ["DesertX"]},
        {"canonical": "Diavel",      "aliases": ["diavel"],                                          "bikewale": "ducati-bikes/diavel-v4",     "keywords": ["Diavel"]},
    ],

    "bmw": [
        {"canonical": "G310R",       "aliases": ["g310r", "g-310-r"],                                "bikewale": "bmw-bikes/g-310-r",          "keywords": ["G310R", "G 310 R"]},
        {"canonical": "G310GS",      "aliases": ["g310gs", "g-310-gs"],                              "bikewale": "bmw-bikes/g-310-gs",         "keywords": ["G310GS", "G 310 GS"]},
        {"canonical": "F900XR",      "aliases": ["f900xr", "f-900-xr"],                              "bikewale": "bmw-bikes/f-900-xr",         "keywords": ["F900XR"]},
        {"canonical": "S1000RR",     "aliases": ["s1000rr"],                                         "bikewale": "bmw-bikes/s-1000-rr",        "keywords": ["S1000RR"]},
        {"canonical": "R 1300 GS",   "aliases": ["r1300gs", "r-1300-gs"],                            "bikewale": "bmw-bikes/r-1300-gs",        "keywords": ["R 1300 GS"]},
        {"canonical": "K 1600",      "aliases": ["k1600", "k-1600"],                                 "bikewale": "bmw-bikes/k-1600-grand-america","keywords": ["K 1600"]},
    ],

    "husqvarna": [
        {"canonical": "Svartpilen",  "aliases": ["svartpilen", "svartpilen-250", "svartpilen-401"],  "bikewale": "husqvarna-bikes/svartpilen-401","keywords": ["Svartpilen"]},
        {"canonical": "Vitpilen",    "aliases": ["vitpilen", "vitpilen-250"],                        "bikewale": "husqvarna-bikes/vitpilen-250","keywords": ["Vitpilen"]},
    ],
}


# -----------------------------------------------------------------------------
# Per-bike minimum monthly units (sanity floor)
# -----------------------------------------------------------------------------
#
# When the extractor finds a number near a bike's keyword, anything below the
# floor for that bike gets rejected as a misparse. This catches the classic
# "Activa = 125 units" bug where the regex picks up a CC displacement near the
# bike's name in prose.
#
# Tuned conservatively from publicly available Indian monthly sales data. The
# numbers are floors, not estimates — set them ~5x below the bike's typical
# trough month so legitimate bad months still pass through.

DEFAULT_MIN_UNITS = 5

MIN_UNITS_BY_MODEL: dict[str, int] = {
    # ---- Best-sellers (~50-450k/month) ----
    "Splendor":   50_000,
    "Activa":     50_000,
    "Shine":      30_000,
    "Pulsar":     30_000,
    "Jupiter":    30_000,
    "HF Deluxe":  15_000,
    "Apache":     10_000,
    "Access 125": 10_000,
    "Platina":    10_000,
    "Classic":     8_000,
    "Hunter":      5_000,
    "NTorq":       5_000,
    "Raider":      5_000,
    "Dio":         5_000,
    "XL100":       3_000,
    "Rayzr":       3_000,
    "Bullet":      3_000,
    "Chetak":      3_000,
    "iQube":       2_000,
    "FZ":          2_000,
    "Unicorn":     2_000,
    "SP 125":      2_000,

    # ---- Mid-volume (~3-30k/month) ----
    "R15":           1_000,
    "MT-15":         1_000,
    "Fascino":       1_000,
    "Glamour":       1_000,
    "Xtreme":        1_000,
    "Passion":       1_000,
    "Destini":       1_000,
    "Freedom 125":   1_000,
    "Meteor":        1_000,
    "CT":            1_000,
    "Burgman":       1_000,
    "Gixxer":        1_000,

    # ---- Lower volume (~200-3k/month) ----
    "Star City":     500,
    "Sport":         500,
    "Maestro":       500,
    "Hornet 2.0":    500,
    "Xoom":          500,
    "Aerox 155":     200,
    "Avenis":        200,
    "Vida":          200,
    "Xpulse 200":    200,
    "Radeon":        200,
    "CB350":         200,
    "Grazia":        200,
    "Avenger":       200,
    "Dominar":       200,
    "Himalayan":     200,
    "Interceptor 650": 200,
    "Guerrilla 450": 200,
    "Karizma":       100,
    "Mavrick 440":   100,
    "Ronin":         100,
    "XSR 155":       100,
    "Super Meteor 650": 100,

    # ---- Premium / KTM / niche (~5-200/month) ----
    "Duke 125":         100,
    "Duke 200":         100,
    "Duke 390":         100,
    "390 Adventure":    100,
    "Continental GT":    50,
    "Shotgun 650":       50,
    "Intruder":          50,
    "Duke 250":          50,
    "RC 125":            50,
    "RC 200":            50,
    "RC 390":            50,
    "250 Adventure":     50,
    "CB300F":            50,
    "CB200X":            50,
    "NX200":             50,
    "NX500":             50,
    # Imports / very low volume
    "R3":      5,
    "MT-03":   5,
    "Hayabusa": 5,
}


def min_units_for(canonical: str) -> int:
    """Return the per-bike monthly-units floor (defaults to DEFAULT_MIN_UNITS)."""
    return MIN_UNITS_BY_MODEL.get(canonical, DEFAULT_MIN_UNITS)


# -----------------------------------------------------------------------------
# Lookup helpers
# -----------------------------------------------------------------------------

def all_brands() -> list[dict]:
    """Returns [{id, display, model_count}, ...]."""
    return [
        {"id": bid, "display": meta["display"], "model_count": len(CATALOGUE.get(bid, []))}
        for bid, meta in BRANDS.items()
    ]


def get_brand_models(brand_id: str) -> list[dict]:
    return CATALOGUE.get(brand_id, [])


def find_model(brand_id: str, candidate: str) -> dict | None:
    """
    Match a discovered candidate name (e.g. "Mt 15", "rayzr", "xsr155")
    against the catalogue for `brand_id`. Case-insensitive, alias-aware.
    Returns the catalogue entry or None.
    """
    if brand_id not in CATALOGUE:
        return None
    cand = candidate.strip().lower()
    cand_compact = cand.replace(" ", "").replace("-", "")
    for entry in CATALOGUE[brand_id]:
        canonical_lc = entry["canonical"].lower()
        canonical_compact = canonical_lc.replace(" ", "").replace("-", "")
        if cand == canonical_lc or cand_compact == canonical_compact:
            return entry
        for alias in entry.get("aliases", []):
            alias_lc = alias.lower()
            alias_compact = alias_lc.replace(" ", "").replace("-", "")
            if cand == alias_lc or cand_compact == alias_compact:
                return entry
            # Substring match — a discovered "rayzr" should match alias "rayzr"
            # but we need to be careful; require alias to be the leading token
            if cand.startswith(alias_lc + " ") or cand.startswith(alias_lc + "-"):
                return entry
    return None


def make_bike_id(brand_id: str, canonical: str) -> str:
    import re
    slug = re.sub(r"[^a-z0-9]+", "-", canonical.lower()).strip("-")
    return f"{brand_id}-{slug}"
