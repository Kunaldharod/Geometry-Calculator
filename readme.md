# Geometry Calculator Pro

**Geometry Calc** is a powerful QGIS 3 plugin designed to streamline spatial analysis by automatically calculating geometry properties (area, length, point count) and generating buffers for vector layers[cite: 1]. 

Built with performance in mind, this plugin utilizes QGIS background tasks (`QgsTask`) to ensure the user interface remains fully responsive during heavy batch processing[cite: 1].

---

## 🚀 Features

* **Comprehensive Geometry Calculations:** Automatically calculates Area (in km² for polygons), Length (in km for lines), and Point Counts[cite: 1].
* **Integrated Buffer Analysis:** Optionally generate buffer zones around geometries by specifying a custom distance in meters[cite: 1].
* **Batch Processing:** Process multiple spatial files at once (supports `.shp`, `.kml`, `.kmz`, `.gpkg`, `.geojson`, and `.gml`) or seamlessly include the currently active layer from QGIS[cite: 1].
* **Robust Export Options:** Export both original geometries and calculated buffer zones into Shapefile (`.shp`) and KML (`.kml`) formats[cite: 1].
* **Detailed Reporting:** Generates a structured CSV output containing feature names, calculated values, buffer areas, and geometry categories for easy reporting and spreadsheet integration[cite: 1].
* **Smart CRS Handling:** Automatically calculates the appropriate UTM zone based on the feature's centroid to ensure highly accurate area and length measurements[cite: 1].

---

## 📋 Requirements

* **QGIS Version:** 3.0 or higher[cite: 1].
* **Operating System:** Windows, macOS, or Linux.

---

## 🛠️ Installation

### Option 1: Install via QGIS Plugin Repository (Recommended)
*(Note: Available once the plugin is approved and published)*
1. Open QGIS.
2. Navigate to **Plugins** > **Manage and Install Plugins...**
3. Search for **Geometry Calc**.
4. Click **Install Plugin**.

### Option 2: Manual Installation
1. Download the source code from this repository as a `.zip` file.
2. Open QGIS and go to **Settings** > **User Profiles** > **Open Active Profile Folder**.
3. Navigate to `python/plugins/`.
4. Extract the `.zip` file into this folder. Ensure the extracted folder is named `Advanced_Zone_Splitter`[cite: 1].
5. Restart QGIS.
6. Go to **Plugins** > **Manage and Install Plugins...**, find **Geometry Calc**, and check the box to enable it.

---

## 🖥️ How to Use

1. **Launch the Plugin:** Click the Geometry Calc icon in the QGIS toolbar or navigate to the **Plugins** > **Geometry Calc** menu[cite: 1].
2. **Select Files:** Click **Select Spatial Files** to browse your computer, or check **Include active layer from QGIS**[cite: 1].
3. **Configure Buffer Analysis:** If you need buffer calculations, check **Enable Buffer Analysis** and specify the distance in meters[cite: 1].
4. **Choose Exports:** Select your preferred export formats (Shapefile and/or KML)[cite: 1].
5. **Set Output Directory:** Choose the folder where all calculated files and CSV reports will be saved[cite: 1].
6. **Run:** Click **Run Analysis**[cite: 1]. You can track the progress via the status log and progress bar. The interface will not freeze during processing.

---

## 📁 Output Files

Upon successful completion, the plugin will generate the following in your selected output directory[cite: 1]:
* `[layer_name]_geometry_calc_output.csv` - Data report.
* `[layer_name]_original.shp` / `.kml` - Projected original geometries.
* `[layer_name]_buffer.shp` / `.kml` - Generated buffer geometries (if enabled).
* `analysis_summary_report.txt` - A text summary of all processed files and total calculated areas/lengths[cite: 1].

Additionally, the generated layers will automatically be added to your active QGIS map canvas[cite: 1].

---

## 🐛 Bug Reports & Feature Requests

If you encounter a bug or have an idea for a new feature, please open an issue in the GitHub issue tracker.

---
