import geopandas as gpd

print("Loading giant US file...")
gdf = gpd.read_file('tl_2025_us_county.shp')

print("Filtering for Texas...")
# Filter for Texas (State FIPS '48')
texas_gdf = gdf[gdf['STATEFP'] == '48']

print("Saving optimized file...")
texas_gdf.to_file('texas_counties.shp')
print("Done! Created texas_counties.shp")
