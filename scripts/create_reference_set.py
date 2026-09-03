"""Cree un jeu de reference reproductible et equilibre depuis le holdout M1 dans data/reference_set.csv."""

import csv
import random
from collections import Counter
from pathlib import Path


RANDOM_SEED = 42
SAMPLES_PER_CLASS = 250
TARGET_COLUMN = "loan_status"
EXPECTED_CLASSES = ("Fully Paid", "Charged Off")

PROJECT_DIRECTORY = Path(__file__).resolve().parents[1]
DATA_DIRECTORY = PROJECT_DIRECTORY / "data"
SOURCE_PATH = DATA_DIRECTORY / "lending_club_holdout.csv"
TARGET_PATH = DATA_DIRECTORY / "reference_set.csv"
TEMPLATE_PATH = DATA_DIRECTORY / "reference_set_TEMPLATE.csv"


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
	"""Lit l'en-tete et les lignes d'un CSV avec un message d'erreur explicite."""
	if not path.exists():
		raise FileNotFoundError(f"Fichier introuvable : {path}")

	with path.open(encoding="utf-8", newline="") as file:
		reader = csv.DictReader(file)
		if reader.fieldnames is None:
			raise ValueError(f"Le fichier est vide ou sans en-tete : {path}")
		return reader.fieldnames, list(reader)


def main() -> None:
	fieldnames, rows = read_csv(SOURCE_PATH)
	template_fieldnames, _ = read_csv(TEMPLATE_PATH)

	# Le jeu produit doit avoir exactement les memes colonnes et le meme ordre
	# que le template attendu par l'evaluation continue.
	if fieldnames != template_fieldnames:
		raise ValueError(
			"Les colonnes du holdout ne correspondent pas au template de reference."
		)
	if TARGET_COLUMN not in fieldnames:
		raise ValueError(f"Colonne cible absente : {TARGET_COLUMN}")

	# Separer les observations par classe permet de tirer le meme nombre de
	# remboursements et de defauts, sans dupliquer des lignes.
	rows_by_class = {
		class_name: [row for row in rows if row[TARGET_COLUMN] == class_name]
		for class_name in EXPECTED_CLASSES
	}
	insufficient_classes = [
		class_name
		for class_name, class_rows in rows_by_class.items()
		if len(class_rows) < SAMPLES_PER_CLASS
	]
	if insufficient_classes:
		counts = Counter(row[TARGET_COLUMN] for row in rows)
		raise ValueError(
			f"Pas assez de lignes pour {', '.join(insufficient_classes)}. "
			f"Effectifs observes : {dict(counts)}"
		)

	# Une graine fixe donne toujours le meme echantillon : les evaluations des
	# futures versions du modele restent donc comparables.
	random_generator = random.Random(RANDOM_SEED)
	reference_rows = [
		row
		for class_name in EXPECTED_CLASSES
		for row in random_generator.sample(rows_by_class[class_name], SAMPLES_PER_CLASS)
	]
	# Melanger evite que les deux classes soient groupees dans le fichier final.
	random_generator.shuffle(reference_rows)

	# DictWriter preserve l'ordre des colonnes du fichier holdout valide plus haut.
	with TARGET_PATH.open("w", encoding="utf-8", newline="") as file:
		writer = csv.DictWriter(file, fieldnames=fieldnames)
		writer.writeheader()
		writer.writerows(reference_rows)

	counts = Counter(row[TARGET_COLUMN] for row in reference_rows)
	print(f"Jeu de reference cree : {TARGET_PATH}")
	print(f"Lignes : {len(reference_rows)}")
	print(f"Distribution : {dict(counts)}")
	print(f"Graine aleatoire : {RANDOM_SEED}")


if __name__ == "__main__":
	main()
