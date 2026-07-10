"""Parsing of authority-file name strings ("Family, Given (extra)") into a
structured PersonName that can render itself in western or eastern name order.
"""

import re

NAME_ORDER_WESTERN = "family name last"
NAME_ORDER_EASTERN = "family name first"
NAME_ORDER_HUNGARIAN = "family name first, Hungarian"
NAME_ORDER_UNDETERMINED = ""


def has_numbers(input_string: str) -> bool:
    return any(char.isdigit() for char in input_string)


# Parenthetical qualifiers seen in authority-file name strings (mostly French,
# from IdRef/BnF: occupations, titles, religious orders). A name such as
# "Dupont, Jean (historien)" carries no name information between the
# parentheses, so these are dropped during parsing.
IGNORED_PARENTHETICAL_TERMS = [
    "abbé",
    "acteur",
    "actrice",
    "africaniste",
    "agrégée",
    "alchimiste",
    "anatomiste",
    "angliciste",
    "anthropologue",
    "arabisante",
    "archéologue",
    "archimandrite",
    "architecte",
    "archiviste",
    "assyriologue",
    "astronome",
    "astrophysicien",
    "augustin",
    "auteur de livres sur les arts martiaux",
    "auteur de manuel scolaire",
    "auteur pour la jeunesse",
    "auteur-éditeur",
    "avocat",
    "avocate",
    "badmaevič",
    "baron de",
    "baronne de",
    "bek",
    "bénédictin",
    "bhagavad",
    "bibliographe",
    "bibliothécaire",
    "biochimiste",
    "biographe",
    "biologiste",
    "biophysicien",
    "biostatisticien",
    "botaniste",
    "byzantiniste",
    "capitaine",
    "capucin",
    "caricaturiste",
    "carme déchaux",
    "carme",
    "chanoine",
    "chercheur en géologie",
    "chercheur en mécanique",
    "chercheur",
    "chercheuse en mathématiques",
    "chimiste",
    "chirurgien",
    "colonel",
    "compositeur",
    "conservateur",
    "conteur",
    "criminologue",
    "curé",
    "datadesigner",
    "démographe",
    "dentiste",
    "dermatologue",
    "designer graphiste",
    "designer",
    "dessinateur",
    "dessinatrice",
    "diététicienne",
    "diplomate",
    "docteur en philosophie",
    "docteur en théologie",
    "docteur ès sciences biologiques",
    "documentaliste",
    "dom",
    "dominicain",
    "dr. phil.",
    "dr.",
    "dr",
    "drag shos",
    "dramaturge",
    "économiste",
    "écrivain",
    "éditeur scientifique",
    "éditeur",
    "éditrice",
    "égyptologue",
    "électronicien",
    "encreur",
    "enseignant en sciences bibliques",
    "enseignant",  # IdRef 128470119
    "enseignante-chercheuse en biochimie et biologie moléculaire",
    "entomologiste",
    "ethnographe",
    "ethnologue",
    "ethnomusicologue",
    "évêque",
    "exégète",
    "franciscain",
    "généalogiste",
    "général",
    "géobotaniste",
    "géographe",
    "géologue",
    "germaniste",
    "graf von der",
    "graf von",
    "grammairien",
    "graveur",
    "gynécologue-obstétricien",
    "gynécologue",
    "helléniste",
    "historien",
    "historienne de l'environnement",
    "historienne",
    "hittitologue",
    "hor btsun",
    "illustrateur",
    "illustratrice",
    "indianiste",
    "infirmière",
    "informaticien",
    "ingénieur électronicien",
    "ingénieur",
    "inspecteur diocésain",
    "japonisant",
    "jésuite",
    "journaliste",
    "juriste",
    "latiniste",
    "lexicographe",
    "linguiste",
    "mariste",
    "mathématicien",
    "mathématicienne",
    "médecin-vétérinaire",
    "médecin",
    "médiéviste",
    "méthodiste",
    "microbiologiste",
    "militaire",
    "musicologue",
    "néerlandiciste",
    "neuro-chirurgien",
    "neurochirurgien",
    "numismate",
    "nutritionniste",
    "océanographe",
    "œnologue",
    "orientaliste",
    "ornithologue",
    "paléontologue",
    "papyrologue",
    "pasteur",
    "paysagiste",
    "pédiatre",
    "pédologue",
    "personnage biblique",
    "philologie ancienne",
    "philologie slave",
    "philologue, historiographe géorgienne",
    "philologue",
    "philosophe",
    "phlébologue",
    "photographe",
    "physicien",
    "piano",
    "plasticienne",
    "poète",
    "poétesse",
    "poétesse",
    "poétesse",
    "politiste",
    "politologue",
    "préhistorien",
    "prêtre",
    "producteur de films",
    "producteur, scénariste",
    "professeur agrégé de philosophie",
    "professeur de religion",
    "professeur des universités",
    "professeur",
    "professeure",
    "professor",
    "pseudonyme",
    "psychanalyste",
    "psychiatre",
    "psychologue",
    "psychothérapeute",
    "rabbin",
    "réalisateur",
    "réalisatrice",
    "rédacteur en chef",
    "religieuse",
    "religieux",
    "révérend",
    "rinpoche",
    "romancier",
    "romancière",
    "saint ; auteur prétendu",
    "saint",
    "scénariste",
    "sciences d'ingénieur",
    "sérigraphe",
    "sexologue",
    "sinologue",  # IdRef Q10800351
    "sismologue",
    "slavisant",
    "slaviste",
    "sociolinguiste",
    "sociologue",
    "soprano",
    "spécialiste de la santé et de l'environnement",
    "spécialiste de science militaire",
    "spécialiste en biologie du développement",
    "sulpicien",
    "swami",
    "terminologue",
    "théologien",
    "théologienne",
    "tibétologue",
    "traducteur",
    "traductrice",
    "universitaire australien",
    "urologue",
    "vétérinaire",
    "zoologue",
    "archéologue américain",
    "astrologue",
    "baron",
    "biogéochimiste",
    "chirurgien dentiste",
    "comte de",
    "conservatrice",
    "docteur",
    "dramaturge sanscrit",
    "détective",
    "essayiste",
    "généticien",
    "géshé",
    "informaticienne",
    "journaliste brésilienne",
    "lexicologue",
    "libraire",
    "moine bouddhiste",
    "poète, dramaturge",
    "professeur (histoire",
    "sainte",
    "sous-archiviste",
]


