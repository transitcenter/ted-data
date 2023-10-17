"""GTFS Related functions and utilities

This module contains a set of utility functions specific to managing, analysing,
and validating GTFS feeds."""

import datetime
import difflib
import logging
import os
import urllib
import zipfile

import geopandas
import pandas
from slugify import slugify
import yaml

from gtfslite.gtfs import GTFS

MOBILITY_CATALOG_URL = "https://bit.ly/catalogs-csv"

logging.basicConfig(format="%(levelname)s: %(message)s", level=logging.DEBUG)


def download_gtfs_using_yaml(yaml_path: str, output_folder: str, custom_mdb_path=None):
    with open(yaml_path) as infile:
        config = yaml.safe_load(infile)

    if custom_mdb_path is None:
        # Fetch the MobilityData catalog's latest
        mdb = fetch_mobility_database()
    else:
        mdb = pandas.read_csv(custom_mdb_path)
    mdb = mdb[mdb["mdb_source_id"].isin(config["mdb_ids"])]
    mdb["name"] = mdb["name"].fillna("")
    result_data = {
        "mdb_provider": [],
        "mdb_name": [],
        "mdb_id": [],
        "gtfs_slug": [],
        "gtfs_agency_name": [],
        "gtfs_agency_url": [],
        "gtfs_agency_fare_url": [],
        "gtfs_start_date": [],
        "gtfs_end_date": [],
        "date_fetched": [],
    }

    today = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    if not os.path.exists(output_folder):
        os.mkdir(output_folder)

    for idx, row in mdb.iterrows():
        url = row["urls.latest"]
        # Get a slugified filename
        slug = slugify(f"{row['location.subdivision_name']} {row['provider']} {row['name']} {row['mdb_source_id']}")
        filename = f"{slug}.zip"
        print(slug)
        try:
            urllib.request.urlretrieve(url, os.path.join(output_folder, filename))
            result_data["mdb_provider"].append(row["provider"])
            result_data["mdb_name"].append(row["name"])
            result_data["mdb_id"].append(row["mdb_source_id"])
            result_data["gtfs_slug"].append(slug)
            gtfs = GTFS.load_zip(os.path.join(output_folder, filename))
            summary = gtfs.summary()
            result_data["gtfs_agency_name"].append(gtfs.agency.iloc[0]["agency_name"])
            result_data["gtfs_agency_url"].append(gtfs.agency.iloc[0]["agency_url"])

            if "agency_fare_url" in gtfs.agency.columns:
                result_data["gtfs_agency_fare_url"].append(gtfs.agency.iloc[0]["agency_fare_url"])
            else:
                result_data["gtfs_agency_fare_url"].append("")
            result_data["gtfs_start_date"].append(summary["first_date"].strftime("%Y-%m-%d"))
            result_data["gtfs_end_date"].append(summary["last_date"].strftime("%Y-%m-%d"))
            result_data["date_fetched"].append(today)
        except urllib.error.HTTPError:
            print("  HTTPERROR")
        except urllib.error.URLError:
            print("  URLERROR")

    result_df = pandas.DataFrame(result_data)
    result_df.to_csv(os.path.join(output_folder, "download_results.csv"), index=False)


def fetch_mobility_database() -> pandas.DataFrame:
    # Get the URL
    return pandas.read_csv(MOBILITY_CATALOG_URL)


def get_all_stops(gtfs_folder) -> geopandas.GeoDataFrame:
    """Get all the stop locations in a given set of GTFS files

    Parameters
    ----------
    gtfs_folder : str
        The folder path for the GTFS folder
    """
    stop_dfs = []
    for filename in os.listdir(gtfs_folder):
        # Load the zipfile
        print(filename)
        try:
            gtfs = GTFS.load_zip(os.path.join(gtfs_folder, filename))
            # Get the stops
            stops = gtfs.stops[["stop_id", "stop_name", "stop_lat", "stop_lon"]].copy()
            stops["agency"] = filename[:-4]
            stop_dfs.append(stops)
        except zipfile.BadZipFile:
            print(filename, "is not a zipfile, skipping...")

    df = pandas.concat(stop_dfs, axis="index")
    gdf = geopandas.GeoDataFrame(df, geometry=geopandas.points_from_xy(df.stop_lon, df.stop_lat), crs="EPSG:4326")
    return gdf


