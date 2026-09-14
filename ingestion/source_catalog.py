"""Configured public marine-data sources and their ingestion adapters."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceDefinition:
    key: str
    name: str
    url: str
    adapter: str | None
    feed_env_var: str | None
    notes: str


SOURCES = (
    SourceDefinition("pfz_advisory", "INCOIS PFZ advisory", "https://incois.gov.in/MarineFisheries/PfzAdvisory", "pfz", "ORCA_PFZ_FEED_URL", "Portal page; configure a GeoJSON/JSON export URL for ingestion."),
    SourceDefinition("pfz_webgis", "INCOIS PFZ WebGIS", "https://incois.gov.in/MarineFisheries/PfzWebGis", "pfz", "ORCA_PFZ_FEED_URL", "Portal page; configure a machine-readable endpoint for ingestion."),
    SourceDefinition("pfz_interactive", "INCOIS PFZ interactive WebGIS", "https://incois.gov.in/geoportal/MFASPFZ/index.html", "pfz", "ORCA_PFZ_FEED_URL", "Interactive map; configure its data endpoint for ingestion."),
    SourceDefinition("pfz_bhuvan", "NRSC Bhuvan PFZ viewer", "https://bhuvan-app1.nrsc.gov.in/bhuvan2d/bhuvan/usrtasks/Ocean_services/pfz.php?id=en-us", None, None, "Alternate viewer; no direct normalized feed is assumed."),
    SourceDefinition("incois_services", "INCOIS services catalogue", "https://services.incois.gov.in/portal/services.jsp", None, None, "Catalogue/reference page for related services."),
    SourceDefinition("oceansat_open_data", "MOSDAC open data", "https://www.mosdac.gov.in/open-data", "satellite", "ORCA_SATELLITE_FEED_URL", "Requires MOSDAC login; configure a download/export URL."),
    SourceDefinition("oceansat3", "MOSDAC Oceansat-3", "https://www.mosdac.gov.in/oceansat-3", None, None, "Mission reference page."),
    SourceDefinition("oceansat3_atbds", "MOSDAC Oceansat-3 ATBDs", "https://www.mosdac.gov.in/oceansat3-references", None, None, "Calibration and methodology references."),
    SourceDefinition("imd_api", "IMD public APIs", "https://api.imd.gov.in/public/api_reference.html", "weather", "ORCA_IMD_API_URL", "Configure a named IMD API endpoint; set ORCA_IMD_API_KEY if required."),
    SourceDefinition("imd_cyclone", "IMD cyclone information", "https://mausam.imd.gov.in/responsive/cycloneinformation.php", None, None, "Portal page; use the IMD API for ingestion."),
    SourceDefinition("incois_osf", "INCOIS ocean-state forecast", "https://incois.gov.in/oceanservices/osfforecast.jsp", "osf", "ORCA_OSF_FEED_URL", "Portal page; configure an OSF data export URL for ingestion."),
    SourceDefinition("incois_erddap_sst", "INCOIS ERDDAP SST (NOAA AVHRR)", "https://erddap.incois.gov.in/erddap/griddap/NOAA_AVHRR_AMSR_datasets", None, None, "Griddap endpoint; use ingest_erddap.py with value-based constraints."),
    SourceDefinition("incois_erddap_chl", "INCOIS ERDDAP Chlorophyll", "https://erddap.incois.gov.in/erddap/griddap/incois_oceansat2_datasets", None, None, "Griddap endpoint for chlorophyll/Kd490; use ingest_erddap.py."),
    SourceDefinition("incois_erddap_wind", "INCOIS ERDDAP Wind (ASCAT)", "https://erddap.incois.gov.in/erddap/griddap/ascat_daily_datasets", None, None, "Griddap endpoint for wind; use ingest_erddap.py."),
    SourceDefinition("incois_erddap_argo", "INCOIS ERDDAP ARGO Floats", "https://erddap.incois.gov.in/erddap/tabledap/Indian_ARGO_Floats", None, None, "Tabledap endpoint with QC flags; use ingest_argo.py for validated ground truth."),
    SourceDefinition("marine_regions_eez", "Marine Regions EEZ dataset", "https://marineregions.org/downloads.php", "boundaries", "ORCA_BOUNDARIES_FEED_URL", "Configure a GeoJSON export for ingestion."),
    SourceDefinition("protected_planet", "Protected Planet WDPA", "https://www.protectedplanet.net/country/IND", "boundaries", "ORCA_BOUNDARIES_FEED_URL", "Configure a filtered India MPA export; set ORCA_WDPA_TOKEN if required."),
    SourceDefinition("gebco", "GEBCO bathymetry", "https://download.gebco.net/", None, None, "Raster/gridded bathymetry; it is not supported by the vector loaders."),
)


def get_source(key: str) -> SourceDefinition:
    for source in SOURCES:
        if source.key == key:
            return source
    valid = ", ".join(source.key for source in SOURCES)
    raise KeyError(f"Unknown source {key!r}. Choose one of: {valid}")