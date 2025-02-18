"""
Generate stac files for the WaPOR version 3.0 Datasets
"""

import calendar
import collections
import json
import os
import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

import click
import fsspec
import gcsfs
import pandas as pd
import requests
import s3fs
from dateutil.relativedelta import relativedelta
from eodatasets3.images import ValidDataMethod
from eodatasets3.model import DatasetDoc
from eodatasets3.serialise import to_path  # noqa F401
from eodatasets3.stac import to_stac_item
from fsspec.implementations.local import LocalFileSystem
from gcsfs import GCSFileSystem
from odc.aws import s3_dump
from s3fs.core import S3FileSystem

from deafrica.easi_assemble import EasiPrepare
from deafrica.utils import (
    odc_uuid,
    setup_logging,
)

# Set log level to info
log = setup_logging()


def is_s3_path(path: str) -> bool:
    return path.startswith("s3://")


def is_gcsfs_path(path: str) -> bool:
    return path.startswith("gcs://") or path.startswith("gs://")


def is_url(path: str) -> bool:
    return path.startswith("http://") or path.startswith("https://")


def get_filesystem(
    path: str,
    anon: bool = True,
) -> S3FileSystem | LocalFileSystem | GCSFileSystem:
    if is_s3_path(path=path):
        fs = s3fs.S3FileSystem(
            anon=anon, s3_additional_kwargs={"ACL": "bucket-owner-full-control"}
        )
    elif is_gcsfs_path(path=path):
        if anon:
            fs = gcsfs.GCSFileSystem(token="anon")
        else:
            fs = gcsfs.GCSFileSystem()
    else:
        fs = fsspec.filesystem("file")
    return fs


def check_file_exists(path: str) -> bool:
    fs = get_filesystem(path=path, anon=True)
    if fs.exists(path) and fs.isfile(path):
        return True
    else:
        return False


def check_directory_exists(path: str) -> bool:
    fs = get_filesystem(path=path, anon=True)
    if fs.exists(path) and fs.isdir(path):
        return True
    else:
        return False


def check_file_extension(path: str, accepted_file_extensions: list[str]) -> bool:
    _, file_extension = os.path.splitext(path)
    if file_extension.lower() in accepted_file_extensions:
        return True
    else:
        return False


def is_geotiff(path: str) -> bool:
    accepted_geotiff_extensions = [".tif", ".tiff", ".gtiff"]
    return check_file_extension(
        path=path, accepted_file_extensions=accepted_geotiff_extensions
    )


def find_geotiff_files(directory_path: str, file_name_pattern: str = ".*") -> list[str]:
    file_name_pattern = re.compile(file_name_pattern)

    fs = get_filesystem(path=directory_path, anon=True)

    geotiff_file_paths = []

    for root, dirs, files in fs.walk(directory_path):
        for file_name in files:
            if is_geotiff(path=file_name):
                if re.search(file_name_pattern, file_name):
                    geotiff_file_paths.append(os.path.join(root, file_name))
                else:
                    continue
            else:
                continue

    if is_s3_path(path=directory_path):
        geotiff_file_paths = [f"s3://{file}" for file in geotiff_file_paths]
    elif is_gcsfs_path(path=directory_path):
        geotiff_file_paths = [f"gs://{file}" for file in geotiff_file_paths]
    return geotiff_file_paths


def get_WaPORv3_info(url: str) -> pd.DataFrame:
    """
    Get information on WaPOR v3 data from the api url.
    WaPOR v3 variables are stored in `mapsets`, which in turn contain
    `rasters` that contain the data for a particular date or period.

    Parameters
    ----------
    url : str
        URL to get information from
    Returns
    -------
    pd.DataFrame
        A table of the mapset attributes found.
    """
    data = {"links": [{"rel": "next", "href": url}]}

    output_dict = collections.defaultdict(list)
    while "next" in [x["rel"] for x in data["links"]]:
        url_ = [x["href"] for x in data["links"] if x["rel"] == "next"][0]
        response = requests.get(url_)
        response.raise_for_status()
        data = response.json()["response"]
        for item in data["items"]:
            for key in list(item.keys()):
                if key == "links":
                    output_dict[key].append(item[key][0]["href"])
                else:
                    output_dict[key].append(item[key])

    output_df = pd.DataFrame(output_dict)

    if "code" in output_df.columns:
        output_df.sort_values("code", inplace=True)
        output_df.reset_index(drop=True, inplace=True)
    return output_df


