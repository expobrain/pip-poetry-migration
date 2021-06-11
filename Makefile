lint:
	mypy migrate.py

fmt:
	isort migrate.py
	black migrate.py
