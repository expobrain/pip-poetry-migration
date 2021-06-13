lint:
	poetry run mypy migrate.py

fmt:
	poetry run autoflake --recursive --in-place --remove-all-unused-imports .
	poetry run isort migrate.py
	poetry run black migrate.py