def get_mapset_rasters_from_api(wapor_v3_mapset_code: str) -> list[str]:
    base_url = (
        "https://data.apps.fao.org/gismgr/api/v2/catalog/workspaces/WAPOR-3/mapsets"
    )
    wapor_v3_mapset_url = os.path.join(base_url, wapor_v3_mapset_code, "rasters")
    wapor_v3_mapset_rasters = get_WaPORv3_info(wapor_v3_mapset_url)[
        "downloadUrl"
    ].to_list()
    return wapor_v3_mapset_rasters


def get_mapset_rasters_from_gsutil_uri(wapor_v3_mapset_code: str) -> list[str]:
    base_url = "gs://fao-gismgr-wapor-3-data/DATA/WAPOR-3/MAPSET/"
    wapor_v3_mapset_url = os.path.join(base_url, wapor_v3_mapset_code)
    wapor_v3_mapset_rasters = find_geotiff_files(directory_path=wapor_v3_mapset_url)
    return wapor_v3_mapset_rasters


def get_mapset_rasters(wapor_v3_mapset_code: str) -> list[str]:
    try:
        wapor_v3_mapset_rasters = get_mapset_rasters_from_api(wapor_v3_mapset_code)
    except Exception:
        wapor_v3_mapset_rasters = get_mapset_rasters_from_gsutil_uri(
            wapor_v3_mapset_code
        )
    log.info(
        f"Found {len(wapor_v3_mapset_rasters)} rasters for the mapset {wapor_v3_mapset_code}"
    )
    return wapor_v3_mapset_rasters


def get_dekad(year: str | int, month: str | int, dekad_label: str) -> tuple:
    """
    Get the end date of the dekad that a date belongs to and the time range
    for the dekad.
    Every month has three dekads, such that the first two dekads
    have 10 days (i.e., 1-10, 11-20), and the third is comprised of the
    remaining days of the month.

    Parameters
    ----------
    year: int | str
        Year of the dekad
    month: int | str
        Month of the dekad
    dekad_label: str
        Label indicating whether the date falls in the 1st, 2nd or 3rd dekad
        in a month

    Returns
    -------
    tuple
        The end date of the dekad and the time range for the dekad.
    """
    if isinstance(year, str):
        year = int(year)

    if isinstance(month, str):
        month = int(month)

    first_day = datetime(year, month, 1)
    last_day = datetime(year, month, calendar.monthrange(year, month)[1])

    d1_start_date, d2_start_date, d3_start_date = pd.date_range(
        start=first_day, end=last_day, freq="10D", inclusive="left"
    )
    if dekad_label == "D1":
        input_datetime = (d2_start_date - relativedelta(days=1)).to_pydatetime()
        start_datetime = d1_start_date.to_pydatetime()
        end_datetime = input_datetime.replace(hour=23, minute=59, second=59)
    elif dekad_label == "D2":
        input_datetime = (d3_start_date - relativedelta(days=1)).to_pydatetime()
        start_datetime = d2_start_date.to_pydatetime()
        end_datetime = input_datetime.replace(hour=23, minute=59, second=59)
    elif dekad_label == "D3":
        input_datetime = last_day
        start_datetime = d3_start_date.to_pydatetime()
        end_datetime = input_datetime.replace(hour=23, minute=59, second=59)

    return input_datetime, (start_datetime, end_datetime)


def get_last_modified(file_path: str):
    """Returns the Last-Modified timestamp
    of a given URL if available."""
    if is_gcsfs_path(file_path):
        url = file_path.replace("gs://", "https://storage.googleapis.com/")
    else:
        url = file_path
    response = requests.head(url, allow_redirects=True)
    last_modified = response.headers.get("Last-Modified")
    if last_modified:
        return parsedate_to_datetime(last_modified)
    else:
        return None


