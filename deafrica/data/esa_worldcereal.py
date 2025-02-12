"""
Download the ESA WorldCereal 10 m 2021 v100 products from Zenodo,
convert to CLoud Optimized Geotiff, and push to an S3 bucket.

Datasource: https://zenodo.org/records/7875105
"""

import os
import shutil
from zipfile import ZipFile

import click
import geopandas as gpd
import requests
import rioxarray
from odc.aws import s3_dump
from odc.geo.xr import assign_crs, write_cog
from yarl import URL

from deafrica.utils import AFRICA_BBOX, setup_logging

AFRICA_EXTENT_URL = "https://raw.githubusercontent.com/digitalearthafrica/deafrica-extent/master/africa-extent-bbox.json"
WORLDCEREAL_AEZ_URL = "https://zenodo.org/records/7875105/files/WorldCereal_AEZ.geojson"
VALID_YEARS = ["2021"]
VALID_SEASONS = [
    "tc-annual",
    "tc-wintercereals",
    "tc-springcereals",
    "tc-maize-main",
    "tc-maize-second",
]
VALID_PRODUCT_TYPE = ["classification", "confidence"]

DOWNLOAD_DIR = "worldcereal_data"

# Set log level to info
log = setup_logging()


def download_and_unzip_data(zip_url: str):
    """
    Download and extract the selected World Cereal product GeoTIFFs.

    Args:
        zip_url (str): URL for the World Cereal product zip file to download.
    """
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    zip_filename = os.path.basename(zip_url).split(".zip")[0] + ".zip"
    local_zip_path = os.path.join(DOWNLOAD_DIR, zip_filename)

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
            local_file_path = os.path.join(DOWNLOAD_DIR, file)

            # TODO: Remove file path check
            # Check if the file already exists
            if os.path.exists(local_file_path):
                local_aez_geotiffs.append(local_file_path)
                continue

            # Extract file
            zip_ref.extract(member=file, path=DOWNLOAD_DIR)
            local_aez_geotiffs.append(local_file_path)

    log.info(f"Download complete! \nDownloaded {len(local_aez_geotiffs)} geotiffs")

    return local_aez_geotiffs


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


def esa_worldcereal_download_stac_cog(year, season, product, product_type, s3_dst):

    if season not in VALID_SEASONS:
        raise ValueError(f"Invalid season selected: {season}")

    if product_type not in VALID_PRODUCT_TYPE:
        raise ValueError(f"Invalid product type selected: {product_type}")

    if year not in VALID_YEARS:
        raise ValueError(f"Invalid year selected: {year}")

    # URL for the zip file
    zip_url = f"https://zenodo.org/records/7875105/files/WorldCereal_{year}_{season}_{product}_{product_type}.zip?download=1"

    # Download data
    local_aez_geotiffs = download_and_unzip_data(zip_url)

    for idx, local_geotiff in enumerate(local_aez_geotiffs):
        log.info(f"Processing geotiff {idx+1}/{len(local_aez_geotiffs)}")
        filename = os.path.splitext(os.path.basename(local_geotiff))[0]
        aez_id, season_, product_, startdate, enddate, product_type_ = filename.split(
            "_"
        )

        # Define output files
        out_cog = URL(s3_dst) / str(year) / aez_id / f"{filename}.tif"
        # out_stac = URL(s3_dst) / str(year) / aez_id / f"{filename}.stac-item.json"

        # Create and upload COG
        da = rioxarray.open_rasterio(local_geotiff).squeeze(dim="band")
        crs = f"EPSG:{da.rio.crs.to_epsg()}"
        nodata = da.rio.nodata
        assert crs == "EPSG:4326"

        # Subset to Africa
        ulx, uly, lrx, lry = AFRICA_BBOX
        # Note: lats are upside down!
        da = da.sel(y=slice(uly, lry), x=slice(ulx, lrx))
        # Add crs information
        da = assign_crs(da, crs=crs)

        # Create an in memory COG.
        cog_bytes = write_cog(
            geo_im=da, fname=":mem:", nodata=nodata, overview_resampling="nearest"
        )

        # Upload COG to s3
        s3_dump(
            data=cog_bytes,
            url=str(out_cog),
            ACL="bucket-owner-full-control",
            ContentType="image/tiff",
        )
        log.info(f"COG written to {out_cog}")

        # Create and upload STAC


@click.command("download-worldcereal-product")
@click.option("--year", required=True, default="2021")
@click.option("--season", required=True)
@click.option("--product", required=True)
@click.option("--product-type", required=True, default="classification")
@click.option("--s3_dst", default="s3://deafrica-data-dev-af/esa_worldcereal_sample/")
def cli(year, season, product, product_type, s3_dst):
    """
    Available years are
    • 2021

    Naming convention of the ZIP files is as follows:
        WorldCereal_{year}_{season}_{product}_{classification|confidence}.zip
    """
    esa_worldcereal_download_stac_cog(
        year=year,
        season=season,
        product=product,
        product_type=product_type,
        s3_dst=s3_dst,
    )
