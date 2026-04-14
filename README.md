# GCPM: GEOS-Chem PM2.5 Calculator

GCPM calculates fine particulate matter (PM2.5) mass concentrations from GEOS-Chem chemical transport model output. It converts species volume mixing ratios (VMR) to mass concentrations in micrograms per cubic meter (ug/m3) and aggregates them into PM2.5 components.

## PM2.5 Calculation Method

### Volume Mixing Ratio to Mass Concentration

GEOS-Chem reports aerosol species as dry volume mixing ratios (mol/mol). GCPM converts these to mass concentrations using the ideal gas law at **standard conditions**:

```
C [ug/m3] = VMR * P / (R * T) * MW * 1e6
```

where:
- `VMR` = volume mixing ratio (mol/mol) from GEOS-Chem `SpeciesConcVV_*` fields
- `P` = 101325 Pa (standard atmospheric pressure)
- `R` = 8.314 J/(mol*K) (universal gas constant)
- `T` = 298 K (standard temperature)
- `MW` = molecular weight of the species (g/mol)
- `1e6` = conversion from g to ug

**Note:** Standard temperature and pressure are used intentionally (rather than local meteorological conditions) to provide a consistent reference basis for mass concentration.

### Hygroscopic Growth Factors

Aerosol particles absorb water under ambient humidity conditions, increasing their mass. GCPM can report either **wet** (default) or **dry** mass concentrations. In wet mode, species-specific growth factors are applied:

| Group | Default Factor | Species |
|-------|---------------|---------|
| SIA   | 1.042         | NIT, SO4, NH4, (HMS) |
| ORG   | 1.011         | All organic aerosol species |
| SS    | 1.17          | SALA |

> The hygroscopic growth factors here represent results from a recent laboratory study (Oxford et al., in prep), which are lower than previous values in Latimer et al., 2019.

Black carbon and mineral dust are not hygroscopic and receive no growth factor.

Growth factors can be overridden at runtime for sensitivity analysis via the `growth_factors` parameter.

### OM/OC Ratios

Some organic aerosol species are reported as carbon mass in GEOS-Chem. To obtain total organic matter mass, an organic-matter-to-organic-carbon (OM/OC) ratio is applied:

| OA Type | Default OM/OC | Rationale |
|---------|--------------|-----------|
| Non-volatile POA (POA1/2 or OCPO) | 1.4 | Fresh, less oxidized primary organic aerosol |
| Semi-volatile / oxidized POA (OPOA1/2 or OCPI) | 2.1 | Aged, more oxidized organic aerosol |
| SOA | 1.8 | This is a very uncertain estimation as calculated by median value of the two typical type of POA

> Another option is to use NO2-dependent seasonally varying spatially-resolved OM/OC ratio in Philip et al., 2014

OM/OC ratios can be overridden at runtime via the `omoc_ratios` parameter (spatially varying OM/OC not supported).

## Species Categories

PM2.5 is the sum of the following component categories:

### Secondary Inorganic Aerosol (SIA)
- **NIT** — Nitrate (MW 62.01)
- **SO4** — Sulfate (MW 96.06)
- **NH4** — Ammonium (MW 18.05)
- **HMS** — Hydroxymethanesulfonate (MW 111.1) — *optional, see below*

### Organic Aerosol (OA)

OA = POA (Primary Organic Aerosol) + SOA (Secondary Organic Aerosol). The specific species depend on the model scheme configuration (see Scheme Variants below).

### Black Carbon (BC)
- **BCPI** — Hydrophilic black carbon (MW 12.01)
- **BCPO** — Hydrophobic black carbon (MW 12.01)

### Sea Salt (SS)
- **SALA** — Accumulation-mode sea salt (MW 31.4)

### Mineral Dust
Species depend on the dust scheme. Only fine-mode bins are included in PM2.5 (see PM2.5 Size Cuts below).

## Scheme Variants

GEOS-Chem supports different configurations for organic aerosol and dust. GCPM can auto-detect the active scheme from dataset variables or accept explicit user specification.

### SOA Schemes

| Scheme | Species | Description |
|--------|---------|-------------|
| **complex** | ASOA1, ASOA2, ASOA3, ASOAN, TSOA0, TSOA1, TSOA2, TSOA3, SOAIE, SOAGX, LVOCOA, (INDIOL) | Volatility basis set with explicit speciation of aromatic SOA (ASOA), terpene SOA (TSOA), isoprene epoxydiols (SOAIE), glyoxal (SOAGX), and low-volatility OC (LVOCOA), **INDIOL is optional, see detailed explanation below** |
| **simple** | SOAS | Lumped SOA representation |

Auto-detection: if `SpeciesConcVV_ASOA1` is present, uses `complex`; if `SpeciesConcVV_SOAS` is present, uses `simple`.

### POA Schemes

| Scheme | Species | OM/OC | Description |
|--------|---------|-------|-------------|
| **SVPOA** (Semi-Volatile) | POA1, POA2 (OM/OC=1.4); OPOA1, OPOA2 (OM/OC=2.1) | See table | POA partitions between gas and particle phase |
| **NVPOA** (Non-Volatile) | OCPO (OM/OC=1.4); OCPI (OM/OC=2.1) | See table | POA is non-volatile, tracked as hydrophobic/hydrophilic |

Auto-detection: if `SpeciesConcVV_POA1` is present, uses `SVPOA`; if `SpeciesConcVV_OCPI` is present, uses `NVPOA`.

### Dust Schemes

| Scheme | PM2.5 Bins | Excluded (coarse) | Description |
|--------|-----------|-------------------|-------------|
| **DEAD** | DST1, DST2 (x0.3) | DST3, DST4 | 4-bin DEAD dust scheme |
| **L23** | DSTbin1, DSTbin2, DSTbin3, DSTbin4 (x0.546) | DSTbin5, DSTbin6, DSTbin7 | 7-bin Kok et al. (L23) dust scheme |