class PersonName:
    """A person name split into given/family parts.

    Built either from explicit given_name/family_name parts, or parsed from an
    authority-file string in "Family, Given (qualifier)" format. `names()`
    renders the full name honoring the configured name order.
    """

    def __init__(
        self,
        name: str = "",
        given_name: str = "",
        family_name: str = "",
    ):

        if family_name or given_name:
            self.short_given_name = ""
            self.family_name = family_name or ""
            self.given_name = given_name or ""
        elif name:
            self.short_given_name, self.given_name, self.family_name = (
                self.parse_authority_name(name)
            )
        else:
            self.short_given_name = ""
            self.given_name = ""
            self.family_name = ""

        self.name_order = NAME_ORDER_UNDETERMINED

        if self.remove_suffix(", Mrs."):
            self.prefix = "Mrs."
        else:
            self.prefix = ""

        self.check_invalid_chars(self.family_name)
        self.check_invalid_chars(self.given_name)

    def check_invalid_chars(self, name: str):
        invalid_chars = set('[]<>&$#~=$!?%^*_+}\\{|/@,()0123456789"')
        if any(char in invalid_chars for char in name):
            raise RuntimeError(f"Invalid char in name: {name}")
        # Q18646095
        if "  " in name:
            raise RuntimeError(f"Double space in name: {name}")
        if "--" in name:
            raise RuntimeError(f"Double - in name: {name}")
        if "' " in name:
            raise RuntimeError(f"Quote + space in name: {name}")
        if name.startswith(" "):
            raise RuntimeError(f"Invalid start char: {name}")
        if name.endswith(" "):
            raise RuntimeError(f"Invalid end char: {name}")

    def parse_authority_name(self, name: str):
        """Split "Family, Given (qualifier)" into (short_given_name,
        given_name, family_name).

        A parenthetical part is either dropped (years, known occupation
        qualifiers) or treated as the long form of an abbreviated given name:
        "Family, A. B. (Anton Barend)" yields given_name "Anton Barend" with
        short_given_name "A. B.".
        """
        short_given_name = ""

        # , ? and () are allowed
        # example: Wedgwood, John Taylor (1783?-1856)
        invalid_chars = set("[]<>&$#~=$!%^*_\\+}{|@")
        if any(char in invalid_chars for char in name):
            raise RuntimeError(f"Invalid chars in name: {name}")
        # extract the part between parentheses
        match = re.search(r"\(([^)]+)\)", name)
        if match:
            # parentheses text can be birth/death year, alternative family name, long given name
            parentheses_text = match.group(1)
            name = name.replace("(" + parentheses_text + ")", "@")
            if has_numbers(parentheses_text):
                # ignore (year-year)
                parentheses_text = ""
            elif parentheses_text in IGNORED_PARENTHETICAL_TERMS:
                parentheses_text = ""
            elif parentheses_text.islower():
                raise RuntimeError(
                    f"Invalid parentheses text in name: <{parentheses_text}>"
                )
        else:
            parentheses_text = ""

        # format = family name, given name
        if "," in name:
            # 'Ōishi, Yutaka, 1956-'
            arr = name.split(",", 3)
            if len(arr) == 3:
                # idref: Kadžaâ, Valerij Georgievič, (1942-....)
                print(f"Name with 2 or more comma's: {name} - removed: {arr[2]}")
            family_name = arr[0].strip()
            given_name = arr[1].strip()

            if "@" in family_name:
                family_name = family_name.strip(" @")

            if "@" in given_name:
                given_name = given_name.strip(" @")
                if parentheses_text:
                    short_given_name = given_name
                    given_name = parentheses_text
        else:
            family_name = ""
            if "@" in name:
                name = name.strip(" @")
            given_name = name
        return (short_given_name, given_name, family_name)

    def names(self):
        if self.family_name and self.given_name:
            if self.name_order == NAME_ORDER_EASTERN:
                return self.family_name_first()
            else:
                return self.family_name_last()
        elif self.family_name:
            return [self.family_name]
        elif self.given_name:
            return [self.given_name]
        else:
            return []

    def family_name_last(self):
        res = [self.full_name(self.prefix, self.given_name, self.family_name)]
        if self.short_given_name:
            res.append(
                self.full_name(self.prefix, self.short_given_name, self.family_name)
            )
        return res

    def family_name_first(self):
        res = [self.full_name(self.prefix, self.family_name, self.given_name)]
        if self.short_given_name:
            res.append(
                self.full_name(self.prefix, self.family_name, self.short_given_name)
            )
        return res

    def full_name(self, prefix, name1: str, name2: str) -> str:
        if not name1:
            fn = name2
        elif not name2:
            fn = name1
        elif name1.endswith("'"):
            if name1.endswith(" d'"):
                fn = f"{name1}{name2}"
            else:
                raise RuntimeError(f"name1 ends with quote: {name1} {name2}")
        elif name1.endswith("-"):
            fn = f"{name1}{name2}"
        else:
            fn = f"{name1} {name2}"
        if prefix and fn:
            return f"{prefix} {fn}"
        else:
            return fn

    def remove_suffix(self, suffix: str) -> bool:
        suffix_len = len(suffix)
        changed = False
        if self.short_given_name.endswith(suffix):
            self.short_given_name = self.short_given_name[:-suffix_len]
            changed = True
        if self.family_name.endswith(suffix):
            self.family_name = self.family_name[:-suffix_len]
            changed = True
        if self.given_name.endswith(suffix):
            self.given_name = self.given_name[:-suffix_len]
            changed = True

        return changed
