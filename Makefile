# repo-forge:tareas
.PHONY: doctor test check all

doctor:
	python scripts/doctor.py

test:
	python -m unittest discover -s tests -v

check: doctor test

all: check
