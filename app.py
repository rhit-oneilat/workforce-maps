import streamlit as st
import geopandas as gpd
import matplotlib.pyplot as plt
import contextily as cx
import matplotlib.patheffects as pe
import folium
from streamlit_folium import st_folium
from adjustText import adjust_text
import io
import os
from PIL import Image

# --- CONFIG ---
Image.MAX_IMAGE_PIXELS = None

# --- CACHE SETUP ---
# Saves tiles locally so you don't re-download them every time
cache_dir = os.path.join(os.getcwd(), "tile_cache")
if not os.path.exists(cache_dir):
    os.makedirs(cache_dir)
cx.set_cache_dir(cache_dir)

st.set_page_config(layout="wide", page_title="Workforce Solutions Map Generator")

# --- HELPER: CLEAN GEOMETRY ---
def clean_geoms(gdf):
    if gdf is None or gdf.empty:
        return gdf
    gdf = gdf[~gdf.is_empty]
    gdf = gdf[gdf.geometry.type.isin(['Polygon', 'MultiPolygon'])]
    return gdf

# --- CACHED DATA LOADING ---
@st.cache_data
def load_data():
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

    gdf_places = gdf_places.to_crs(epsg=3857)
    gdf_places['area_sq_mi'] = gdf_places.geometry.area * 3.86102e-7

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

st.sidebar.subheader("📐 Quality")
export_dpi = st.sidebar.select_slider("Image Resolution (DPI)", options=[150, 300, 600], value=300)

font_size_header = st.sidebar.slider("Title Font Size", 10, 100, 32)
font_size_labels = st.sidebar.slider("City Label Size", 4, 40, 10)
fill_opacity = st.sidebar.slider("Fill Opacity", 0.0, 1.0, 0.4)

# --- MAP PREPARATION ---

if map_type == "Gulf Coast Region (13 Counties)":
    main_gdf = region_gdf
    main_gdf_3857 = main_gdf.to_crs(epsg=3857)
    clipped_cities = clean_geoms(gpd.clip(gdf_places, main_gdf_3857))
    display_gdf = main_gdf
    display_isds = None
    title = "Workforce Solutions Gulf Coast Region"

else: # Brazoria
    brazoria_gdf = region_gdf[region_gdf['NAME'] == 'Brazoria']
    brazoria_3857 = brazoria_gdf.to_crs(epsg=3857)

    isds_3857 = gdf_isds.to_crs(epsg=3857)
    clipped_isds = clean_geoms(gpd.clip(isds_3857, brazoria_3857))
    clipped_cities = clean_geoms(gpd.clip(gdf_places, brazoria_3857))

    display_gdf = brazoria_gdf
    display_isds = clipped_isds
    title = "Brazoria County: City Limits & ISDs"

display_cities = clipped_cities[clipped_cities['area_sq_mi'] >= min_area]

# --- TAB 1: INTERACTIVE MAP ---
tab1, tab2 = st.tabs(["🗺️ Interactive Map", "🖨️ Print Export (PDF/PNG)"])

with tab1:
    st.subheader(f"Interactive View: {title}")
    m = folium.Map(location=[29.5, -95.5], zoom_start=9, tiles=None)
    folium.TileLayer(tiles="CartoDB positron", name="Light Map", detect_retina=True).add_to(m)

    folium.GeoJson(
        display_gdf.to_crs(epsg=4326),
        style_function=lambda x: {
            'fillColor': fill_color_hex, 'color': outline_color, 'weight': 2, 'fillOpacity': fill_opacity
        },
        tooltip=folium.GeoJsonTooltip(fields=['NAME'], aliases=['County:'])
    ).add_to(m)

    if display_isds is not None and not display_isds.empty:
        folium.GeoJson(
            display_isds.to_crs(epsg=4326),
            style_function=lambda x: {
                'fillColor': 'orange', 'color': isd_outline_color, 'weight': 1, 'dashArray': '5, 5', 'fillOpacity': 0.1
            },
            tooltip=folium.GeoJsonTooltip(fields=['NAME'], aliases=['ISD:'])
        ).add_to(m)

    if not display_cities.empty:
        cities_4326 = display_cities.to_crs(epsg=4326)
        for idx, row in cities_4326.iterrows():
            if row.geometry and not row.geometry.is_empty:
                folium.CircleMarker(
                    location=[row.geometry.centroid.y, row.geometry.centroid.x],
                    radius=3, color='red', fill=True,
                    tooltip=f"{row[city_col]} ({row['area_sq_mi']:.1f} sq mi)"
                ).add_to(m)

    st_folium(m, width=1000, height=600)

