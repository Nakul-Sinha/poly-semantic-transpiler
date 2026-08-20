# Poly — dev tasks. (Targets assume a POSIX shell; on Windows use WSL/Git Bash.)
.PHONY: install test selfcheck transpile web clean

install:
	python -m pip install -e ".[dev]"

test:
	pytest -q

selfcheck:
	@for f in examples/*.py; do echo "==== $$f ===="; python -m poly $$f --self-check; done

# Transpile one example to all targets: `make transpile EX=examples/gcd.py`
transpile:
	@mkdir -p build
	@python -m poly $(EX) -t js -o build/out.js  || true
	@python -m poly $(EX) -t py -o build/out.py  || true
	@python -m poly $(EX) -t c  -o build/out.c   || true

web:
	python web/server.py

clean:
	rm -rf build **/__pycache__ .pytest_cache *.egg-info poly/llm/cache/*.json
