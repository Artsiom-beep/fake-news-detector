# Verity Lens report

Draft university report source:

```powershell
.\scripts\build_report.ps1 -BootstrapTectonic
```

From this repository root, the command writes:

```text
docs\report\verity_lens_report.pdf
```

If a TeX distribution is already installed, compiling inside this directory also works:

```powershell
pdflatex verity_lens_report.tex
pdflatex verity_lens_report.tex
```

The helper script can bootstrap the local Tectonic binary into `.venv` via the `tecto` wheel when `pdflatex` is unavailable.
Fill in the author, group and instructor fields on the title page before final submission.