def prepare_wapor_soil_moisture_dataset(
    dataset_path: str | Path,
    product_yaml: str | Path,
    output_path: str = None,
) -> DatasetDoc:
    """
    Prepare an eo3 metadata file for SAMPLE data product.
    @param dataset_path: Path to the geotiff to create dataset metadata for.
    @param product_yaml: Path to the product definition yaml file.
    @param output_path: Path to write the output metadata file.

    :return: DatasetDoc
    """
    ## File format of data
    # e.g. cloud-optimised GeoTiff (= GeoTiff)
    file_format = "GeoTIFF"
    file_extension = ".tif"

    tile_id = os.path.basename(dataset_path).removesuffix(file_extension)

    ## Initialise and validate inputs
    # Creates variables (see EasiPrepare for others):
    # - p.dataset_path
    # - p.product_name
    # The output_path and tile_id are use to create a dataset unique filename
    # for the output metadata file.
    # Variable p is a dictionary of metadata and measurements to be written
    # to the output metadata file.
    # The code will populate p with the metadata and measurements and then call
    # p.write_eo3() to write the output metadata file.
    p = EasiPrepare(dataset_path, product_yaml, output_path)

    ## IDs and Labels should be dataset and Product unique
    # Unique dataset name, probably parsed from p.dataset_path or a filename
    unique_name = f"{tile_id}"
    # Can not have '.' in label
    unique_name_replace = re.sub("\.", "_", unique_name)
    label = f"{unique_name_replace}-{p.product_name}"
    # p.label = label # Optional
    # product_name is added by EasiPrepare().init()
    p.product_uri = f"https://explorer.digitalearth.africa/product/{p.product_name}"
    # The version of the source dataset
    p.dataset_version = "v3.0"
    # Unique dataset UUID built from the unique Product ID
    p.dataset_id = odc_uuid(p.product_name, p.dataset_version, [unique_name])

    ## Satellite, Instrument and Processing level
    # High-level name for the source data (satellite platform or project name).
    # Comma-separated for multiple platforms.
    p.platform = "WaPORv3"
    # p.instrument = 'SAMPLETYPE'  #  Instrument name, optional
    # Organisation that produces the data.
    # URI domain format containing a '.'
    p.producer = "www.fao.org"
    # ODC/EASI identifier for this "family" of products, optional
    # p.product_family = 'FAMILY_STUFF'
    p.properties["odc:file_format"] = file_format  # Helpful but not critical
    p.properties["odc:product"] = p.product_name

    ## Scene capture and Processing

    # Datetime derived from file name
    year, month, dekad_label = tile_id.split(".")[-1].split("-")
    input_datetime, time_range = get_dekad(year, month, dekad_label)
    # Searchable datetime of the dataset, datetime object
    p.datetime = input_datetime
    # Searchable start and end datetimes of the dataset, datetime objects
    p.datetime_range = time_range
    # When the source dataset was created by the producer, datetime object
    processed_dt = get_last_modified(dataset_path)
    if processed_dt:
        p.processed = processed_dt

    ## Geometry
    # Geometry adds a "valid data" polygon for the scene, which helps bounding box searching in ODC
    # Either provide a "valid data" polygon or calculate it from all bands in the dataset
    # Some techniques are more accurate than others, but all are valid. You may need to use coarser methods if the data
    # is particularly noisy or sparse.
    # ValidDataMethod.thorough = Vectorize the full valid pixel mask as-is
    # ValidDataMethod.filled = Fill holes in the valid pixel mask before vectorizing
    # ValidDataMethod.convex_hull = Take convex-hull of valid pixel mask before vectorizing
    # ValidDataMethod.bounds = Use the image file bounds, ignoring actual pixel values
    # p.geometry = Provide a "valid data" polygon rather than read from the file, shapely.geometry.base.BaseGeometry()
    # p.crs = Provide a CRS string if measurements GridSpec.crs is None, "epsg:*" or WKT
    p.valid_data_method = ValidDataMethod.bounds

    ## Product-specific properties, OPTIONAL
    # For examples see eodatasets3.properties.Eo3Dict().KNOWN_PROPERTIES
    # p.properties[f'{custom_prefix}:algorithm_version'] = ''
    # p.properties[f'{custom_prefix}:doi'] = ''
    # p.properties[f'{custom_prefix}:short_name'] = ''
    # p.properties[f'{custom_prefix}:processing_system'] = 'SomeAwesomeProcessor' # as an example

    ## Add measurement paths
    # This simple loop will go through all the measurements and determine their grids, the valid data polygon, etc
    # and add them to the dataset.
    # For LULC there is only one measurement, land_cover_class
    p.note_measurement(
        "relative_soil_moisture", dataset_path, relative_to_metadata=False
    )

    return p.to_dataset_doc(validate_correctness=True, sort_measurements=True)


