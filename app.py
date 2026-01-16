import streamlit as st
import geopandas as gpd
import matplotlib.pyplot as plt
import contextily as cx
import matplotlib.patheffects as pe
import folium
from streamlit_folium import st_folium
from adjustText import adjust_text
import io

st.set_page_config(layout="wide", page_title="Workforce Solutions Map Generator")

# --- HELPER: CLEAN GEOMETRY ---
def clean_geoms(gdf):
    """
    Removes empty geometries and GeometryCollections that break Folium.
    Keeps only Polygons and MultiPolygons.
    """
    if gdf is None or gdf.empty:
        return gdf
    # 1. Remove empty rows
    gdf = gdf[~gdf.is_empty]
    # 2. Keep only valid area shapes (Polygons), ignoring Points/Lines from clip artifacts
    gdf = gdf[gdf.geometry.type.isin(['Polygon', 'MultiPolygon'])]
    return gdf

# --- CACHED DATA LOADING ---
@st.cache_data
def load_data():
    # Update paths to your actual files
    county_path = 'texas_counties.shp'
    place_path = 'Cities.shp'
    isd_path = 'tl_2025_48_unsd.shp'

    gdf_counties = gpd.read_file(county_path)
    gdf_places = gpd.read_file(place_path)
    gdf_isds = gpd.read_file(isd_path)

    return gdf_counties, gdf_places, gdf_isds

try:
    gdf_counties, gdf_places, gdf_isds = load_data()

    city_col = 'CITY_NM' if 'CITY_NM' in gdf_places.columns else 'NAME'

    # Calculate Area
    gdf_places = gdf_places.to_crs(epsg=3857)
    gdf_places['area_sq_mi'] = gdf_places.geometry.area * 3.86102e-7

    # Filter Region
    target_counties = [
        'Austin', 'Brazoria', 'Chambers', 'Colorado', 'Fort Bend',
        'Galveston', 'Harris', 'Liberty', 'Matagorda', 'Montgomery',
        'Walker', 'Waller', 'Wharton'
    ]
    region_gdf = gdf_counties[
        (gdf_counties['NAME'].isin(target_counties)) &
        (gdf_counties['STATEFP'] == '48')
    ]

except Exception as e:
    st.error(f"Error loading shapefiles: {e}")
    st.stop()

# --- SIDEBAR CONTROLS ---
st.sidebar.header("⚙️ Map Settings")
map_type = st.sidebar.selectbox("Select Map Region", ["Gulf Coast Region (13 Counties)", "Brazoria County Specific"])

st.sidebar.subheader("🧹 Clutter Control")
min_area = st.sidebar.slider("Hide Cities Smaller Than (Sq Miles)", 0.0, 50.0, 5.0)

st.sidebar.subheader("🎨 Colors")
fill_color_hex = st.sidebar.color_picker("Region Fill Color", "#b3cde3")
outline_color = st.sidebar.color_picker("Outline Color", "#000000")
text_color = st.sidebar.color_picker("City Label Color", "#8B0000")
isd_outline_color = st.sidebar.color_picker("ISD Color (Brazoria)", "#000080")

st.sidebar.subheader("📐 Quality & Dimensions")
export_dpi = st.sidebar.select_slider("Export Resolution (DPI)", options=[150, 300, 450, 600], value=300)
font_size_header = st.sidebar.slider("Title Font Size", 10, 80, 24)
font_size_labels = st.sidebar.slider("City Label Size", 4, 30, 8)
fill_opacity = st.sidebar.slider("Fill Opacity", 0.0, 1.0, 0.4)

# --- MAP PREPARATION ---

if map_type == "Gulf Coast Region (13 Counties)":
    main_gdf = region_gdf
    main_gdf_3857 = main_gdf.to_crs(epsg=3857)

    clipped_cities = gpd.clip(gdf_places, main_gdf_3857)
    # CLEAN THE CITIES
    clipped_cities = clean_geoms(clipped_cities)

    display_gdf = main_gdf
    display_isds = None
    title = "Workforce Solutions Gulf Coast Region"

else: # Brazoria
    brazoria_gdf = region_gdf[region_gdf['NAME'] == 'Brazoria']
    brazoria_3857 = brazoria_gdf.to_crs(epsg=3857)

    # Clip ISDs
    isds_3857 = gdf_isds.to_crs(epsg=3857)
    clipped_isds = gpd.clip(isds_3857, brazoria_3857)
    # FIX: Clean the ISDs to remove GeometryCollections
    clipped_isds = clean_geoms(clipped_isds)

    # Clip Cities
    clipped_cities = gpd.clip(gdf_places, brazoria_3857)
    # FIX: Clean the Cities too
    clipped_cities = clean_geoms(clipped_cities)

    display_gdf = brazoria_gdf
    display_isds = clipped_isds
    title = "Brazoria County: City Limits & ISDs"

# Apply Area Filter
display_cities = clipped_cities[clipped_cities['area_sq_mi'] >= min_area]

# --- TAB 1: INTERACTIVE MAP ---
tab1, tab2 = st.tabs(["🗺️ Interactive Map", "🖨️ High-Res Print Preview"])

