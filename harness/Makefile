PYTHON ?= python3
.PHONY: bootstrap quick full
bootstrap:
	cd .. && $(PYTHON) harness/run.py --group bootstrap
quick:
	cd .. && $(PYTHON) harness/run.py --group quick
full:
	cd .. && $(PYTHON) harness/run.py --group full