def remove_routes_from_gtfs(gtfs_path: str, output_folder: str, route_ids: list[str]):
    # Open/load the GTFS files
    # Use the "remove_route" feature to remove the set of routes
    # Make the output folder if it doesn't exist
    # Write the GTFS file
    zipfile_name = os.path.basename(gtfs_path)
    gtfs = GTFS.load_zip(gtfs_path)
    gtfs.delete_routes(route_ids)
    if not os.path.exists(output_folder):
        os.mkdir(output_folder)
    gtfs.write_zip(os.path.join(output_folder, zipfile_name))

def remove_premium_routes_from_gtfs(gtfs_folder: str, output_folder: str, premium_routes_path: str):
    """Make a copy of a GTFS folder without premium routes

    Parameters
    ----------
    gtfs_folder : str
        The path to the folder to remove premium routes from.
    output_folder : str
        The path to where the new GTFS folder without premium routes will be created.
    premium_routes_path : str
        The path to the csv containing the list of premium route slugs and their ids.
        This must specify a csv file and the csv should be formatted into 'route_slug, route_id' columns

    """
    premium_routes = pandas.read_csv(premium_routes_path, index_col = False)
    if not os.path.exists(output_folder):
        os.mkdir(output_folder)
    dated_entries = os.listdir(gtfs_folder)

    # Iterate through all dated entries
    for curr_dated_entry in dated_entries:
        # Make target output folder with the '-limited' tag
        dated_output_path = os.path.join(output_folder, curr_dated_entry + '-limited')
        os.mkdir(dated_output_path)
        zip_entries = os.listdir(os.path.join(gtfs_folder, curr_dated_entry))
        # Iterate through .zip entries
        for curr_zip_entry in zip_entries:
            # Find entry zip folder
            curr_zip_dir = os.path.join(gtfs_folder, curr_dated_entry, curr_zip_entry)
            curr_zip_slug = curr_zip_entry.removesuffix('.zip')
            
            if not(curr_zip_entry.startswith('._')):
                    print("Currently parsing: " + curr_dated_entry + ": " + curr_zip_entry)
        
            premium_slug_rows = premium_routes.loc[premium_routes['route_slug'] == curr_zip_slug]
            slug_premium_ids = (premium_slug_rows.iloc[:,1]).tolist()

            #Skip slug labelled __ALL__
            if '__ALL__' in slug_premium_ids:
                print(curr_zip_slug + " is a premium feed, skipping...")
            #delete specific routes within the given slug
            else:
                try: 
                    if (curr_zip_slug in premium_routes['route_slug'].values): #delete premium routes if it exists
                        remove_routes_from_gtfs(curr_zip_dir,dated_output_path,slug_premium_ids)
                    else: #not a feed containing premium routes: copy over current feed as is
                        copy = GTFS.load_zip(curr_zip_dir)
                        if not os.path.exists(dated_output_path):
                            os.mkdir(dated_output_path)
                        copy.write_zip(os.path.join(dated_output_path,curr_zip_entry))
                except zipfile.BadZipFile:
                    print(curr_zip_entry, "is not a zipfile, skipping...")

            if not(curr_zip_entry.startswith('._')):
                print("Finished parsing: " + curr_zip_entry)
        print("\n       ---Finished parsing feed: " + curr_dated_entry + "---\n")
    print(f"Done removing premium routes from {gtfs_folder}!")


def stops_in_block_groups(
    gtfs_folder, block_groups: geopandas.GeoDataFrame, date: datetime.date, buffer=400
) -> pandas.DataFrame:
    # Buffer the block groups to get "nearby" stops
    block_groups.geometry = block_groups.geometry.buffer(buffer)
    just_bgs = block_groups[["bg_id"]]
    columns = []
    datasets = []
    for filename in os.listdir(gtfs_folder):
        print(filename)
        try:
            gtfs = GTFS.load_zip(os.path.join(gtfs_folder, filename))
            column_name = os.path.splitext(filename)[0]
            columns.append(column_name)
            stops = geopandas.GeoDataFrame(
                gtfs.stops[["stop_id", "stop_lat", "stop_lon"]],
                geometry=geopandas.points_from_xy(gtfs.stops.stop_lon, gtfs.stops.stop_lat),
                crs="EPSG:4326",
            ).to_crs(block_groups.crs)
            joined = block_groups.sjoin(stops)
            data = {"bg_id": [], column_name: []}
            for bg_id in joined.bg_id.unique():
                # Get the stops in that zone
                bg_stops = joined[joined.bg_id == bg_id]
                trips = gtfs.unique_trips_at_stops(bg_stops.stop_id.tolist(), date).shape[0]
                data["bg_id"].append(bg_id)
                data[column_name].append(trips)

            data = pandas.DataFrame(data)
            data.set_index("bg_id", inplace=True)
            datasets.append(data)

        except zipfile.BadZipFile:
            print(filename, "is not a valid zipfile, skipping...")

    result = pandas.concat(datasets, axis=1, join="outer").fillna(0)
    result["total_trips"] = result[columns].sum(axis=1)
    all_bgs = just_bgs.join(result, how="left").fillna(0)
    return result


