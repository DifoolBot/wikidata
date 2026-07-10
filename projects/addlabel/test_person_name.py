import unittest

from addlabel.person_name import PersonName


class TestPersonName(unittest.TestCase):
    def test_explicit_parts_with_parentheses(self):
        # https://www.idref.fr/078837863
        # Explicitly passed name parts are not cleaned up, so parentheses in
        # the family name are rejected. (The old test suite appeared to cover
        # this with an expected value of "Igorʹ Vladimirovič Borisov", but the
        # test was shadowed by a second method with the same name and never
        # ran; this pins down the actual behavior.)
        with self.assertRaises(RuntimeError):
            PersonName(
                name="Borisov(Ilʹin), Igorʹ Vladimirovič",
                given_name="Igorʹ Vladimirovič",
                family_name="Borisov(Ilʹin)",
            )

    def test_short_given_name(self):
        name = PersonName(
            name="Family, A. B. (Anton Barend)",
        )
        self.assertEqual(name.names()[0], "Anton Barend Family")

    def test_simple(self):
        name = PersonName(name="Familyname, Givenname")
        self.assertEqual(name.names()[0], "Givenname Familyname")

    def test_name_with_year(self):
        name = PersonName(name="Zalizniak, Anna Andreevna (1959-....)")
        self.assertEqual(name.names()[0], "Anna Andreevna Zalizniak")

    def test_extra_comma(self):
        name = PersonName(name="Kadžaâ, Valerij Georgievič, (1942-....)")
        self.assertEqual(name.names()[0], "Valerij Georgievič Kadžaâ")

    def test_given_name_with_quote(self):
        name = PersonName(family_name="Oncieu de La Batie", given_name="Eugène d'")
        self.assertEqual(name.names()[0], "Eugène d'Oncieu de La Batie")


if __name__ == "__main__":
    unittest.main()
