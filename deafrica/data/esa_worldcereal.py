"""
Download the ESA WorldCereal 10 m 2021 v100 products from Zenodo,
convert to Cloud Optimized Geotiff, and push to an S3 bucket.

Datasource: https://zenodo.org/records/7875105
"""

import os
import shutil
from zipfile import ZipFile

import click
import geopandas as gpd
import requests

from deafrica.utils import (
    AFRICA_EXTENT_URL,
    check_directory_exists,
    check_file_exists,
    crop_geotiff,
    get_filesystem,
    setup_logging,
)

WORLDCEREAL_AEZ_URL = "https://zenodo.org/records/7875105/files/WorldCereal_AEZ.geojson"
VALID_YEARS = ["2021"]
VALID_SEASONS = [
    "tc-annual",
    "tc-wintercereals",
    "tc-springcereals",
    "tc-maize-main",
    "tc-maize-second",
]
VALID_PRODUCTS = [
    "activecropland",
    "irrigation",
    "maize",
    "springcereals",
    "temporarycrops",
    "wintercereals",
]
LOCAL_DOWNLOAD_DIR = "tmp/worldcereal_data"

# Set log level to info
log = setup_logging()


def get_africa_aez_ids():
    """
    Get the Agro-ecological zone (AEZ) ids for the zones in Africa.

    Returns:
        set[str]: Agro-ecological zone (AEZ) ids for the zones in Africa
    """
    # Get the AEZ ids for Africa
    africa_extent = gpd.read_file(AFRICA_EXTENT_URL).to_crs("EPSG:4326")

    worldcereal_aez = gpd.read_file(WORLDCEREAL_AEZ_URL).to_crs("EPSG:4326")

    africa_worldcereal_aez_ids = worldcereal_aez.sjoin(
        africa_extent, predicate="intersects", how="inner"
    )["aez_id"].to_list()

    africa_worldcereal_aez_ids = [str(i) for i in africa_worldcereal_aez_ids]
    africa_worldcereal_aez_ids = set(africa_worldcereal_aez_ids)

    return africa_worldcereal_aez_ids


def download_and_unzip_data(zip_url: str):
    """
    Download and extract the selected World Cereal product GeoTIFFs.

    Args:
        zip_url (str): URL for the World Cereal product zip file to download.
    """
    if not check_directory_exists(LOCAL_DOWNLOAD_DIR):
        fs = get_filesystem(LOCAL_DOWNLOAD_DIR, anon=False)
        fs.makedirs(LOCAL_DOWNLOAD_DIR, exist_ok=True)
        log.info(f"Created the directory {LOCAL_DOWNLOAD_DIR}")

    zip_filename = os.path.basename(zip_url).split(".zip")[0] + ".zip"
    local_zip_path = os.path.join(LOCAL_DOWNLOAD_DIR, zip_filename)

    # Download the zip file.
    if not os.path.exists(local_zip_path):
        with requests.get(zip_url, stream=True, allow_redirects=True) as r:
            with open(local_zip_path, "wb") as f:
                shutil.copyfileobj(r.raw, f)
    else:
        log.info(f"Skipping download, {local_zip_path} already exists!")

    africa_aez_ids = get_africa_aez_ids()

    # Extract the AEZ-based GeoTIFF files
    with ZipFile(local_zip_path) as zip_ref:
        # All files in zip
        all_aez_geotiffs = [
            file for file in zip_ref.namelist() if file.endswith(".tif")
        ]
        # Filter to Africa extent
        africa_aez_geotiffs = [
            file
            for file in all_aez_geotiffs
            if os.path.basename(file).split("_")[0] in africa_aez_ids
        ]
        # Extract
        local_aez_geotiffs = []
        for file in africa_aez_geotiffs:
            local_file_path = os.path.join(LOCAL_DOWNLOAD_DIR, file)

            # TODO: Remove file path check
            # Check if the file already exists
            if os.path.exists(local_file_path):
                local_aez_geotiffs.append(local_file_path)
                continue

            # Extract file
            zip_ref.extract(member=file, path=LOCAL_DOWNLOAD_DIR)
            local_aez_geotiffs.append(local_file_path)

    log.info(f"Download complete! \nDownloaded {len(local_aez_geotiffs)} geotiffs")

    return local_aez_geotiffs