@click.command("download-wapor-v3")
@click.option(
    "--product-name",
    type=str,
    help="Name of the product to generate the stac item files for",
)
@click.option(
    "--product-yaml",
    type=str,
    help="File path or URL to the product definition yaml file",
)
@click.option(
    "--stac-output-dir",
    type=str,
    default="s3://deafrica-data-dev-af/wapor-v3/",
    help="Directory to write the stac files docs to",
)
@click.option("--overwrite/--no-overwrite", default=False)
def cli(
    product_name: str,
    product_yaml: str,
    stac_output_dir: str,
    overwrite: bool,
):
    valid_product_names = ["wapor_soil_moisture"]
    if product_name not in valid_product_names:
        raise NotImplementedError(
            f"Stac file generation has not been implemented for {product_name}"
        )

    # Set to /tmp as output metadata yaml files are not required.
    metadata_output_dir = "/tmp"
    if product_name not in os.path.basename(metadata_output_dir.rstrip("/")):
        metadata_output_dir = os.path.join(metadata_output_dir, product_name)
    if is_s3_path(metadata_output_dir):
        raise RuntimeError("Metadata files require to be written to a local directory")
    else:
        metadata_output_dir = Path(metadata_output_dir).resolve()

    if not is_s3_path(product_yaml):
        if is_url(product_yaml):
            product_yaml = product_yaml
        else:
            product_yaml = Path(product_yaml).resolve()
    else:
        NotImplemented("Product yaml is expected to be a local file or url not s3 path")

    # Create the proper format for the output directory
    if product_name not in os.path.basename(stac_output_dir.rstrip("/")):
        stac_output_dir = os.path.join(stac_output_dir, product_name)
    if not is_s3_path(stac_output_dir):
        stac_output_dir = Path(stac_output_dir).resolve()

    log.info(f"Generating stac files for the product {product_name}")

    if product_name == "wapor_soil_moisture":
        mapset_code = "L2-RSM-D"

    geotiffs = get_mapset_rasters(mapset_code)
    # Use a gsutil URI instead of the the public URL
    geotiffs = [i.replace("https://storage.googleapis.com/", "gs://") for i in geotiffs]

    for idx, geotiff in enumerate(geotiffs):
        log.info(f"Generating stac file for {geotiff} {idx+1}/{len(geotiffs)}")

        # File system Path() to the dataset
        # or gsutil URI prefix  (gs://bucket/key) to the dataset.
        if not is_s3_path(geotiff) and not is_gcsfs_path(geotiff):
            dataset_path = Path(geotiff)
        else:
            dataset_path = geotiff

        tile_id = os.path.basename(dataset_path).removesuffix(".tif")
        year, month, _ = tile_id.split(".")[-1].split("-")

        metadata_output_path = Path(
            os.path.join(
                metadata_output_dir, year, month, f"{tile_id}.odc-metadata.yaml"
            )
        )

        stac_item_destination_url = os.path.join(
            stac_output_dir, year, month, f"{tile_id}.stac-item.json"
        )

        if not overwrite:
            if check_file_exists(stac_item_destination_url):
                log.info(
                    f"{stac_item_destination_url} exists! Skipping stac file generation for {dataset_path}"
                )
                continue

        if product_name == "wapor_soil_moisture":
            dataset_doc = prepare_wapor_soil_moisture_dataset(
                dataset_path=dataset_path,
                product_yaml=product_yaml,
                output_path=metadata_output_path,
            )

        # Write the dataset doc to file
        # to_path(metadata_output_path, dataset_doc)
        # log.info(f"Wrote dataset to {metadata_output_path}")

        # Convert dataset doc to stac item
        stac_item = to_stac_item(
            dataset=dataset_doc,
            stac_item_destination_url=str(stac_item_destination_url),
        )

        # Fix links in stac item
        assets = stac_item["assets"]
        for band in assets.keys():
            band_url = assets[band]["href"]
            if band_url.startswith("gs://"):
                new_band_url = band_url.replace(
                    "gs://", "https://storage.googleapis.com/"
                )
                stac_item["assets"][band]["href"] = new_band_url

        if is_s3_path(stac_item_destination_url):
            s3_dump(
                data=json.dumps(stac_item, indent=2),
                url=stac_item_destination_url,
                ACL="bucket-owner-full-control",
                ContentType="application/json",
            )
        else:
            with open(stac_item_destination_url, "w") as file:
                json.dump(
                    stac_item, file, indent=2
                )  # `indent=4` makes it human-readable

        log.info(f"STAC item written to {stac_item_destination_url}")
