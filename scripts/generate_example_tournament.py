"""Generate a realistic, synthetic, fully anonymized wrestling tournament spreadsheet."""

import random
from pathlib import Path

from bracketman.io.xlsx import write_xlsx_sheets


FIRST_NAMES_BOYS = [
    "Liam", "Noah", "Oliver", "James", "Elijah", "William", "Henry", "Lucas", "Benjamin", "Theodore",
    "Jack", "Levi", "Alexander", "Jackson", "Mateo", "Daniel", "Michael", "Mason", "Sebastian", "Ethan",
    "Logan", "Owen", "Samuel", "Jacob", "Asher", "Aiden", "John", "Joseph", "Wyatt", "David",
    "Leo", "Luke", "Julian", "Hudson", "Grayson", "Matthew", "Ezra", "Gabriel", "Carter", "Isaac",
    "Jayden", "Luca", "Anthony", "Dylan", "Lincoln", "Thomas", "Maverick", "Elias", "Josiah", "Charles",
    "Caleb", "Christopher", "Ezekiel", "Miles", "Jaxon", "Isaiah", "Andrew", "Joshua", "Nathan", "Nolan",
    "Adrian", "Cameron", "Santiago", "Eli", "Aaron", "Ryan", "Angel", "Cooper", "Waylon", "Easton",
    "Kai", "Christian", "Landon", "Colton", "Roman", "Axel", "Brooks", "Jonathan", "Robert", "Jameson",
    "Ian", "Everett", "Greyson", "Wesley", "Jeremiah", "Hunter", "Leonardo", "Jordan", "Bennett", "Silas",
    "Nicholas", "Beau", "Weston", "Austin", "Connor", "Carson", "Dominic", "Xavier", "Jaxson", "Jace",
]

FIRST_NAMES_GIRLS = [
    "Olivia", "Emma", "Charlotte", "Amelia", "Sophia", "Isabella", "Ava", "Mia", "Evelyn", "Harper",
    "Luna", "Camila", "Gianna", "Elizabeth", "Eleanor", "Ella", "Abigail", "Sofia", "Avery", "Scarlett",
    "Emily", "Aria", "Penelope", "Chloe", "Layla", "Mila", "Nora", "Hazel", "Madison", "Ellie",
    "Lily", "Nova", "Isla", "Grace", "Violet", "Aurora", "Riley", "Zoey", "Willow", "Emilia",
    "Stella", "Zoe", "Victoria", "Hannah", "Addison", "Leah", "Lucy", "Eliana", "Ivy", "Everly",
    "Lillian", "Paisley", "Elena", "Naomi", "Maya", "Natalie", "Kinsley", "Delilah", "Claire", "Audrey",
    "Ruby", "Brooklyn", "Alice", "Aubrey", "Autumn", "Leilani", "Savannah", "Valentina", "Kennedy", "Madelyn",
    "Josephine", "Bella", "Skylar", "Genesis", "Sophie", "Hailey", "Sadie", "Natalia", "Quinn", "Caroline",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
    "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
    "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson",
    "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores",
    "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell", "Carter", "Roberts",
    "Gomez", "Phillips", "Evans", "Turner", "Diaz", "Parker", "Cruz", "Edwards", "Collins", "Reyes",
    "Stewart", "Morris", "Morales", "Murphy", "Cook", "Rogers", "Gutierrez", "Ortiz", "Morgan", "Cooper",
    "Peterson", "Bailey", "Reed", "Kelly", "Howard", "Ramos", "Kim", "Cox", "Ward", "Richardson",
    "Watson", "Brooks", "Chavez", "Wood", "James", "Bennett", "Gray", "Mendoza", "Ruiz", "Hughes",
    "Price", "Alvarez", "Castillo", "Sanders", "Patel", "Myers", "Long", "Ross", "Foster", "Jimenez",
]

