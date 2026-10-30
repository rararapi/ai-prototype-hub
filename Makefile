PYTHON ?= python3
.PHONY: doctor doctor-kind up-mock up-real check integration e2e security verify logs down reset-local
doctor:
	$(PYTHON) harness/doctor.py --mode compose
doctor-kind:
	$(PYTHON) harness/doctor.py --mode kind
up-mock:
	bash scripts/local/up-mock.sh
up-real:
	bash scripts/local/up-real.sh
check:
	$(PYTHON) harness/run.py --group quick
integration:
	$(PYTHON) harness/run.py --group integration
e2e:
	$(PYTHON) harness/run.py --group e2e
security:
	$(PYTHON) harness/run.py --group security
verify:
	$(PYTHON) harness/run.py --group full
logs:
	bash scripts/local/logs.sh
down:
	bash scripts/local/down.sh
reset-local:
	bash scripts/local/reset-local.sh