Auto-detection: if `SpeciesConcVV_DSTbin1` is present, uses `L23`; otherwise uses `DEAD`.

## PM2.5 Size Cuts for Dust

Not all dust size bins fall within the PM2.5 diameter cutoff (2.5 um aerodynamic diameter):

**DEAD scheme (DST1-4):**
- DST1: Fully within PM2.5 (fraction = 1.0)
- DST2: Straddles the 2.5 um cutoff; **30%** of mass is PM2.5
- DST3, DST4: Entirely coarse, excluded from PM2.5

**L23 scheme (DSTbin1-7):**
- DSTbin1-3: Fully within PM2.5 (fraction = 1.0)
- DSTbin4: Straddles the 2.5 um cutoff; **54.6%** of mass is PM2.5
- DSTbin5-7: Entirely coarse, excluded from PM2.5

## Optional Species

Two species have debatable classification and are **excluded by default**. Their inclusion can be toggled via configuration flags:

### HMS (Hydroxymethanesulfonate)
- **Flag:** `include_hms` (default: `False`)
- **Category if included:** SIA
- HMS is formed from the aqueous-phase reaction of formaldehyde with sulfite/bisulfite. Whether it should be classified as PM2.5 depends on the analysis context — it is a real aerosol-phase species but is not always reported in observational PM2.5 measurements.

### INDIOL (Hydrolysis product of organonitrate)
- **Flag:** `include_indiol` (default: `False`)
- **Category if included:** SOA (complex scheme only)
- INDIOL represents the hydrolysis product of aerosol-form organonitrate, e.g., AONITA, IONITA and MONITA. It can easily takes >50% of total SOA and it should be seen as an overestimation.
> Kelvin Bates (Email, 2026): There is still the issue of whether to include INDIOL at all as a species in PM2.5 or not. I think we do this species wrong in GEOS-Chem, because in reality, while it's true that most of the INDIOL from monoterpenes (MONITA --> INDIOL) would stay in the aerosol phase as a non-nitrate component of PM2.5, most of the INDIOL from isoprene (IONITA --> INDIOL) would come back out of the aerosol into the gas phase. Once it's lost its nitrate group, isoprene-derived INDIOL represents 1,2-dihydroxyisoprene and is a pretty volatile compound. I actually measured the oxidation rates and products of that compound a few years ago (here) and made a mechanism for it to go in GEOS-Chem (in the supplement of this paper, where I called it "IDIOL" to differentiate it from "INDIOL"), but that never made it into the standard version. So I think the ideal way to handle this would be to split up GEOS-Chem's current "INDIOL" into one monoterpene-derived compound that *does* get counted as PM2.5, and one isoprene-derived compound that goes on to do some gas-phase chemistry... we're just not quite there yet. 
> So in summary... tough to know whether or not to include INDIOL as it is now into PM2.5. I would lean towards yes, and know that it likely overestimates isoprene-derived organic aerosol. But it'd also be defensible not to.

## ALT1 Scenario (Surface Diagnostic)

GEOS-Chem can output `SpeciesConcALT1_*` fields, which represent species concentration at a given height (here 2M) calculated through dry deposition for **secondary aerosol species only** (SIA, SOA and SVPOA).
> Reasons that only secondary aerosol is available are that primary aerosol can have an emission flux from the ground, whereas secondary aerosol better fulfils the dry deposition model assumption.

These are used in the `PM25_S2M` composite calculation, where:

- SIA and SOA use ALT1 fields (surface diagnostic)
- BC, Dust, and Sea Salt use standard `SpeciesConcVV_*` fields

The `use_alt` parameter controls ALT1 usage:
- `"auto"` (default): detect from dataset variables
- `True`: force use of ALT1 fields
- `False`: use standard fields only

## AOD Calculation

`AOD_Total` computes the total aerosol optical depth by summing component AODs:
WL1 here represents wavelength at 550 nm
- `AODDust` — mineral dust AOD
- `AODHygWL1_SO4` — SNA AOD (hygroscopic)
- `AODHygWL1_BCPI` — black carbon AOD
- `AODHygWL1_SALA` — fine sea salt AOD
- `AODHygWL1_SALC` — coarse sea salt AOD
- `AODHygWL1_OCPI` or `AODHygWL1_POA1` — organic aerosol AOD (scheme-dependent)

## Configuration Reference

### species_config.yaml

All species definitions, molecular weights, category assignments, scheme memberships, and default constants are stored in `species_config.yaml`. See the header comments in that file for the full attribute reference.

### AerosolCalculator Parameters

```python
calculator = AerosolCalculator(
    ds,                          # xarray Dataset from GEOS-Chem
    dry=False,                   # True for dry mass, False for wet (with growth factors)
    poa_scheme="auto",           # "auto" | "SVPOA" | "NVPOA"
    soa_scheme="auto",           # "auto" | "simple" | "complex"
    dust_scheme="auto",          # "auto" | "DEAD" | "L23"
    use_alt="auto",              # "auto" | True | False
    include_hms=False,           # Include HMS in SIA
    include_indiol=False,        # Include INDIOL in SOA
    growth_factors=None,         # Override dict, e.g. {"SIA": 1.05, "ORG": 1.02, "SS": 1.2}
    omoc_ratios=None,            # Override dict, e.g. {"POA": 1.6, "OPOA": 2.3}
)
```

### Legacy API

The `AeroMassFine(ds, spcs, dry=False)` wrapper function is maintained for backward compatibility with existing scripts.
