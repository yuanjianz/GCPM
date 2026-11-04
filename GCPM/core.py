import os
import yaml
import xarray as xr
from typing import Optional, Union

# --- Load species configuration ---
_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'species_config.yaml'
)
with open(_CONFIG_PATH) as f:
    _CONFIG = yaml.safe_load(f)

SPECIES_DB = _CONFIG['species']
DEFAULTS = _CONFIG['defaults']

# --- Variable name prefixes ---
PF_CONC = 'SpeciesConcVV_'
PF_ALT = 'SpeciesConcALT1_'
PF_AERO = ''
PF_AOD = 'AOD'
PF_AOD_HYG = 'AODHygWL1_'

# Which species attribute holds the dust mass fraction under each size cut.
# A missing/null attribute means the full bin.
_SIZE_CUT_ATTR = {
    'PM1': 'dust_frac_pm1',
    'PM25': 'dust_frac',
    'PM10': 'dust_frac_pm10',
}


def _resolve_active_species(
    poa_scheme, soa_scheme, dust_scheme, use_alt, include_hms, include_indiol
):
    """Filter SPECIES_DB to only species active under the given configuration.

    When use_alt is False, each species' alt1 attribute is overridden to False
    so that downstream logic can treat alt1 uniformly as "ALT1 is available
    AND enabled for this species".
    """
    toggles = {
        'include_hms': include_hms,
        'include_indiol': include_indiol,
    }
    active = {}
    for name, attrs in SPECIES_DB.items():
        # Toggle filter
        flag = attrs.get('include_if')
        if flag is not None and not toggles.get(flag, False):
            continue

        # Scheme filter
        scheme = attrs.get('scheme')
        if scheme is None:
            match = True
        elif isinstance(scheme, dict):
            match = (
                scheme.get('poa_scheme', poa_scheme) == poa_scheme
                and scheme.get('soa_scheme', soa_scheme) == soa_scheme
                and scheme.get('dust_scheme', dust_scheme) == dust_scheme
            )
        else:
            match = False

        if match:
            # Copy to avoid mutating SPECIES_DB; disable alt1 globally when use_alt is False
            entry = dict(attrs)
            # Determine whether to calculate ALT1 version
            if not use_alt:
                entry['alt1'] = False
            active[name] = entry
    return active


