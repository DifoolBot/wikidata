import shared_lib.constants as wd
from enum import Enum


class Field(Enum):
    PREFIX = "prefix"
    SUFFIX = "suffix"
    DATE_OF_BIRTH = "dob"
    DATE_OF_DEATH = "dod"
    DATE_OF_BAPTISM = "baptism"
    DATE_OF_BURIAL = "burial"
    DATE_OF_PROBATE = "probate"
    PLACE_OF_BIRTH = "place_of_birth"
    PLACE_OF_DEATH = "place_of_death"
    PLACE_OF_RESIDENCE = "place_of_residence"
    GENDER = "gender"
    DISPLAY_NAME = "display_name"
    ALIASES = "aliases"
    DEPRECATED_NAMES = "deprecated_names"
    DEPRECATED_DESC = 'deprecated_desc'

    FIND_A_GRAVE_ID = "findagrave_id"


class Source(Enum):
    WIKITREE = "wikitree"
    GENEALOGICS = "genealogics"


IGNORED_IDENTIFIERS = {"findmygrave"}

ALL_FIELDS = set(item for item in Field)
DATE_FIELDS = {
    Field.DATE_OF_BIRTH,
    Field.DATE_OF_DEATH,
    Field.DATE_OF_BAPTISM,
    Field.DATE_OF_BURIAL,
    Field.DATE_OF_PROBATE,
}
PLACE_FIELDS = {
    Field.PLACE_OF_BIRTH,
    Field.PLACE_OF_DEATH,
    Field.PLACE_OF_RESIDENCE,
}
NAME_FIELDS = {
    Field.DISPLAY_NAME,
    Field.ALIASES,
    Field.DEPRECATED_NAMES,
    Field.DEPRECATED_DESC,
}
IDENTIFIER_FIELDS = {
    Field.FIND_A_GRAVE_ID,
}
OTHER_FIELDS = ALL_FIELDS - DATE_FIELDS - PLACE_FIELDS - NAME_FIELDS - IDENTIFIER_FIELDS
ALL_EXCEPT_NAME_FIELDS = ALL_FIELDS - NAME_FIELDS
