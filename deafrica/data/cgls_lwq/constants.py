"""
Manifest files and measurements of interest for the
Copernicus Global Land Service - Lake Water Quality ODC products
"""

MANIFEST_FILE_URLS = {
    "cgls_lwq300_2002_2012": "https://globalland.vito.be/download/manifest/lwq_300m_v1_10daily-reproc_netcdf/manifest_clms_global_lwq_300m_v1_10daily-reproc_netcdf_latest.txt",
    "cgls_lwq300_2016_2024": "https://globalland.vito.be/download/manifest/lwq_300m_v1_10daily-nrt_netcdf/manifest_clms_global_lwq_300m_v1_10daily-nrt_netcdf_latest.txt",
    "cgls_lwq100_2019_2024": "https://globalland.vito.be/download/manifest/lwq_100m_v1_10daily-nrt_netcdf/manifest_clms_global_lwq_100m_v1_10daily-nrt_netcdf_latest.txt",
    "cgls_lwq300_2024_nrt": "https://globalland.vito.be/download/manifest/lwq_300m_v2_10daily-nrt_netcdf/manifest_clms_global_lwq_300m_v2_10daily-nrt_netcdf_latest.txt",
    "cgls_lwq100_2024_nrt": "https://globalland.vito.be/download/manifest/lwq_100m_v2_10daily-nrt_netcdf/manifest_clms_global_lwq_100m_v2_10daily-nrt_netcdf_latest.txt",
}
MEASUREMENTS_1 = [
    "first_obs",
    "last_obs",
    "n_obs_quality_risk_sum",
    "num_obs",
    "stats_valid_obs_tsi_sum",
    "stats_valid_obs_turbidity_sum",
    "trophic_state_index",
    "turbidity_mean",
    "turbidity_sigma",
]
MEASUREMENTS_2 = [
    "first_obs",
    "last_obs",
    "num_obs",
    "trophic_state_index",
    "turbidity_blended_mean",
]
MEASUREMENTS_3 = [
    "chla_mean",
    "chla_uncertainty",
    "first_obs",
    "floating_cyanobacteria",
    "last_obs",
    "num_obs",
    "quality_flags",
    "trophic_state_index",
    "tsm_mean",
    "tsm_uncertainty",
    "turbidity_mean",
]
MEASUREMENTS_4 = [
    "chla_mean",
    "first_obs",
    "floating_cyanobacteria",
    "last_obs",
    "num_obs",
    "quality_flags",
    "trophic_state_index",
    "tsm_mean",
    "turbidity_mean",
]

MEASUREMENTS = {
    "cgls_lwq300_2002_2012": MEASUREMENTS_1,
    "cgls_lwq300_2016_2024": MEASUREMENTS_1,
    "cgls_lwq100_2019_2024": MEASUREMENTS_2,
    "cgls_lwq300_2024_nrt": MEASUREMENTS_3,
    "cgls_lwq100_2024_nrt": MEASUREMENTS_4,
}
NAMING_PREFIX = "c_gls"