class AerosolCalculator:
    """Calculates aerosol mass concentrations from GEOS-Chem xarray Datasets.

    See README.md for methodology documentation and species_config.yaml for
    species definitions.
    """

    def __init__(
        self,
        ds: xr.Dataset,
        poa_scheme: str = 'auto',
        soa_scheme: str = 'auto',
        dust_scheme: str = 'auto',
        use_alt: Optional[Union[str, bool]] = 'auto',
        include_hms: bool = False,
        include_indiol: bool = False,
        growth_factors: Optional[dict] = None,
        omoc_ratios: Optional[dict] = None,
        verbose: bool = False,
    ):
        self.ds = ds
        self._vars = ds.data_vars
        self._verbose = verbose

        # Resolve schemes
        self.poa_scheme = (
            self._detect_poa_scheme() if poa_scheme == 'auto' else poa_scheme
        )
        self.soa_scheme = (
            self._detect_soa_scheme() if soa_scheme == 'auto' else soa_scheme
        )
        self.dust_scheme = (
            self._detect_dust_scheme() if dust_scheme == 'auto' else dust_scheme
        )
        self.use_alt = self._detect_alt() if use_alt == 'auto' else use_alt

        # Toggles
        self.include_hms = include_hms
        self.include_indiol = include_indiol

        # Configurable constants (with defaults from YAML)
        self.growth_factors = {**DEFAULTS['growth_factors'], **(growth_factors or {})}
        self.omoc_ratios = {**DEFAULTS['omoc_ratios'], **(omoc_ratios or {})}
        self.std = DEFAULTS['standard_conditions']

        # Build active species set (use_alt propagates into each entry's alt1 flag)
        self.active_species = _resolve_active_species(
            self.poa_scheme,
            self.soa_scheme,
            self.dust_scheme,
            self.use_alt,
            self.include_hms,
            self.include_indiol,
        )

        # Build category lists for composite calculations
        def _in_category(cat):
            return [s for s, a in self.active_species.items() if a['category'] == cat]

        self.sia_species = _in_category('SIA')
        self.poa_species = _in_category('POA')
        self.soa_species = _in_category('SOA')
        self.bc_species = _in_category('BC')
        self.ss_species = _in_category('SS')
        self.dust_species = _in_category('Dust')
        # PM10-only species: no PM2.5 composite reads these lists.
        self.ss_coarse_species = _in_category('SS_coarse')
        self.dust_coarse_species = _in_category('Dust_coarse')

    def _log(self, message):
        if self._verbose:
            print(message)

    # --- Scheme auto-detection ---

    def _detect_poa_scheme(self):
        if PF_CONC + 'POA1' in self._vars:
            self._log('Detected POA scheme: SVPOA as POA1 is present')
            return 'SVPOA'
        if PF_CONC + 'OCPI' in self._vars:
            self._log('Detected POA scheme: NVPOA as OCPI is present')
            return 'NVPOA'
        raise ValueError('Cannot auto-detect POA scheme: neither POA1 nor OCPI found')

    def _detect_soa_scheme(self):
        if PF_CONC + 'ASOA1' in self._vars:
            self._log('Detected SOA scheme: complex as ASOA1 is present')
            return 'complex'
        if PF_CONC + 'SOAS' in self._vars:
            self._log('Detected SOA scheme: simple as SOAS is present')
            return 'simple'
        raise ValueError('Cannot auto-detect SOA scheme: neither ASOA1 nor SOAS found')

    def _detect_dust_scheme(self):
        if PF_CONC + 'DSTbin1' in self._vars:
            self._log('Detected dust scheme: L23 as DSTbin1 is present')
            return 'L23'
        if PF_CONC + 'DST1' in self._vars:
            self._log('Detected dust scheme: DEAD as DST1 is present')
            return 'DEAD'
        raise ValueError(
            'Cannot auto-detect dust scheme: neither DSTbin1 nor DST1 found'
        )

    def _detect_alt(self):
        for spc in self._vars:
            if spc.startswith(PF_ALT):
                self._log('Detected ALT1 (2M) diagnostic due to presence of ' + spc)
                return True
        self._log('No ALT1 (2M) diagnostic detected; using standard surface fields')
        return False

    # --- Core calculation ---

    def calculate_mass(self, spcs, dry=False, size_cut='PM25') -> xr.Dataset:
        """Calculate aerosol mass for one or more species/composites."""
        if isinstance(spcs, str):
            spcs = [spcs]

        outds = xr.Dataset()
        for spc in spcs:
            if hasattr(self, f'_calc_{spc}'):
                mass = getattr(self, f'_calc_{spc}')(dry=dry)
            else:
                mass = self._calc_single(spc, dry=dry, size_cut=size_cut)

            outds[PF_AERO + spc] = mass.assign_attrs(units='ug m-3')

        return outds

    def _calc_single(self, spc: str, dry=False, size_cut='PM25') -> xr.DataArray:
        """Convert a single species from VMR to mass concentration."""

        attrs = self.active_species[spc]
        is_alt = attrs.get('alt1')
        pf = PF_ALT if is_alt else PF_CONC

        # Ideal gas law: VMR -> ug/m3
        P, R, T = self.std['P'], self.std['R'], self.std['T']
        mass = self.ds[pf + spc] * P / R / T * attrs['mw'] * 1e6

        # Hygroscopic growth (wet mode only)
        if not dry:
            gf_group = attrs.get('growth_group')
            if gf_group and gf_group in self.growth_factors:
                mass *= self.growth_factors[gf_group]

        # OM/OC ratio
        omoc = attrs.get('omoc')
        if omoc is not None:
            mass *= omoc

        # Dust PM1 / PM2.5 / PM10 fraction (size-cut dependent).
        # null -> full bin (1.0); a number -> partial; 0.0 -> excluded.
        dust_frac = attrs.get(_SIZE_CUT_ATTR[size_cut])
        if dust_frac is not None:
            mass *= dust_frac

        return mass

    def _sum_components(
        self, components: list, dry=False, size_cut='PM25'
    ) -> xr.DataArray:
        """Sum mass of multiple species/composites"""
        summed = (
            self.calculate_mass(components, dry=dry, size_cut=size_cut)
            .to_array()
            .sum(dim='variable')
        )
        return summed

    # --- Composite species ---

    def _calc_Dust(self, dry=False):
        return self._sum_components(self.dust_species, dry=dry)

    def _calc_Dust_PM1(self, dry=False):
        """Mineral dust under the PM1 (1 um) size cut.

        Uses each dust species' dust_frac_pm1 fraction. Works for both DEAD
        (DST1 x0.06) and L23 (DSTbin1 + DSTbin2 + DSTbin3 x0.073) schemes.
        """
        return self._sum_components(self.dust_species, dry=dry, size_cut='PM1')

    def _calc_Dust_PM10(self, dry=False):
        """Mineral dust under the PM10 (10 um) size cut.

        L23 only: DSTbin1-6 full + DSTbin7 x0.156 (each species'
        dust_frac_pm10). DEAD bins carry no PM10 fraction, and summing only
        the ones that exist would silently under-count PM10, so it raises.
        """
        if self.dust_scheme != 'L23':
            raise NotImplementedError(
                f'Dust_PM10 is defined for the L23 dust scheme only, '
                f'not {self.dust_scheme}: no PM10 fractions are configured '
                f'for its bins.')
        return self._sum_components(
            self.dust_species + self.dust_coarse_species, dry=dry, size_cut='PM10'
        )

    def _calc_BC(self, dry=False):
        return self._sum_components(self.bc_species, dry=dry)

    def _calc_SS(self, dry=False):
        return self._sum_components(self.ss_species, dry=dry)

    def _calc_SS_PM10(self, dry=False):
        """Sea salt under the PM10 cut: SALA + SALC, both with the SS growth factor."""
        return self._sum_components(self.ss_species + self.ss_coarse_species, dry=dry)

    def _calc_SIA(self, dry=False):
        return self._sum_components(self.sia_species, dry=dry)

    def _calc_POA(self, dry=False):
        return self._sum_components(self.poa_species, dry=dry)

    def _calc_SOA(self, dry=False):
        return self._sum_components(self.soa_species, dry=dry)

    def _calc_PM25(self, dry=False):
        """PM2.5 at surface 2M using ALT1 diagnostic where available.

        Every species reads its own ALT1 field when its alt1 attribute is set
        (see _calc_single); _resolve_active_species clears alt1 when use_alt is
        False, so this transparently respects the use_alt configuration.
        """
        return self._sum_components(['SIA', 'POA', 'SOA', 'BC', 'Dust', 'SS'], dry=dry)

    def _calc_PM10(self, dry=False):
        """PM10: PM2.5 with dust and sea salt swapped for their PM10 cuts.

        SIA, OA and BC are taken as entirely below 2.5 um, so the only
        difference from PM25 is Dust -> Dust_PM10 and SS -> SS_PM10.
        """
        return self._sum_components(
            ['SIA', 'POA', 'SOA', 'BC', 'Dust_PM10', 'SS_PM10'], dry=dry
        )


# --- Legacy API Wrappers ---


def AeroMassFine(ds, spcs, dry=False, **kwargs):
    """Wrapper function for backward compatibility with existing scripts.

    Additional keyword arguments are forwarded to AerosolCalculator.
    """
    calculator = AerosolCalculator(ds, **kwargs)
    return calculator.calculate_mass(spcs, dry=dry)


def AOD_Total(ds):
    """Calculate total aerosol optical depth."""
    components = [
        ds[PF_AOD + 'Dust'],
        ds[PF_AOD_HYG + 'SO4'],
        ds[PF_AOD_HYG + 'BCPI'],
        ds[PF_AOD_HYG + 'SALA'],
        ds[PF_AOD_HYG + 'SALC'],
        (
            ds[PF_AOD_HYG + 'OCPI']
            if PF_AOD_HYG + 'OCPI' in ds.data_vars
            else ds[PF_AOD_HYG + 'POA1']
        ),
    ]
    total_aod = sum(components)
    return total_aod.assign_attrs(units='1').to_dataset(name=PF_AOD + 'Total')