# --- TAB 2: STATIC PRINT ---
with tab2:
    st.subheader("Generate Print Files")
    st.write(f"Click below to render at **{export_dpi} DPI**.")

    use_adjust_text = st.checkbox("Auto-Adjust Labels (Prevents Overlap)", value=True)

    if st.button("Generate Map"):
        progress_text = "Starting engine..."
        my_bar = st.progress(0, text=progress_text)

        try:
            # STEP 1: SETUP
            my_bar.progress(10, text="Setting up canvas...")
            fig, ax = plt.subplots(figsize=(24, 24))

            # --- CRITICAL FIX FOR BLANK PDF ---
            # This tells matplotlib: "Rasterize everything below Z-Order 1 (the map tiles),
            # but keep everything above Z-Order 1 (Text, Lines) as Vectors."
            ax.set_rasterization_zorder(1)

            bounds_gdf = display_gdf.to_crs(epsg=3857)
            minx, miny, maxx, maxy = bounds_gdf.total_bounds
            ax.set_xlim(minx, maxx)
            ax.set_ylim(miny, maxy)

            # STEP 2: DOWNLOAD TILES
            # We use Zoom 11 or 12 as a safe "Medium" default that won't crash
            my_bar.progress(25, text="Downloading background tiles...")
            cx.add_basemap(ax, source=cx.providers.CartoDB.PositronNoLabels, zoom=12, zorder=0)

            # STEP 3: PLOT VECTORS (Z-Order > 1 to stay Vector)
            my_bar.progress(50, text="Plotting counties and districts...")

            # Draw ISDs
            if display_isds is not None and not display_isds.empty:
                display_isds.plot(ax=ax, column='NAME', cmap='Set3', alpha=fill_opacity, zorder=2)
                display_isds.plot(ax=ax, facecolor='none', edgecolor=isd_outline_color, linestyle='--', linewidth=1.5, zorder=3)

                isd_texts = []
                for x, y, label in zip(display_isds.geometry.centroid.x, display_isds.geometry.centroid.y, display_isds['NAME']):
                    clean = label.replace('Independent School District', 'ISD').replace('Consolidated', 'Cons.')
                    t = ax.text(x, y, clean, fontsize=font_size_labels, color=isd_outline_color, ha='center', weight='bold',
                            zorder=4, path_effects=[pe.withStroke(linewidth=3, foreground="white")])
                    isd_texts.append(t)

            # Draw Region
            if map_type == "Gulf Coast Region (13 Counties)":
                display_gdf.to_crs(epsg=3857).plot(ax=ax, column='NAME', cmap='Pastel1', alpha=fill_opacity, zorder=2)

            display_gdf.to_crs(epsg=3857).plot(ax=ax, facecolor='none', edgecolor=outline_color, linewidth=3, zorder=4)

            # Draw Cities
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

            plt.title(title, fontsize=font_size_header)
            plt.axis('off')

            # STEP 4: ADJUST TEXT
            if use_adjust_text:
                my_bar.progress(70, text="Optimizing label placement (Physics engine)...")
                all_texts = city_texts + (isd_texts if display_isds is not None else [])
                if all_texts:
                    adjust_text(
                        all_texts, ax=ax, expand_points=(1.2, 1.2),
                        arrowprops=dict(arrowstyle='-', color='gray', alpha=0.5)
                    )

            # STEP 5: SAVE FILES
            my_bar.progress(85, text=f"Saving high-res image ({export_dpi} DPI)...")

            # --- SAVE PNG ---
            img_png = io.BytesIO()
            plt.savefig(img_png, format='png', dpi=export_dpi, bbox_inches='tight')

            # --- SAVE PDF ---
            # DPI=300 here controls the resolution of the rasterized background layer inside the PDF
            my_bar.progress(95, text="Generating Vector PDF...")
            img_pdf = io.BytesIO()
            plt.savefig(img_pdf, format='pdf', dpi=300, bbox_inches='tight')

            plt.close()

            my_bar.progress(100, text="Complete!")
            st.success("Rendering Complete!")

            col1, col2 = st.columns(2)
            with col1:
                st.image(img_png, caption=f"Preview ({export_dpi} DPI)")
                st.download_button("📥 Download Image (PNG)", data=img_png, file_name="map.png", mime="image/png")

            with col2:
                st.info("Best for Printing:")
                st.download_button("📄 Download Vector (PDF)", data=img_pdf, file_name="map.pdf", mime="application/pdf")

        except Exception as e:
            st.error(f"An error occurred: {e}")
            my_bar.empty()
