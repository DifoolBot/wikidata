
from pywikibot.data import sparql
from pathlib import Path

CONST_DIR = Path("projects\\shared_lib\\")
CONST_FILENAME = "constants.py"
CONST_PATH = CONST_DIR / CONST_FILENAME

def get_info_for_qid(qid: str):
    query = f"""
            SELECT ?itemLabel ?itemDescription ?instanceLabel ?instanceDescription WHERE {{
            VALUES ?item {{ wd:{qid} }}

            ?item wdt:P31 ?instance .

            SERVICE wikibase:label {{
                bd:serviceParam wikibase:language "en".
                ?item rdfs:label ?itemLabel .
                ?item schema:description ?itemDescription .
                ?instance rdfs:label ?instanceLabel .
                ?instance schema:description ?instanceDescription .
            }}
            }}
            LIMIT 1
        """

    query_object = sparql.SparqlQuery()
    payload = query_object.query(query=query)
    if payload:
        for row in payload["results"]["bindings"]:
            item_label = row["itemLabel"]["value"]
            item_description = row["itemDescription"]["value"]
            instance_label = row["instanceLabel"]["value"]
            instance_description = row["instanceDescription"]["value"]
            return (item_label, item_description, instance_label, instance_description)
    return None
def get_info_for_property(pid: str):
    query = f"""
            SELECT ?propertyLabel ?propertyDescription ?instanceLabel ?instanceDescription WHERE {{
            VALUES ?property {{ wd:{pid} }}

            ?property wdt:P31 ?instance .

            SERVICE wikibase:label {{
                bd:serviceParam wikibase:language "en".
                ?property rdfs:label ?propertyLabel .
                ?property schema:description ?propertyDescription .
                ?instance rdfs:label ?instanceLabel .
                ?instance schema:description ?instanceDescription .
            }}
            }}
            LIMIT 1
        """

    query_object = sparql.SparqlQuery()
    payload = query_object.query(query=query)
    if payload:
        for row in payload["results"]["bindings"]:
            property_label = row["propertyLabel"]["value"]
            property_description = row["propertyDescription"]["value"]
            instance_label = row["instanceLabel"]["value"]
            instance_description = row["instanceDescription"]["value"]
            return (property_label, property_description, instance_label, instance_description)
    return None


def get_constant_name_for_id(entity_id: str, description: str) -> str:
    """
    Given a string like Q172771 or P551, return QID_ROYAL_NAVY or PID_ROYAL_NAVY.
    """
    # Convert label to constant style: uppercase, spaces and hyphens to underscores, remove non-alphanum
    label = description.upper().replace(" ", "_").replace("-", "_")
    label = "".join(c for c in label if c.isalnum() or c == "_")
    if entity_id.startswith("Q"):
        return f"QID_{label}"
    elif entity_id.startswith("P"):
        return f"PID_{label}"
    else:
        raise ValueError("ID must start with Q or P")

def contains_file_consts(entity_id: str) -> bool:
    """
    Check if the given entity_id already exists in the specified file.
    """
    var1 = f'"{entity_id}"'
    var2 = f"'{entity_id}'"
    section = None
    with open(CONST_PATH, "r", encoding="utf-8-sig") as f:
        for line in f:
            if line.startswith("#"):
                section = line.strip("#").strip()
                continue
            if var1 in line or var2 in line:
                return section, line
    return None

def remove_line(line_to_remove: str):
    """
    Remove a specific line from a file.
    """
    with open(CONST_PATH, "r", encoding="utf-8-sig") as f:
        lines = f.readlines()   
    with open(CONST_PATH, "w", encoding="utf-8") as f:
        for line in lines:
            if line == line_to_remove:
                print(f"Removed line: {line.strip()}")
            else:
                f.write(line)

def get_info_for_entity(entity_id: str):
    """
    Given a Wikidata Q or P id, return a tuple of (section, new_line) for adding to the constants file.
    Section is the instance type (e.g. "Human", "Country", "Award").
    New line is the constant definition line (e.g. QID_ALBERT_EINSTEIN = 'Q937').
    """
    if entity_id.startswith("Q"):
        data = get_info_for_qid(entity_id)
    elif entity_id.startswith("P"):
        data = get_info_for_property(entity_id)
    else:
        raise ValueError("ID must start with Q or P")
    
    if not data:
        return None

    if entity_id.startswith("Q"):
        item_label, item_description, instance_label, instance_description = data
        section = instance_label
        const_name = get_constant_name_for_id(entity_id, item_label)
        new_line = f'{const_name} = "{entity_id}"\n'
        return section, new_line
    elif entity_id.startswith("P"):
        property_label, property_description, instance_label, instance_description = data
        section = instance_label        
        const_name = get_constant_name_for_id(entity_id, property_label)
        new_line = f'{const_name} = "{entity_id}"\n'
        return section, new_line
    return None    
def add_constant_to_file(section: str, new_line: str):
    """
    Add a new constant definition to the specified file.
    """
    with open(CONST_PATH, "r", encoding="utf-8-sig") as f:
        lines = f.readlines()
    new_lines = []
    section_found = False
    added = False      
    for line in lines:
        if not added:
            if section_found and line.startswith("#"):
                new_lines.append(new_line)
                added = True
            elif line == f"# {section}\n":
                section_found = True
        new_lines.append(line)            
            
    if not section_found:
        new_lines.append(f"# {section}\n")
    if not added:
        new_lines.append(f"{new_line}")
        added = True

    with open(CONST_PATH, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

    print(f"Added line: {new_line.strip()} in section: {section}")

def ask():
    entity_id = input("Enter a string: ")
    work(entity_id)

def work(entity_id: str):
    line_info = contains_file_consts(entity_id)
    if line_info:
        section, line = line_info
        if section:
            print(f"{entity_id} already exists in {CONST_FILENAME}")
            return
        data = get_info_for_entity(entity_id)
        if not data:
            print(f"Could not find info for {entity_id}")
            return
        section, new_line = data
        remove_line(line)
        add_constant_to_file(section, new_line)
    else:        
        data = get_info_for_entity(entity_id)
        if not data:
            print(f"Could not find info for {entity_id}")
            return
        section, new_line = data
        add_constant_to_file(section, new_line)

def test_prop():
    qid = "Q6518699"
    print(get_info_for_qid(qid))
    
if __name__ == "__main__":
    ask()