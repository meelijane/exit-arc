.PHONY: test pyz clean

test:
	python3 -m unittest discover -s tests

pyz:
	python3 scripts/build_pyz.py

clean:
	rm -rf dist build *.egg-info
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