TEAMS = [
    ("Arapahoe", "AR", 65),
    ("Ascent", "ASC", 15),
    ("Bailey", "BAI", 40),
    ("Columbine", "COL", 45),
    ("Discovery Canyon", "DCC", 20),
    ("Englewood", "ENG", 50),
    ("Golden Eagles", "GE", 38),
    ("Heritage", "HER", 17),
]

# (Age group, nominal min weight, nominal max weight, approx actual age)
AGE_DISTRIBUTIONS = [
    ("6U", 32.0, 62.0, 5, 6),
    ("8U", 42.0, 95.0, 7, 8),
    ("10U", 55.0, 135.0, 9, 10),
    ("12U", 65.0, 160.0, 11, 12),
    ("14U", 80.0, 175.0, 13, 14),
]


def generate_synthetic_spreadsheet(output_path: Path) -> int:
    """Generate multi-tab synthetic tournament spreadsheet."""
    random.seed(42)  # Deterministic generation for reproducible test cases
    sheets: list[tuple[str, list[list[object]]]] = []
    total_wrestlers = 0

    used_names: set[str] = set()

    for tab_name, team_code, target_count in TEAMS:
        rows: list[list[object]] = [
            ["Age groups: 6U, 8U, 10U, 12U & 14U"],
            ["Ability: Novice = 1st & 2nd year wrestlers, Experienced = 3+ years"],
            [],
            ["Bracket: Place an X indicating division (Boys/COED or Girls only, or both)"],
            [
                "Weight",
                "Wrestlers Name",
                "Age Group",
                "School",
                "Age",
                "Ability (Novice or experienced)",
                "Boys / COED Bracket",
                "Girls only Bracket",
            ],
        ]

        for _ in range(target_count):
            # 85% boys, 15% girls
            is_girl = random.random() < 0.16
            fn_list = FIRST_NAMES_GIRLS if is_girl else FIRST_NAMES_BOYS
            fn = random.choice(fn_list)
            ln = random.choice(LAST_NAMES)
            full_name = f"{fn} {ln}"
            while full_name in used_names:
                fn = random.choice(fn_list)
                ln = random.choice(LAST_NAMES)
                full_name = f"{fn} {ln}"
            used_names.add(full_name)

            # Age group weighted distribution: 6U (25%), 8U (25%), 10U (25%), 12U (15%), 14U (10%)
            age_tuple = random.choices(
                AGE_DISTRIBUTIONS,
                weights=[0.25, 0.25, 0.25, 0.15, 0.10],
                k=1,
            )[0]
            age_group, min_w, max_w, min_a, max_a = age_tuple

            # Weight generation with realistic clusters
            # Normal distribution centered around lower-middle of range
            mean_w = min_w + (max_w - min_w) * 0.35
            std_w = (max_w - min_w) * 0.2
            weight = round(max(min_w, min(max_w + 10.0, random.gauss(mean_w, std_w))), 1)

            actual_age = random.randint(min_a, max_a)

            # Ability: 70% Novice, 30% Experienced
            ability = "Novice" if random.random() < 0.70 else "Experienced"

            # Division placement
            if is_girl:
                # 30% dual entry (both Coed and Girls), 70% Girls only
                if random.random() < 0.30:
                    coed_x = "X"
                    girls_x = "X"
                else:
                    coed_x = ""
                    girls_x = "X"
            else:
                coed_x = "X"
                girls_x = ""

            rows.append([
                weight,
                full_name,
                age_group,
                team_code,
                actual_age,
                ability,
                coed_x,
                girls_x,
            ])
            total_wrestlers += 1

        sheets.append((tab_name, rows))

    write_xlsx_sheets(output_path, sheets)
    return total_wrestlers


if __name__ == "__main__":
    out = Path("data/example_tournament.xlsx")
    out.parent.mkdir(parents=True, exist_ok=True)
    count = generate_synthetic_spreadsheet(out)
    print(f"Generated {count} synthetic wrestlers across {len(TEAMS)} tabs at {out}")
