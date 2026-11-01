# Card 959: cheap pre-Pass checks. Prefer tools/precheck.sh <head>.
.PHONY: precheck
precheck:
	./tools/precheck.sh $(HEAD)
