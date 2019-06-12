.PHONY: all clean

SED:=sed

all:
	(for i in `git ls-files | grep '^[^/]*ipynb$$'`; do make `basename $$i .ipynb`.py; done)

%.py: %.ipynb
	jupyter nbconvert --to script "$*.ipynb" --stdout > "$@"
	$(SED) -i "/get_ipython/d" "$@" 
	python "$@"

clean:
	(for i in `git ls-files | grep '^[^/]*ipynb$$'`; do rm -fv "`basename $$i .ipynb`.py"; done)
