PYTHON ?= python
PORT ?= 8765
HOST ?= 127.0.0.1

.PHONY: import serve test check-site

import:
	$(PYTHON) scripts/import_reports.py

serve:
	$(PYTHON) -m http.server $(PORT) --bind $(HOST) --directory site

test:
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v

check-site:
	$(PYTHON) scripts/check_site.py