with tab1:
    st.subheader(f"Interactive View: {title}")

    m = folium.Map(
        location=[29.5, -95.5],
        zoom_start=8,
        tiles=None
    )
    folium.TileLayer(
        tiles="CartoDB positron",
        name="Light Map",
        detect_retina=True
    ).add_to(m)

    folium.GeoJson(
        display_gdf.to_crs(epsg=4326),
        style_function=lambda x: {
            'fillColor': fill_color_hex,
            'color': outline_color,
            'weight': 2,
            'fillOpacity': fill_opacity
        },
        tooltip=folium.GeoJsonTooltip(fields=['NAME'], aliases=['County:'])
    ).add_to(m)

    if display_isds is not None and not display_isds.empty:
        folium.GeoJson(
            display_isds.to_crs(epsg=4326),
            style_function=lambda x: {
                'fillColor': 'orange',
                'color': isd_outline_color,
                'weight': 1,
                'dashArray': '5, 5',
                'fillOpacity': 0.1
            },
            tooltip=folium.GeoJsonTooltip(fields=['NAME'], aliases=['ISD:'])
        ).add_to(m)

    # City Markers
    if not display_cities.empty:
        cities_4326 = display_cities.to_crs(epsg=4326)
        for idx, row in cities_4326.iterrows():
            # Safety check for geometry type before centroid
            if row.geometry:
                folium.CircleMarker(
                    location=[row.geometry.centroid.y, row.geometry.centroid.x],
                    radius=3,
                    color='red',
                    fill=True,
                    tooltip=f"{row[city_col]} ({row['area_sq_mi']:.1f} sq mi)"
                ).add_to(m)

    st_folium(m, width=1000, height=600)

# --- TAB 2: STATIC PRINT ---
with tab2:
    st.subheader("Generate High-Resolution Print")
    st.write(f"Click below to render at **{export_dpi} DPI**. Note: The preview below is compressed for speed; the downloaded file will be sharp.")

    use_adjust_text = st.checkbox("Auto-Adjust Labels (Prevents Overlap)", value=True)

    if st.button("Generate Print Image"):
        with st.spinner("Rendering... this takes longer at high DPI..."):

            fig, ax = plt.subplots(figsize=(24, 24))

            bounds_gdf = display_gdf.to_crs(epsg=3857)
            minx, miny, maxx, maxy = bounds_gdf.total_bounds
            ax.set_xlim(minx, maxx)
            ax.set_ylim(miny, maxy)

            cx.add_basemap(ax, source=cx.providers.CartoDB.PositronNoLabels, zoom=10)

            if display_isds is not None and not display_isds.empty:
                display_isds.plot(ax=ax, column='NAME', cmap='Set3', alpha=fill_opacity, zorder=2)
                display_isds.plot(ax=ax, facecolor='none', edgecolor=isd_outline_color, linestyle='--', linewidth=1.5, zorder=3)

                isd_texts = []
                for x, y, label in zip(display_isds.geometry.centroid.x, display_isds.geometry.centroid.y, display_isds['NAME']):
                    clean = label.replace('Independent School District', 'ISD').replace('Consolidated', 'Cons.')
                    t = ax.text(x, y, clean, fontsize=font_size_labels, color=isd_outline_color, ha='center', weight='bold',
                            zorder=4, path_effects=[pe.withStroke(linewidth=3, foreground="white")])
                    isd_texts.append(t)

            if map_type == "Gulf Coast Region (13 Counties)":
                display_gdf.to_crs(epsg=3857).plot(ax=ax, column='NAME', cmap='Pastel1', alpha=fill_opacity, zorder=2)

            display_gdf.to_crs(epsg=3857).plot(ax=ax, facecolor='none', edgecolor=outline_color, linewidth=3, zorder=4)

            display_cities.plot(ax=ax, facecolor='gray', edgecolor='none', alpha=0.1, zorder=3)

            city_texts = []
            for x, y, label in zip(display_cities.geometry.centroid.x, display_cities.geometry.centroid.y, display_cities[city_col]):
                t = ax.text(x, y, label, fontsize=font_size_labels, color=text_color, ha='center', weight='bold',
                        zorder=5, path_effects=[pe.withStroke(linewidth=2, foreground="white")])
                city_texts.append(t)

            if map_type == "Gulf Coast Region (13 Counties)":
                 for x, y, label in zip(bounds_gdf.geometry.centroid.x, bounds_gdf.geometry.centroid.y, bounds_gdf['NAME']):
                    ax.text(x, y, label.upper(), fontsize=font_size_labels+4, color=outline_color, ha='center', weight='heavy',
                            zorder=5, path_effects=[pe.withStroke(linewidth=4, foreground="white")])

            if use_adjust_text:
                all_texts = city_texts + (isd_texts if display_isds is not None else [])
                if all_texts:
                    adjust_text(
                        all_texts,
                        ax=ax,
                        expand_points=(1.2, 1.2),
                        arrowprops=dict(arrowstyle='-', color='gray', alpha=0.5)
                    )

            plt.title(title, fontsize=font_size_header)
            plt.axis('off')

            fn = "map_export.png"
            img = io.BytesIO()
            plt.savefig(img, format='png', dpi=export_dpi)
            plt.close()

            st.success("Map Rendered!")
            st.image(img, caption=f"Preview (Download for full {export_dpi} DPI resolution)")

            st.download_button("📥 Download High-Res Map", data=img, file_name=f"workforce_map_{export_dpi}dpi.png", mime="image/png")
