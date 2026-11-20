# Submission figures (vector, A3 landscape)

`python3 page1_usecases.py && python3 page2_functional.py && python3 page3_technical.py` writes the SVGs to
/tmp/figs; then `rsvg-convert -f pdf pageN.svg -o pageN.pdf` and `pdfunite page1.pdf page2.pdf page3.pdf
ASE_Group_9_Figures.pdf`. Needs the Inter font. Edit the Python files, not the SVGs.