def download_esa_worldcereal_cogs(
    year: str, season: str, product: str, output_dir: str, overwrite: bool
):
    """
    Download the ESA WorldCereal 10 m 2021 v100 products from Zenodo,
    convert to Cloud Optimized Geotiff, and push to an S3 bucket.
    """
    if season not in VALID_SEASONS:
        raise ValueError(f"Invalid season selected: {season}")

    if product not in VALID_PRODUCTS:
        raise ValueError(f"Invalid product selected: {product}")

    if year not in VALID_YEARS:
        raise ValueError(f"Invalid year selected: {year}")

    # Download the classifcation geotiffs for the product
    classification_zip_url = f"https://zenodo.org/records/7875105/files/WorldCereal_{year}_{season}_{product}_classification.zip?download=1"

    log.info("Processing classification geotiffs")

    local_classification_geotiffs = download_and_unzip_data(classification_zip_url)
    for idx, local_classification_geotiff in enumerate(local_classification_geotiffs):
        log.info(
            f"Processing geotiff {local_classification_geotiff} {idx + 1}/{len(local_classification_geotiffs)}"
        )

        filename = os.path.splitext(os.path.basename(local_classification_geotiff))[0]
        aez_id, season_, product_, startdate, enddate, product_type = filename.split(
            "_"
        )

        # Define output files
        output_cog_path = os.path.join(
            output_dir, product, season, aez_id, year, f"{filename}.tif"
        )
        if not overwrite:
            if check_file_exists(output_cog_path):
                log.info(f"{output_cog_path} exists! Skipping ...")
                continue

        # Create the required parent directories
        output_cog_parent_dir = os.path.dirname(output_cog_path)
        if not check_directory_exists(output_cog_parent_dir):
            fs = get_filesystem(output_cog_parent_dir, anon=False)
            fs.makedirs(output_cog_parent_dir, exist_ok=True)
            log.info(f"Created the directory {output_cog_parent_dir}")

        crop_geotiff(local_classification_geotiff, output_cog_path)

    # Download the confidence geotiffs for the product
    confidence_zip_url = f"https://zenodo.org/records/7875105/files/WorldCereal_{year}_{season}_{product}_confidence.zip?download=1"

    log.info("Processing confidence geotiffs")

    local_confidence_geotiffs = download_and_unzip_data(confidence_zip_url)
    for idx, local_confidence_geotiff in enumerate(local_confidence_geotiffs):
        log.info(
            f"Processing geotiff {local_confidence_geotiff} {idx + 1}/{len(local_confidence_geotiffs)}"
        )

        filename = os.path.splitext(os.path.basename(local_confidence_geotiff))[0]
        aez_id, season_, product_, startdate, enddate, product_type = filename.split(
            "_"
        )

        # Define output files
        output_cog_path = os.path.join(
            output_dir, product, season, aez_id, year, f"{filename}.tif"
        )
        if not overwrite:
            if check_file_exists(output_cog_path):
                log.info(f"{output_cog_path} exists! Skipping...")
                continue

        # Create the required parent directories
        output_cog_parent_dir = os.path.dirname(output_cog_path)
        if not check_directory_exists(output_cog_parent_dir):
            fs = get_filesystem(output_cog_parent_dir, anon=False)
            fs.makedirs(output_cog_parent_dir, exist_ok=True)
            log.info(f"Created the directory {output_cog_parent_dir}")

        crop_geotiff(local_confidence_geotiff, output_cog_path)


@click.command("download-worldcereal-product")
@click.option(
    "--year",
    required=True,
    default="2021",
    type=click.Choice(VALID_YEARS, case_sensitive=False),
)
@click.option(
    "--season", required=True, type=click.Choice(VALID_SEASONS, case_sensitive=False)
)
@click.option(
    "--product", required=True, type=click.Choice(VALID_PRODUCTS, case_sensitive=False)
)
@click.option(
    "--output-dir",
    type=str,
    default="s3://deafrica-data-dev-af/esa_worldcereal_sample/",
    help="Directory to write the cropped COG files to",
)
@click.option("--overwrite/--no-overwrite", default=False)
def cli(year, season, product, output_dir, overwrite):
    """
    Available years are
    • 2021

    Naming convention of the ZIP files is as follows:
        WorldCereal_{year}_{season}_{product}_{classification|confidence}.zip
    """
    download_esa_worldcereal_cogs(
        year=year,
        season=season,
        product=product,
        output_dir=output_dir,
        overwrite=overwrite,
    )
