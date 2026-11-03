# XML stackup files for gds2openEMS workflow

Stackup files in this repository are for gds2openEMS, do not use them with gds2palace. There are some subtle differences (like MIM dielectric modelling) due to solver method.

---

The latest stackup files can be found in the [latest](latest) folder. They make use of new XML file format features such as variables, see the [XML stackup format description](../doc/XML_stackup_format.md). They are also installed with the gds2openEMS package: `utilities.get_stackup_path('SG13G2_FDTD_300um.xml')` returns the full path of one.

The [legacy](legacy) folder contains previous versions for compatibility only, used by the examples in the [workflow](../workflow) folder.

**For new models, it is recommended to use the XML stackup files from the [latest](latest) folder.**
