import streamlit as st
import geopandas as gpd
import matplotlib.pyplot as plt
import contextily as cx
import matplotlib.patheffects as pe
import folium
from streamlit_folium import st_folium
from adjustText import adjust_text # The magic label fixer
import io

st.set_page_config(layout="wide", page_title="Workforce Solutions Map Generator")

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

    # Detect city column
    city_col = 'CITY_NM' if 'CITY_NM' in gdf_places.columns else 'NAME'

    # Calculate Area in Square Miles (Approximate) for filtering
    # We project to 3857 (meters) then convert: sq_meters * 3.86e-7 = sq_miles
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
# This is the new filter
min_area = st.sidebar.slider("Hide Cities Smaller Than (Sq Miles)", 0.0, 50.0, 5.0, help="Increasing this removes small towns.")

st.sidebar.subheader("🎨 Colors")
fill_color_hex = st.sidebar.color_picker("Region Fill Color", "#b3cde3")
outline_color = st.sidebar.color_picker("Outline Color", "#000000")
text_color = st.sidebar.color_picker("City Label Color", "#8B0000")
isd_outline_color = st.sidebar.color_picker("ISD Color (Brazoria)", "#000080")

st.sidebar.subheader("📐 Dimensions")
font_size_header = st.sidebar.slider("Title Font Size", 10, 50, 24)
font_size_labels = st.sidebar.slider("City Label Size", 4, 20, 8)
fill_opacity = st.sidebar.slider("Fill Opacity", 0.0, 1.0, 0.4)

# --- MAP PREPARATION ---

if map_type == "Gulf Coast Region (13 Counties)":
    main_gdf = region_gdf
    main_gdf_3857 = main_gdf.to_crs(epsg=3857)

    # Clip cities
    clipped_cities = gpd.clip(gdf_places, main_gdf_3857)

    display_gdf = main_gdf
    display_isds = None
    title = "Workforce Solutions Gulf Coast Region"

else: # Brazoria
    brazoria_gdf = region_gdf[region_gdf['NAME'] == 'Brazoria']
    brazoria_3857 = brazoria_gdf.to_crs(epsg=3857)

    # Clip ISDs
    isds_3857 = gdf_isds.to_crs(epsg=3857)
    clipped_isds = gpd.clip(isds_3857, brazoria_3857)

    # Clip Cities
    clipped_cities = gpd.clip(gdf_places, brazoria_3857)

    display_gdf = brazoria_gdf
    display_isds = clipped_isds
    title = "Brazoria County: City Limits & ISDs"

# --- APPLY FILTER ---
# This removes the small cities based on the slider
display_cities = clipped_cities[clipped_cities['area_sq_mi'] >= min_area]
filtered_count = len(clipped_cities) - len(display_cities)
st.sidebar.caption(f"Hidden Cities: {filtered_count}")

# --- TAB 1: INTERACTIVE MAP ---
tab1, tab2 = st.tabs(["🗺️ Interactive Map", "🖨️ High-Res Print Preview"])

with tab1:
    st.subheader(f"Interactive View: {title}")

    # Folium Setup
    m = folium.Map(location=[29.5, -95.5], zoom_start=8, tiles="CartoDB positron")

    # Region Layer
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

    # ISD Layer
    if display_isds is not None:
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

    # City Markers (Only the filtered ones)
    cities_4326 = display_cities.to_crs(epsg=4326)
    for idx, row in cities_4326.iterrows():
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
    st.write("Click below to render. **Note:** 'Auto-Adjust Labels' adds processing time but prevents overlaps.")

    use_adjust_text = st.checkbox("Auto-Adjust Labels (Prevents Overlap)", value=True)

    if st.button("Generate Print Image"):
        with st.spinner("Rendering... (If auto-adjust is on, this takes a few extra seconds)"):

            fig, ax = plt.subplots(figsize=(24, 24))

            # Bounds
            bounds_gdf = display_gdf.to_crs(epsg=3857)
            minx, miny, maxx, maxy = bounds_gdf.total_bounds
            ax.set_xlim(minx, maxx)
            ax.set_ylim(miny, maxy)

            cx.add_basemap(ax, source=cx.providers.CartoDB.PositronNoLabels)

            # Draw ISDs
            if display_isds is not None:
                display_isds.plot(ax=ax, column='NAME', cmap='Set3', alpha=fill_opacity, zorder=2)
                display_isds.plot(ax=ax, facecolor='none', edgecolor=isd_outline_color, linestyle='--', linewidth=1.5, zorder=3)

                # ISD Labels
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

            # City Labels
            city_texts = []
            for x, y, label in zip(display_cities.geometry.centroid.x, display_cities.geometry.centroid.y, display_cities[city_col]):
                t = ax.text(x, y, label, fontsize=font_size_labels, color=text_color, ha='center', weight='bold',
                        zorder=5, path_effects=[pe.withStroke(linewidth=2, foreground="white")])
                city_texts.append(t)

            # County Labels
            if map_type == "Gulf Coast Region (13 Counties)":
                 for x, y, label in zip(bounds_gdf.geometry.centroid.x, bounds_gdf.geometry.centroid.y, bounds_gdf['NAME']):
                    ax.text(x, y, label.upper(), fontsize=font_size_labels+4, color=outline_color, ha='center', weight='heavy',
                            zorder=5, path_effects=[pe.withStroke(linewidth=4, foreground="white")])

            # --- AUTO-ADJUST LOGIC ---
            if use_adjust_text:
                # We combine city_texts and isd_texts (if any) to repel them all from each other
                all_texts = city_texts + (isd_texts if display_isds is not None else [])

                # adjust_text moves the labels to avoid overlapping each other AND the city dots
                adjust_text(
                    all_texts,
                    ax=ax,
                    expand_points=(1.2, 1.2), # Push text further from points
                    arrowprops=dict(arrowstyle='-', color='gray', alpha=0.5) # Add lines if they move too far
                )

            plt.title(title, fontsize=font_size_header)
            plt.axis('off')

            fn = "map_export.png"
            img = io.BytesIO()
            plt.savefig(img, format='png', dpi=300)
            plt.close()

            st.success("Map Rendered!")
            st.image(img)
            st.download_button("📥 Download Map", data=img, file_name="workforce_map.png", mime="image/png")