def summarize_gtfs_data(gtfs_folder, date: datetime.date) -> pandas.DataFrame:
    """Summarize all GTFS data in a given folder

    Parameters
    ----------
    gtfs_folder : str or os.path
        The path to the folder to summarize

    Returns
    -------
    pandas.DataFrame
        A dataframe containing the results for each feed in the folder as
        generated by GTFS lite
    """
    summaries = []
    for filename in os.listdir(gtfs_folder):
        print("Summarizing", filename)
        try:
            gtfs = GTFS.load_zip(os.path.join(gtfs_folder, filename))
            summary = gtfs.summary()
            summary["service_hours"] = gtfs.service_hours(date=date)
            summary["file"] = os.path.splitext(filename)[0]
            summaries.append(summary)

        except zipfile.BadZipFile:
            print(filename, "is not a valid zipfile, skipping...")

    return pandas.DataFrame(summaries)


def match_with_mobility_database(gtfs_folder, custom_mdb_path=None):
    if custom_mdb_path is None:
        mdb = fetch_mobility_database()
    else:
        mdb = pandas.read_csv(custom_mdb_path)
    mdb["name"] = mdb.name.fillna("")
    mdb = mdb[mdb.data_type == "gtfs"]
    mdb = mdb[mdb["location.country_code"] == "US"][["mdb_source_id", "location.subdivision_name", "provider", "name"]]
    mdb["slugified"] = mdb.provider.apply(slugify)
    # Let's go through the folder and see what we can do
    for filename in os.listdir(gtfs_folder):
        try:
            gtfs = GTFS.load_zip(os.path.join(gtfs_folder, filename))
            if gtfs.agency.shape[0] > 1:
                print("WARNING: Multiple agencies exist")
            agency_name = slugify(gtfs.agency.iloc[0].agency_name)
            print("Matching", os.path.splitext(filename)[0], f"({agency_name})")
            print("Route Types:", gtfs.routes.route_type.unique())
            mdb_matches = mdb[mdb.slugified.str.contains(agency_name)]
            if mdb_matches.shape[0] == 0:
                print(" Can't find a match for", agency_name)
                # Let's get close matches
                close_matches = difflib.get_close_matches(agency_name, mdb.slugified)
                if len(close_matches) > 0:
                    print(mdb[mdb.slugified.isin(close_matches)])
                    mdb_id = int(input("Enter correct mdb_source_id: "))
                else:
                    mdb_id = int(input("No match found. Enter mdb_id: "))
            if mdb_matches.shape[0] == 1:
                mdb_id = mdb_matches.iloc[0].mdb_source_id.astype(int)
            if mdb_matches.shape[0] > 1:
                print(mdb_matches)
                mdb_id = int(input("Enter correct mdb_source_id: "))

            if mdb_id > 0:
                row = mdb[mdb.mdb_source_id == mdb_id].iloc[0]
                slug = slugify(
                    f"{row['location.subdivision_name']} {row['provider']} {row['name']} {row['mdb_source_id']}"
                )
            else:
                slug = input("Enter Custom Slug: ")

            print(f"  {filename} --> {slug}.zip")
            os.rename(os.path.join(gtfs_folder, filename), os.path.join(gtfs_folder, f"{slug}.zip"))
            print()

        except zipfile.BadZipFile:
            print(filename, "is not a valid zipfile, skipping...")


def transit_service_intensity(gtfs_folder, date: datetime.date) -> pandas.DataFrame:
    for filename in os.listdir(gtfs_folder):
        try:
            gtfs = GTFS.load_zip(os.path.join(gtfs_folder, filename))
        except zipfile.BadZipFile:
            print(filename, "is not a valid zipfile, skipping...")
