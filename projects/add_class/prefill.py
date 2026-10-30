"""Prefill the decision column of output/review_<wiki>.tsv (Claude 2026-10-28, for the user to check).

  python projects/add_class/prefill.py [--wiki en]

decision = 'P31 Qx' / 'P279 Qx' (the class may differ from the row's class: an override), empty = skip.
Default is the row's suggest + class for a single-class stub; SKIP_CLASS rows and several-class stubs not in
PICK are skipped. Book stubs follow the book data model: written work (Q47461344) for non-fiction, literary work
(Q7725634) for novels/poems (never P31 = book/novel, none-of constraint). Taxa, genes and proteins are left to
their own bots (an item there needs more than a P31).
"""
import argparse
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")

WRITTEN_WORK = "Q47461344"
LITERARY_WORK = "Q7725634"
SKIP_CLASS = {
    "Q35120",    # entity
    "Q4167836",  # Wikimedia category
    "Q16521",    # taxon
    "Q7187",     # gene
    "Q8054",     # protein
}
SKIP_STUB = {
    "Toy", "Doll", "Dog", "Pig", "Insect", "Virus", "Tree", "Mineral", "Number", "Polynomial", "Sino-Tibetan_language",
    "Motor_vehicle_company", "United_States_motor_vehicle_company", "Radio_organization", "Graphic_novel",
    "2010s_graphic_novel", "Book_art", "Order,_decoration,_and_medal",
}
HUMAN_OK = {"Saint", "Antigua_and_Barbuda_politician"}  # other 'human' rows are wrong (Polynomial, Travel_book, ...)
# several-class stubs: the class to use
PICK = {
    "United_States_publishing_company": "Q2085381", "Political_organization": "Q7210356",
    "Electronic_musical_instrument": "Q1327500", "United_States_retail_company": "Q4830453",
    "Inorganic_compound": "Q190065", "Medical_organization": "Q4287745", "Professional_association": "Q829080",
    "Technological_company": "Q18388277", "Unmanned_aerial_vehicle": "Q484000", "Spanish_political_party": "Q6065085",
    "Amusement_park": "Q194195", "Islamic_organization": "Q110706912", "Comics_character": "Q1114461",
    "Sports_award": "Q15229207", "United_States_health_organization": "Q4287745", "Port": "Q44782",
    "Comic_strip": "Q838795", "LGBTQ_organization": "Q64606659", "Merchant_ship": "Q848944",
    "Shopping_mall": "Q11315", "Board_game": "Q131436", "Literary_society": "Q497893",
    "Building_and_structure_type": "Q811102", "Canada_retail_company": "Q4830453",
    "Information_technology_company": "Q18388277", "Plant_disease": "Q2662845", "Retail_company": "Q4830453",
    "Bus": "Q23039057", "Near-Earth_asteroid": "Q217526", "Science_award": "Q11448906", "Bird": None,
    "Music_award": "Q1364556", "United_Kingdom_retail_company": "Q4830453", "Visual_arts_award": "Q1792571",
    "Animated_character": "Q15711870", "Woodwind_instrument": "Q181247", "German_political_party": "Q2023214",
    "Locomotive": "Q19832486", "News_website": "Q17232649", "Steam_locomotive": "Q19832486",
    "String_instrument": "Q1798603", "Musical_instrument": "Q34379", "Horse": None,
    "History_book": WRITTEN_WORK, "Non-fiction_book": WRITTEN_WORK, "Popular_culture_book": WRITTEN_WORK,
    "Science_book": WRITTEN_WORK,
}
# class overrides (the stub's own class is wrong or too generic)
CLASS = {
    "Myanmar_Buddhist_temple": "Q5393308", "South_American_school": "Q3914", "European_flag": "Q14660",
    "Industrial_company": "Q4830453", "Iran_university": "Q3918", "Travel_book": WRITTEN_WORK,
    "United_States_hotel": "Q27686", "United_States_prison": "Q40357", "United_States_shopping_mall": "Q11315",
    "Indian_palace": "Q16560", "Italian_palace": "Q16560", "Indian_cricket_ground": "Q682943",
    "Romanian_sports_venue": "Q1076486", "Canadian_sports_venue": "Q1076486",
    "Northern_Ireland_sports_venue": "Q1076486", "Midwestern_United_States_museum": "Q33506",
    "Southern_United_States_museum": "Q33506", "Western_United_States_museum": "Q33506",
    "United_States_museum": "Q33506", "United_States_art_museum_and_gallery": "Q33506",
    "British_art_museum_and_gallery": "Q33506", "United_States_election": "Q40231",
    "Midwestern_United_States_election": "Q40231", "Southern_United_States_election": "Q40231",
    "Essay": WRITTEN_WORK, "Poem": LITERARY_WORK, "United_Kingdom_poem": LITERARY_WORK,
    "Picture_book": LITERARY_WORK,
}
# property overrides: kinds of things (the article is about a type) -> P279; individual works -> P31
PROP = {
    **{s: "P279" for s in (
        "Tool", "Textile", "Weapon", "Sword", "Food_ingredient", "Drink", "Dessert", "Asian_dessert",
        "European_dessert", "Medical_treatment", "Chemical_process", "Architectural_element", "Motorcycle",
        "Vehicle", "Guitar", "Alloy", "Room", "Ligament", "Musical_instrument", "Electronic_musical_instrument",
        "Woodwind_instrument", "String_instrument", "Unmanned_aerial_vehicle")},
    **{s: "P31" for s in ("Encyclopedia", "Bible_translation")},
}


def decide(stub, cls, suggest, several):
    stub = stub.removesuffix("_stubs")
    if stub in SKIP_STUB:
        return ""
    if several:
        pick = PICK.get(stub)
        if pick is None or (pick != cls and pick not in (WRITTEN_WORK, LITERARY_WORK)):
            return ""
        cls = pick
    if cls == "Q571" or stub.endswith("_book"):
        return f"P31 {WRITTEN_WORK}"
    if cls == "Q8261" or stub.endswith("_novel"):
        return f"P31 {LITERARY_WORK}"
    if cls in SKIP_CLASS or (cls == "Q5" and stub not in HUMAN_OK):
        return ""
    cls = CLASS.get(stub, cls)
    prop = PROP.get(stub) or ("P31" if cls in (WRITTEN_WORK, LITERARY_WORK) else suggest)
    return f"{prop} {cls}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default="en")
    args = ap.parse_args()
    path = os.path.join(OUT, f"review_{args.wiki}.tsv")
    with open(path, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    done = set()
    for r in rows:
        d = decide(r["stub"], r["class"], r["suggest"], r["several"] == "1")
        if r["stub"] in done:  # several-class stub: the decision goes on its first row only
            d = ""
        if d:
            done.add(r["stub"])
        r["decision"] = d
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    decided = {r["stub"]: r for r in rows if r["decision"]}
    print(f"{len(decided)} stubs decided ({sum(int(r['items']) for r in decided.values())} item-links), "
          f"{len({r['stub'] for r in rows}) - len(decided)} skipped -> {path}")


if __name__ == "__main__":
    main()
