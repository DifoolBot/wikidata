from GlotScript import sp


allowed_latin_scripts = ["Latn", "Zinh", "Zyyy", "Zzzz"]
allowed_hebrew_scripts = ["Hebr", "Zinh", "Zyyy", "Zzzz"]
allowed_cyrillic_scripts = ["Cyrl", "Zinh", "Zyyy", "Zzzz"]

def is_script(str: str, allowed_scripts: list) -> bool:
    """
    Checks if the input string contains only allowed scripts.

    Args:
        str (str): The input string.
        allowed_scripts (list): List of allowed scripts (e.g., ["Latn", "Zinh", "Zyyy", "Zzzz"]).

    Returns:
        bool: True if the string contains only allowed scripts, False otherwise.
    """
    res = sp(str)[2]
    if "details" in res:
        for script in res["details"]:
            if script not in allowed_scripts:
                return False
    return True

def is_hebrew_text(str: str) -> bool:
    return is_script(str, allowed_hebrew_scripts)

def is_latin_text(str: str) -> bool:
    return is_script(str, allowed_latin_scripts)

def is_cyrillic_text(str: str) -> bool:
    return is_script(str, allowed_cyrillic_scripts)

def check(name: str):
    print(f"is_latin({name}): {is_script(name, allowed_latin_scripts)}")
    print(f"is_hebrew({name}): {is_script(name, allowed_hebrew_scripts)}")
    print(f"is_cyrillic({name}): {is_script(name, allowed_cyrillic_scripts)}")


def main() -> None:
    check("Ḳampinsḳi, Aharon")
    check("קמפינסקי, אהרון")
    check("Nguyễn Đỗ Cung")
    check("Фельдман-Конрад, Наталия Исаевна")
    check("Захаров, Владимир Александрович")
    check("大石裕")



if __name__ == "__main__":
    main()
